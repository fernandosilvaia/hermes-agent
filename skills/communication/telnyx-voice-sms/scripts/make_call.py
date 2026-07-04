"""
make_call.py — Faz uma ligação via Telnyx Call Control e toca um texto (TTS simples).

Como o Call Control é orientado a webhook, o fluxo é:
  1. Este script dispara o DIAL (POST /v2/calls) e coloca a mensagem no `client_state`
     (base64), para o webhook saber o que falar.
  2. Quando a Telnyx envia `call.answered`, o webhook emite o comando `speak`
     com esse texto. (Ver webhook_server.py.)

Uso como biblioteca:
    from make_call import make_call
    make_call(to="+16174505166", message="Olá, isto é um teste do Hermes.")

Uso como CLI:
    python make_call.py --to +16174505166 --message "Olá, teste do Hermes"
    python make_call.py --self --message "teste"   # liga para o próprio número

Env necessárias:
    TELNYX_API_KEY          (obrigatória)
    TELNYX_CONNECTION_ID    (obrigatória — ID da Call Control Application / Voice API App)
    TELNYX_NUMBER           (opcional, padrão +16174505166 — `from`)
    TELNYX_WEBHOOK_URL      (opcional aqui se já configurado no App; recomendado passar)

⚠️ REGRA DE NEGÓCIO: ligar para números de teste próprios é OK sem confirmação.
   QUALQUER campanha ou ligação para terceiros externos exige confirmação explícita
   do Fernando ANTES. Ver aviso no SKILL.md.
"""

import argparse
import base64
import json
import os

import requests

TELNYX_CALLS_API = "https://api.telnyx.com/v2/calls"
DEFAULT_FROM = os.environ.get("TELNYX_NUMBER", "+16174505166")


def _api_key() -> str:
    key = os.environ.get("TELNYX_API_KEY")
    if not key:
        raise RuntimeError(
            "TELNYX_API_KEY não está no ambiente. Rode via cofre (doppler run / op run)."
        )
    return key


def _encode_state(message: str) -> str:
    """Guarda a mensagem no client_state (base64) para o webhook recuperar no answered."""
    return base64.b64encode(message.encode("utf-8")).decode("ascii")


def make_call(to: str, message: str, from_number: str = None,
              amd: str = "premium") -> dict:
    """
    Dispara uma ligação. O texto é falado quando a chamada é atendida (via webhook).
    amd: 'premium' (recomendado, detecta humano x caixa postal) ou 'disabled'.
    """
    connection_id = os.environ.get("TELNYX_CONNECTION_ID")
    if not connection_id:
        raise RuntimeError(
            "TELNYX_CONNECTION_ID não está no ambiente. É o ID da sua Call Control "
            "Application (Voice API App) no portal Telnyx."
        )

    payload = {
        "connection_id": connection_id,
        "to": to,
        "from": from_number or DEFAULT_FROM,
        "client_state": _encode_state(message),
    }
    webhook_url = os.environ.get("TELNYX_WEBHOOK_URL")
    if webhook_url:
        payload["webhook_url"] = webhook_url
    if amd and amd != "disabled":
        payload["answering_machine_detection"] = amd  # 'premium'

    resp = requests.post(
        TELNYX_CALLS_API,
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Telnyx retornou {resp.status_code}: {resp.text}")

    data = resp.json().get("data", {})
    return {
        "call_control_id": data.get("call_control_id"),
        "call_leg_id": data.get("call_leg_id"),
        "to": to,
        "from": payload["from"],
        "amd": amd,
        "status": "discando — o texto será falado quando atender (via webhook)",
    }


def _cli():
    p = argparse.ArgumentParser(description="Ligar via Telnyx Call Control (Hermes)")
    p.add_argument("--to", help="Número destino E.164")
    p.add_argument("--self", action="store_true", help="Liga para o próprio número Telnyx")
    p.add_argument("--message", required=True, help="Texto a ser falado (TTS)")
    p.add_argument("--from", dest="from_number", default=None)
    p.add_argument("--amd", default="premium", choices=["premium", "disabled"])
    args = p.parse_args()

    to = DEFAULT_FROM if args.self else args.to
    if not to:
        p.error("informe --to ou use --self")
    out = make_call(to, args.message, args.from_number, args.amd)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
