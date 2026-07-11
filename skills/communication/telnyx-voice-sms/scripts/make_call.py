"""
make_call.py — Faz uma ligação via Telnyx Call Control e toca um texto (TTS simples).

Como o Call Control é orientado a webhook, o fluxo é:
  1. Este script dispara o DIAL (POST /v2/calls) e coloca a mensagem no `client_state`
     (base64), para o webhook saber o que falar.
  2. Quando a Telnyx envia `call.answered`, o webhook emite o comando `speak`.

GATE PADRÃO DE DRY-RUN (default PERMANENTE): make_call() NÃO chama a Telnyx a não ser
que TODAS as condições sejam verdadeiras ao mesmo tempo:
  (a) --dry-run NÃO foi passado,
  (b) HERMES_ALLOW_EXECUTE == "true",
  (c) TELNYX_VOICE_SMS_ENABLED == "true",
  (d) o destino está na allowlist (default: só o próprio número TELNYX_NUMBER),
  (e) o teto diário de ligações não foi atingido.
Faltando qualquer uma -> retorna o que FARIA, com "dry_run": true (ou "blocked": true),
sem discar nada. Toda a DECISÃO vive em _send_policy.py (puro, testável).

⚠️ REGRA DE NEGÓCIO: ligar para o próprio número de teste é OK. QUALQUER ligação para
   terceiros externos exige o destino na allowlist E o gate humano aberto — nunca é
   automático (consentimento/TCPA é responsabilidade do Fernando ANTES).

Uso como biblioteca:
    from make_call import make_call
    make_call(to="+16174505166", message="Olá, teste")            # dry-run por padrão
    make_call(to="+16174505166", message="Olá", dry_run=False)    # só liga com gate aberto

Uso como CLI:
    python make_call.py --self --message "teste"                  # dry-run (default)
    python make_call.py --to +16174505166 --message "oi" --execute    # tenta ligar (exige gate)

Env necessárias:
    TELNYX_API_KEY          (obrigatória p/ ligação real)
    TELNYX_CONNECTION_ID    (obrigatória — ID da Call Control Application / Voice API App)
    TELNYX_NUMBER           (opcional, padrão +16174505166 — `from`)
    TELNYX_WEBHOOK_URL      (opcional aqui se já configurado no App; recomendado passar)
    TELNYX_ALLOWED_RECIPIENTS  (opcional; CSV E.164 de destinos extras permitidos)
    HERMES_ALLOW_EXECUTE / TELNYX_VOICE_SMS_ENABLED  (gate p/ ligação real)

CREDENCIAIS POR PARÂMETRO (multi-tenant, ver skills/communication/telnyx-voice-sms/
scripts/consume_tenant_calls.py): make_call() já aceitava `env` pra sobrescrever a
allowlist/gate/teto por chamada (repassado a _send_policy.plan_action), mas
_api_key() ainda lia TELNYX_API_KEY direto de os.environ, ignorando esse `env` —
então uma chamada tenant-scoped (credencial de outra conta Telnyx, resolvida em
tempo de execução, nunca em os.environ do processo) não tinha como sobrescrever
a API key de verdade. Fix mínimo e retrocompatível: _api_key(env) aceita o mesmo
dict `env`, com fallback pro os.environ real quando omitido — chamadas
existentes (CLI, uso interno da Axtro sem passar `env`) continuam idênticas.
"""
from __future__ import annotations

import argparse
import base64
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

TELNYX_CALLS_API = "https://api.telnyx.com/v2/calls"
DEFAULT_FROM = os.environ.get("TELNYX_NUMBER", "+16174505166")


def _api_key(env=None) -> str:
    env = env if env is not None else os.environ
    key = env.get("TELNYX_API_KEY")
    if not key:
        raise RuntimeError(
            "TELNYX_API_KEY não está no ambiente. Rode via cofre (doppler run / op run)."
        )
    return key


def _encode_state(message: str) -> str:
    """Guarda a mensagem no client_state (base64) para o webhook recuperar no answered."""
    return base64.b64encode((message or "").encode("utf-8")).decode("ascii")


def make_call(to: str, message: str, from_number: str = None,
              amd: str = "premium", dry_run: bool = True, env=None) -> dict:
    """Dispara uma ligação SÓ se o gate padrão estiver 100% aberto. Caso contrário
    retorna o que faria (dry_run/blocked) sem discar. `amd`: 'premium' ou 'disabled'."""
    env = env if env is not None else os.environ
    plan = plan_action("make_call", to, dry_run, env=env)
    plan["from"] = from_number or (env.get("TELNYX_NUMBER") or DEFAULT_FROM)
    plan["amd"] = amd

    if not plan["execute"]:
        # dry-run ou bloqueado: NENHUMA chamada à Telnyx.
        return plan

    connection_id = env.get("TELNYX_CONNECTION_ID")
    if not connection_id:
        raise RuntimeError(
            "TELNYX_CONNECTION_ID não está no ambiente. É o ID da sua Call Control "
            "Application (Voice API App) no portal Telnyx."
        )

    # ── Efeito real (só chega aqui com allowlist OK, dentro do teto e gate aberto) ──
    payload = {
        "connection_id": connection_id,
        "to": plan["to"],
        "from": plan["from"],
        "client_state": _encode_state(message),
    }
    webhook_url = env.get("TELNYX_WEBHOOK_URL")
    if webhook_url:
        payload["webhook_url"] = webhook_url
    if amd and amd != "disabled":
        payload["answering_machine_detection"] = amd  # 'premium'

    resp = requests.post(
        TELNYX_CALLS_API,
        headers={
            "Authorization": "Bearer {}".format(_api_key(env)),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=15,
    )
    if resp.status_code >= 400:
        raise RuntimeError("Telnyx retornou {}: {}".format(resp.status_code, resp.text))

    data = resp.json().get("data", {})
    try:
        record_send(_ledger_path(env), "make_call", plan["to"])
    except OSError:
        pass  # ledger é best-effort
    plan.update({
        "sent": True,
        "call_control_id": data.get("call_control_id"),
        "call_leg_id": data.get("call_leg_id"),
        "status": "discando — o texto será falado quando atender (via webhook)",
    })
    return plan


def _cli():
    p = argparse.ArgumentParser(description="Ligar via Telnyx Call Control (Hermes)")
    p.add_argument("--to", help="Número destino E.164")
    p.add_argument("--self", action="store_true", help="Liga para o próprio número Telnyx")
    p.add_argument("--message", required=True, help="Texto a ser falado (TTS)")
    p.add_argument("--from", dest="from_number", default=None)
    p.add_argument("--amd", default="premium", choices=["premium", "disabled"])
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=None,
                      help="força modo seguro (default); sempre vence o --execute")
    mode.add_argument("--execute", dest="execute", action="store_true",
                      help="tenta a ligação real (exige HERMES_ALLOW_EXECUTE e "
                           "TELNYX_VOICE_SMS_ENABLED e destino na allowlist)")
    args = p.parse_args()

    to = (os.environ.get("TELNYX_NUMBER") or DEFAULT_FROM) if args.self else args.to
    if not to:
        p.error("informe --to ou use --self")

    dry_run = True if args.dry_run else (not args.execute)

    if to not in set(_load_recipient_allowlist(os.environ)):
        print(json.dumps({
            "warning": "destino fora da allowlist — será BLOQUEADO",
            "to": to,
            "allowlist": _load_recipient_allowlist(os.environ),
        }, ensure_ascii=False, indent=2), file=sys.stderr)

    out = make_call(to, args.message, args.from_number, args.amd, dry_run=dry_run)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
