"""
ask_vps.py — Delega uma tarefa/pergunta para o Hermes que roda 24/7 na VPS da Axtro.

Uso como biblioteca:
    from ask_vps import ask_vps_hermes
    ask_vps_hermes("quantos emails não lidos eu tenho?")

Uso como CLI:
    python ask_vps.py "quantos emails não lidos eu tenho?"

Env necessárias:
    HERMES_VPS_API_SERVER_KEY   (obrigatória — mesmo segredo usado no Caddy e no
                                  API_SERVER_KEY da VPS)
    HERMES_VPS_URL              (opcional, padrão https://hermes.axtroai.com)
"""

import argparse
import json
import os

import requests

DEFAULT_URL = os.environ.get("HERMES_VPS_URL", "https://hermes.axtroai.com")


def _api_key() -> str:
    key = os.environ.get("HERMES_VPS_API_SERVER_KEY")
    if not key:
        raise RuntimeError(
            "HERMES_VPS_API_SERVER_KEY não está no ambiente. Rode via cofre "
            "(doppler run / op run) para injetar a credencial."
        )
    return key


def ask_vps_hermes(message: str, timeout: int = 120) -> str:
    """Manda uma mensagem para o Hermes da VPS e retorna a resposta em texto."""
    resp = requests.post(
        f"{DEFAULT_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json={
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": message}],
        },
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Hermes VPS retornou {resp.status_code}: {resp.text}")

    data = resp.json()
    choices = data.get("choices", [])
    if not choices:
        return json.dumps(data, ensure_ascii=False)
    return choices[0].get("message", {}).get("content", "")


def _cli():
    p = argparse.ArgumentParser(description="Delegar tarefa para o Hermes da VPS")
    p.add_argument("message", help="A pergunta/tarefa a delegar")
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args()
    print(ask_vps_hermes(args.message, args.timeout))


if __name__ == "__main__":
    _cli()
