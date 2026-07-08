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
import sys
import time
from datetime import datetime, timezone

import requests
from fastapi import FastAPI, Header, HTTPException, Request

# Política PURA (stdlib only) — máscara de OTP + verificação de token do inbox.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _sms_policy import extract_bearer, mask_otp, require_token  # noqa: E402

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

# ── Modo conversacional (ElevenLabs Conversational AI) — OFF por padrão ──
# Só ativa quando ELEVENLABS_AGENT_ID está setado. Enquanto não estiver, o webhook
# usa o TTS simples (_speak) exatamente como antes. Ver docstring de _start_conversational.
ELEVENLABS_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID", "").strip()
ELEVENLABS_API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
# WS do bridge de áudio bidirecional (Telnyx media stream ↔ ElevenLabs). Precisa ser
# provisionado/iterado ao vivo na VPS — enquanto vazio, o modo conversacional loga e cai
# no TTS simples em vez de fingir que a ponte existe.
ELEVENLABS_BRIDGE_WS_URL = os.environ.get("ELEVENLABS_BRIDGE_WS_URL", "").strip()
ELEVENLABS_SIGNED_URL_API = (
    "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url"
)


def conversational_enabled() -> bool:
    return bool(ELEVENLABS_AGENT_ID)

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


def _elevenlabs_signed_url() -> str:
    """Pede à ElevenLabs uma signed URL para o agente conversacional configurado.

    Endpoint documentado: GET /v1/convai/conversation/get-signed-url?agent_id=...
    Retorna string vazia em qualquer falha (o chamador cai no TTS simples).
    """
    if not (ELEVENLABS_AGENT_ID and ELEVENLABS_API_KEY):
        return ""
    try:
        resp = requests.get(
            ELEVENLABS_SIGNED_URL_API,
            params={"agent_id": ELEVENLABS_AGENT_ID},
            headers={"xi-api-key": ELEVENLABS_API_KEY},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("signed_url", "")
    except (requests.RequestException, ValueError):
        return ""


def _start_conversational(call_control_id: str, greeting: str) -> bool:
    """Inicia conversa por IA (ElevenLabs) numa chamada atendida.

    Estado hoje:
      • A iniciação (signed URL da ElevenLabs + streaming_start da Telnyx apontando pro
        bridge) está implementada e é a parte documentada/estável.
      • O BRIDGE de áudio bidirecional (WS que faz Telnyx media stream ↔ ElevenLabs
        Conversational WS em tempo real) precisa ser provisionado e iterado AO VIVO na VPS,
        com uma ligação de teste real — não dá pra validar localmente. Enquanto
        ELEVENLABS_BRIDGE_WS_URL não estiver setado, esta função devolve False e o chamador
        usa o TTS simples (sem fingir que a ponte existe).

    Retorna True se conseguiu iniciar o streaming conversacional; False caso contrário.
    """
    if not ELEVENLABS_BRIDGE_WS_URL:
        _append_jsonl(CALL_LOG_PATH, {
            "at": _now_iso(), "event": "conversational_skipped",
            "reason": "ELEVENLABS_BRIDGE_WS_URL ausente (bridge de áudio não provisionado)",
            "call_control_id": call_control_id,
        })
        return False

    signed_url = _elevenlabs_signed_url()
    if not signed_url:
        _append_jsonl(CALL_LOG_PATH, {
            "at": _now_iso(), "event": "conversational_skipped",
            "reason": "falha ao obter signed_url da ElevenLabs",
            "call_control_id": call_control_id,
        })
        return False

    key = os.environ.get("TELNYX_API_KEY")
    if not key:
        return False
    try:
        # O bridge recebe a signed_url via querystring e conecta na ElevenLabs por dentro.
        stream_url = ELEVENLABS_BRIDGE_WS_URL
        sep = "&" if "?" in stream_url else "?"
        stream_url = "{}{}signed_url={}".format(stream_url, sep, signed_url)
        requests.post(
            "{}/{}/actions/streaming_start".format(TELNYX_CALLS_API, call_control_id),
            headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
            json={
                "stream_url": stream_url,
                "stream_track": "both_tracks",
                "stream_bidirectional_mode": "rtp",
            },
            timeout=10,
        )
        # Enquanto o bridge assume, um cumprimento curto evita silêncio no atendimento.
        if greeting:
            _speak(call_control_id, greeting)
        _append_jsonl(CALL_LOG_PATH, {
            "at": _now_iso(), "event": "conversational_started",
            "call_control_id": call_control_id,
        })
        return True
    except requests.RequestException as exc:
        _append_jsonl(CALL_LOG_PATH, {
            "at": _now_iso(), "event": "conversational_error",
            "reason": str(exc)[:200], "call_control_id": call_control_id,
        })
        return False


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

    # Quando a chamada é atendida: se o modo conversacional (ElevenLabs) estiver
    # habilitado, tenta iniciar a conversa por IA; senão (ou se a iniciação falhar),
    # cai no TTS simples com o texto que veio no client_state — comportamento original.
    if event_type == "call.answered" and ccid:
        message = _decode_state(payload.get("client_state", ""))
        if conversational_enabled():
            started = _start_conversational(ccid, greeting=message or "Um momento.")
            if not started and message:
                _speak(ccid, message)  # fallback gracioso
        elif message:
            _speak(ccid, message)

    return {"ok": True}


# ─────────────────────────────── Conveniências ───────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "verify_signature": VERIFY_SIGNATURE}


@app.get("/sms/last")
def last_sms(authorization: str = Header(None)):
    """Retorna o último SMS recebido — AUTENTICADO e com OTP MASCARADO.

    P0 fechado: este endpoint sobe em 0.0.0.0 atrás do Caddy público. Sem auth ele
    devolvia o último SMS COM o verification_code (OTP/2FA) em claro. Agora:
      - exige `Authorization: Bearer <TELNYX_INBOX_API_KEY>`;
      - sem a env configurada -> 503 (nunca abre sem auth);
      - token errado/ausente -> 401;
      - a resposta HTTP passa por mask_otp (o arquivo local pode manter o código cru,
        a resposta pela rede nunca devolve OTP em claro).
    """
    expected = (os.environ.get("TELNYX_INBOX_API_KEY", "") or "").strip()
    if not expected:
        # Fail-closed: sem chave configurada, o endpoint não abre.
        raise HTTPException(503, "auth do inbox não configurada (TELNYX_INBOX_API_KEY ausente).")
    provided = extract_bearer(authorization)
    if not require_token(provided, expected):
        raise HTTPException(401, "token do inbox inválido ou ausente.")

    if not os.path.isfile(SMS_INBOX_PATH):
        return {"message": "nenhum SMS recebido ainda"}
    last = None
    with open(SMS_INBOX_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last = line
    if not last:
        return {"message": "nenhum SMS recebido ainda"}
    return mask_otp(json.loads(last))


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))
