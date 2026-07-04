"""
webhook_server.py — Recebe webhooks da Telnyx (SMS recebido + eventos de voz).

Roda como processo separado (FastAPI/uvicorn), atrás do reverse proxy Caddy (HTTPS)
que já existe na VPS. A skill NÃO configura o Caddy — só espera ser servida em algo como:
    https://SEU-DOMINIO/webhooks/telnyx/sms
    https://SEU-DOMINIO/webhooks/telnyx/voice

Endpoints:
    POST /webhooks/telnyx/sms    → grava SMS recebido no inbox (arquivo JSONL)
    POST /webhooks/telnyx/voice  → eventos de call; fala o texto quando a chamada é atendida
    GET  /health                 → healthcheck simples
    GET  /sms/last               → último SMS recebido (conveniência p/ o agente)

Segurança:
    - Valida a assinatura Ed25519 de TODA requisição (headers telnyx-signature-ed25519
      + telnyx-timestamp). String assinada = "<timestamp>|<corpo cru>".
    - Rejeita timestamps velhos (> TELNYX_TOLERANCE_SECONDS) contra replay.
    - TELNYX_API_KEY / chaves nunca são logadas.

Env:
    TELNYX_PUBLIC_KEY         (obrigatória p/ validar assinatura — base64, do portal Telnyx:
                               Account Settings > Keys & Credentials > Public Key)
    TELNYX_API_KEY            (obrigatória p/ emitir o comando 'speak' nas ligações)
    SMS_INBOX_PATH            (opcional, padrão /opt/data/telnyx_sms_inbox.jsonl)
    CALL_LOG_PATH             (opcional, padrão /opt/data/telnyx_call_log.jsonl)
    TELNYX_TOLERANCE_SECONDS  (opcional, padrão 300)
    TELNYX_VERIFY_SIGNATURE   (opcional, padrão "true"; "false" só p/ debug local)

Rodar local:
    uvicorn webhook_server:app --host 0.0.0.0 --port 8080
"""

import base64
import json
import os
import re
import time
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Header, HTTPException, Request

# PyNaCl para verificação Ed25519
try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "PyNaCl é necessário para validar a assinatura Telnyx. "
        "Instale: pip install pynacl"
    ) from exc

app = FastAPI(title="Hermes · Telnyx Webhooks")

SMS_INBOX_PATH = os.environ.get("SMS_INBOX_PATH", "/opt/data/telnyx_sms_inbox.jsonl")
CALL_LOG_PATH = os.environ.get("CALL_LOG_PATH", "/opt/data/telnyx_call_log.jsonl")
TOLERANCE = int(os.environ.get("TELNYX_TOLERANCE_SECONDS", "300"))
VERIFY_SIGNATURE = os.environ.get("TELNYX_VERIFY_SIGNATURE", "true").lower() != "false"
TELNYX_CALLS_API = "https://api.telnyx.com/v2/calls"

# regex para código de verificação (4 a 8 dígitos) — conveniência para OTP de cadastro
_OTP_RE = re.compile(r"\b(\d{4,8})\b")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: str, record: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")


# ─────────────────────────── Verificação de assinatura ───────────────────────────

def _verify_signature(raw_body: bytes, signature_b64: str, timestamp: str) -> None:
    """Levanta HTTPException 401 se a assinatura for inválida/ausente/velha."""
    if not VERIFY_SIGNATURE:
        return  # somente para debug local; NUNCA desligar em produção

    public_key_b64 = os.environ.get("TELNYX_PUBLIC_KEY")
    if not public_key_b64:
        raise HTTPException(500, "TELNYX_PUBLIC_KEY não configurada — não é possível validar.")
    if not signature_b64 or not timestamp:
        raise HTTPException(401, "Headers de assinatura Telnyx ausentes.")

    # anti-replay: rejeita timestamps fora da janela de tolerância
    try:
        ts = int(timestamp)
    except ValueError:
        raise HTTPException(401, "timestamp inválido.")
    if abs(time.time() - ts) > TOLERANCE:
        raise HTTPException(401, "timestamp fora da janela de tolerância (replay?).")

    signed_payload = f"{timestamp}|".encode("utf-8") + raw_body
    try:
        verify_key = VerifyKey(base64.b64decode(public_key_b64))
        verify_key.verify(signed_payload, base64.b64decode(signature_b64))
    except (BadSignatureError, ValueError):
        raise HTTPException(401, "Assinatura Telnyx inválida.")


async def _authenticated_body(
    request: Request,
    signature: str,
    timestamp: str,
) -> dict:
    raw = await request.body()
    _verify_signature(raw, signature, timestamp)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(400, "corpo não é JSON válido.")


# ─────────────────────────────── SMS recebido ───────────────────────────────

@app.post("/webhooks/telnyx/sms")
async def sms_webhook(
    request: Request,
    telnyx_signature_ed25519: str = Header(None),
    telnyx_timestamp: str = Header(None),
):
    event = await _authenticated_body(request, telnyx_signature_ed25519, telnyx_timestamp)
    data = event.get("data", {})
    event_type = data.get("event_type")
    payload = data.get("payload", {})

    # Só nos importa o inbound. Status de saída (sent/delivered) é ignorado (200 mesmo assim).
    if event_type == "message.received":
        text = payload.get("text", "")
        frm = (payload.get("from") or {}).get("phone_number")
        to_list = payload.get("to") or []
        to = to_list[0].get("phone_number") if to_list else None
        otp = None
        m = _OTP_RE.search(text or "")
        if m:
            otp = m.group(1)

        record = {
            "received_at": _now_iso(),
            "telnyx_id": data.get("id"),
            "from": frm,
            "to": to,
            "text": text,
            "verification_code": otp,  # None se não houver número tipo OTP
        }
        _append_jsonl(SMS_INBOX_PATH, record)

    # Telnyx exige 2xx rápido (<2s). Retornamos já.
    return {"ok": True}


# ─────────────────────────────── Eventos de voz ───────────────────────────────

def _speak(call_control_id: str, text: str) -> None:
    """Emite o comando 'speak' (TTS) numa chamada ativa."""
    key = os.environ.get("TELNYX_API_KEY")
    if not key:
        # Sem a chave não dá pra falar; loga e segue (não derruba o webhook).
        _append_jsonl(CALL_LOG_PATH, {
            "at": _now_iso(), "event": "speak_skipped",
            "reason": "TELNYX_API_KEY ausente", "call_control_id": call_control_id,
        })
        return
    requests.post(
        f"{TELNYX_CALLS_API}/{call_control_id}/actions/speak",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"payload": text, "voice": "female", "language": "pt-BR"},
        timeout=10,
    )


def _decode_state(client_state: str) -> str:
    if not client_state:
        return ""
    try:
        return base64.b64decode(client_state).decode("utf-8")
    except Exception:  # noqa: BLE001
        return ""


@app.post("/webhooks/telnyx/voice")
async def voice_webhook(
    request: Request,
    telnyx_signature_ed25519: str = Header(None),
    telnyx_timestamp: str = Header(None),
):
    event = await _authenticated_body(request, telnyx_signature_ed25519, telnyx_timestamp)
    data = event.get("data", {})
    event_type = data.get("event_type")
    payload = data.get("payload", {})
    ccid = payload.get("call_control_id")

    _append_jsonl(CALL_LOG_PATH, {
        "at": _now_iso(),
        "event_type": event_type,
        "call_control_id": ccid,
        "from": payload.get("from"),
        "to": payload.get("to"),
        "result": payload.get("result"),  # presente em call.machine.detection.ended
    })

    # Quando a chamada é atendida, fala o texto que veio no client_state.
    if event_type == "call.answered" and ccid:
        message = _decode_state(payload.get("client_state", ""))
        if message:
            _speak(ccid, message)

    # ──────────────────────────────────────────────────────────────────────
    # GANCHO PARA VERSÃO FUTURA — ElevenLabs Conversational AI:
    # Em vez de _speak() com TTS simples, aqui entraria o bridge para o
    # ElevenLabs (SIP/streaming) para conversa por IA em tempo real, como no
    # padrão do Billion CRM. Não implementado nesta primeira versão.
    # Fluxo: call.answered → abrir stream de mídia (stream_url) → ElevenLabs
    #        Conversational AI conduz o diálogo → eventos de transcrição.
    # ──────────────────────────────────────────────────────────────────────

    return {"ok": True}


# ─────────────────────────────── Conveniências ───────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "verify_signature": VERIFY_SIGNATURE}


@app.get("/sms/last")
def last_sms():
    """Retorna o último SMS recebido (para o agente responder 'chegou algum SMS?')."""
    if not os.path.isfile(SMS_INBOX_PATH):
        return {"message": "nenhum SMS recebido ainda"}
    last = None
    with open(SMS_INBOX_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last = line
    return json.loads(last) if last else {"message": "nenhum SMS recebido ainda"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
