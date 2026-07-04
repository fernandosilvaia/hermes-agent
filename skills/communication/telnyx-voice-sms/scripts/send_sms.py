"""
send_sms.py — Envia SMS pelo número Telnyx da empresa (+1 617 450-5166).

Autentica com TELNYX_API_KEY (lido do ambiente, nunca hardcoded, nunca logado).

Uso como biblioteca:
    from send_sms import send_sms
    send_sms(to="+15551234567", text="Olá do Hermes")

Uso como CLI:
    python send_sms.py --to +15551234567 --text "Olá do Hermes"
    python send_sms.py --self --text "teste"   # envia para o próprio número (validação)

Env necessárias:
    TELNYX_API_KEY            (obrigatória)
    TELNYX_NUMBER            (opcional, padrão +16174505166 — remetente `from`)
    TELNYX_MESSAGING_PROFILE_ID (opcional; se o número já está num profile, dispensável)
"""

import argparse
import json
import os

import requests

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


def send_sms(to: str, text: str, from_number: str = None) -> dict:
    """Envia um SMS. Retorna o id/estado da mensagem. `to` em formato E.164 (+55...)."""
    payload = {"from": from_number or DEFAULT_FROM, "to": to, "text": text}
    profile = os.environ.get("TELNYX_MESSAGING_PROFILE_ID")
    if profile:
        payload["messaging_profile_id"] = profile

    resp = requests.post(
        TELNYX_API,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 400:
        # Não logamos a chave; logamos só o corpo de erro da Telnyx.
        raise RuntimeError(f"Telnyx retornou {resp.status_code}: {resp.text}")

    data = resp.json().get("data", {})
    return {
        "id": data.get("id"),
        "from": payload["from"],
        "to": to,
        "parts": data.get("parts"),
        "status": "enviado",
    }


def _cli():
    p = argparse.ArgumentParser(description="Enviar SMS via Telnyx (Hermes)")
    p.add_argument("--to", help="Número destino em E.164, ex.: +15551234567")
    p.add_argument("--self", action="store_true",
                   help="Envia para o próprio número Telnyx (validação/teste)")
    p.add_argument("--text", required=True)
    p.add_argument("--from", dest="from_number", default=None)
    args = p.parse_args()

    to = DEFAULT_FROM if args.self else args.to
    if not to:
        p.error("informe --to ou use --self")
    out = send_sms(to, args.text, args.from_number)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
