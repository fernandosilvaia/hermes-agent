"""
send_sms.py — Envia SMS pelo número Telnyx da empresa (+1 617 450-5166).

Autentica com TELNYX_API_KEY (lido do ambiente, nunca hardcoded, nunca logado).

GATE PADRÃO DE DRY-RUN (default PERMANENTE): send_sms() NÃO chama a Telnyx a não ser
que TODAS as condições sejam verdadeiras ao mesmo tempo:
  (a) --dry-run NÃO foi passado,
  (b) HERMES_ALLOW_EXECUTE == "true",
  (c) TELNYX_VOICE_SMS_ENABLED == "true",
  (d) o destino está na allowlist (default: só o próprio número TELNYX_NUMBER),
  (e) o teto diário de envios não foi atingido.
Faltando qualquer uma -> retorna o que FARIA, com "dry_run": true (ou "blocked": true),
sem nenhum efeito real. Toda a DECISÃO vive em _send_policy.py (puro, testável).

Uso como biblioteca:
    from send_sms import send_sms
    send_sms(to="+16174505166", text="Olá do Hermes")            # dry-run por padrão
    send_sms(to="+16174505166", text="Olá", dry_run=False)       # só executa com gate aberto

Uso como CLI:
    python send_sms.py --self --text "teste"                # dry-run (default)
    python send_sms.py --to +16174505166 --text "oi" --execute   # tenta enviar (exige gate)
    python send_sms.py --to +15551234567 --text "oi" --execute   # BLOQUEADO (fora da allowlist)

Env necessárias:
    TELNYX_API_KEY               (obrigatória p/ envio real)
    TELNYX_NUMBER                (opcional, padrão +16174505166 — remetente `from`)
    TELNYX_MESSAGING_PROFILE_ID  (opcional)
    TELNYX_ALLOWED_RECIPIENTS    (opcional; CSV E.164 de destinos extras permitidos)
    HERMES_ALLOW_EXECUTE / TELNYX_VOICE_SMS_ENABLED  (gate p/ envio real)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import requests

# Política PURA (stdlib only) — allowlist, teto diário, gate de execução.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _send_policy import (  # noqa: E402
    _ledger_path,
    _load_recipient_allowlist,
    plan_action,
    record_send,
)

TELNYX_API = "https://api.telnyx.com/v2/messages"
DEFAULT_FROM = os.environ.get("TELNYX_NUMBER", "+16174505166")


def _api_key() -> str:
    key = os.environ.get("TELNYX_API_KEY")
    if not key:
        raise RuntimeError(
            "TELNYX_API_KEY não está no ambiente. Rode o Hermes via cofre "
            "(doppler run / op run) para injetar a credencial."
        )
    return key


def _preview(text: str) -> str:
    text = text or ""
    return text if len(text) <= 40 else text[:37] + "..."


def send_sms(to: str, text: str, from_number: str = None,
             dry_run: bool = True, env=None) -> dict:
    """Envia um SMS SÓ se o gate padrão estiver 100% aberto. Caso contrário retorna
    o que faria (dry_run/blocked) sem efeito real. `to` em E.164 (+55...)."""
    env = env if env is not None else os.environ
    plan = plan_action("send_sms", to, dry_run, env=env)
    plan["from"] = from_number or (env.get("TELNYX_NUMBER") or DEFAULT_FROM)
    plan["text_preview"] = _preview(text)

    if not plan["execute"]:
        # dry-run ou bloqueado: NENHUMA chamada à Telnyx.
        return plan

    # ── Efeito real (só chega aqui com allowlist OK, dentro do teto e gate aberto) ──
    payload = {"from": plan["from"], "to": plan["to"], "text": text}
    profile = env.get("TELNYX_MESSAGING_PROFILE_ID")
    if profile:
        payload["messaging_profile_id"] = profile

    resp = requests.post(
        TELNYX_API,
        headers={
            "Authorization": "Bearer {}".format(_api_key()),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 400:
        # Não logamos a chave; logamos só o corpo de erro da Telnyx.
        raise RuntimeError("Telnyx retornou {}: {}".format(resp.status_code, resp.text))

    data = resp.json().get("data", {})
    try:
        record_send(_ledger_path(env), "send_sms", plan["to"])
    except OSError:
        pass  # ledger é best-effort; não derruba um envio bem-sucedido
    plan.update({
        "sent": True,
        "id": data.get("id"),
        "parts": data.get("parts"),
        "status": "enviado",
    })
    return plan


def _cli():
    p = argparse.ArgumentParser(description="Enviar SMS via Telnyx (Hermes)")
    p.add_argument("--to", help="Número destino em E.164, ex.: +16174505166")
    p.add_argument("--self", action="store_true",
                   help="Envia para o próprio número Telnyx (validação/teste)")
    p.add_argument("--text", required=True)
    p.add_argument("--from", dest="from_number", default=None)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=None,
                      help="força modo seguro (default); sempre vence o --execute")
    mode.add_argument("--execute", dest="execute", action="store_true",
                      help="tenta o envio real (exige HERMES_ALLOW_EXECUTE e "
                           "TELNYX_VOICE_SMS_ENABLED e destino na allowlist)")
    args = p.parse_args()

    to = (os.environ.get("TELNYX_NUMBER") or DEFAULT_FROM) if args.self else args.to
    if not to:
        p.error("informe --to ou use --self")

    # --dry-run explícito sempre vence; sem --execute o default é dry-run.
    dry_run = True if args.dry_run else (not args.execute)

    # Aviso de destino fora da allowlist já no CLI (a decisão real é do _send_policy).
    if to not in set(_load_recipient_allowlist(os.environ)):
        print(json.dumps({
            "warning": "destino fora da allowlist — será BLOQUEADO",
            "to": to,
            "allowlist": _load_recipient_allowlist(os.environ),
        }, ensure_ascii=False, indent=2), file=sys.stderr)

    out = send_sms(to, args.text, args.from_number, dry_run=dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
