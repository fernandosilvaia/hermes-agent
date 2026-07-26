"""
ask_vps.py — Delega uma CONSULTA DE LEITURA para o Hermes que roda 24/7 na VPS.

Esta ponte é P0-crítica: o Hermes da VPS detém Google Workspace + Telnyx. Como o
Hermes LOCAL processa conteúdo NÃO-confiável (Telegram/emails), esta skill NUNCA
faz passthrough cru de texto arbitrário como instrução ao agente remoto. Toda
decisão de segurança (allowlist, sanitização, detecção de ação/injeção, envelope
de read-only e gate de dry-run) vive em `_relay_policy.py` (módulo PURO e testável).

GATE PADRÃO (dry-run é o default PERMANENTE). O POST real só acontece se, ao mesmo
tempo: (a) --dry-run NÃO foi passado, (b) HERMES_ALLOW_EXECUTE == "true",
(c) ASK_VPS_HERMES_ENABLED == "true". Falta qualquer uma -> dry-run.

Uso como biblioteca:
    from ask_vps import ask_vps_hermes
    ask_vps_hermes("quantos emails não lidos eu tenho?", task_type="consultar")

Uso como CLI (dry-run por default):
    python ask_vps.py --task-type consultar "quantos emails não lidos eu tenho?"
    python ask_vps.py --task-type consultar --execute "resumo da minha agenda de hoje"

Env:
    HERMES_VPS_API_SERVER_KEY   (obrigatória p/ execução real — injetada pelo cofre)
    HERMES_VPS_URL              (opcional, padrão https://hermes.axtroai.com)
    HERMES_ALLOW_EXECUTE        (gate global — "true" libera execução real)
    ASK_VPS_HERMES_ENABLED      (gate da skill — "true" libera execução real)
    CONTROL_TOWER_URL           (opcional — telemetria best-effort)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Garante que o módulo de política (mesmo diretório) seja importável tanto quando
# rodado como script (`python ask_vps.py`) quanto importado como módulo.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from agent.secret_scope import get_secret  # noqa: E402

from _relay_policy import (  # noqa: E402
    TASK_TYPES_PERMITIDOS,
    plan_relay,
)

DEFAULT_URL = os.environ.get("HERMES_VPS_URL", "https://hermes.axtroai.com")


def _api_key() -> str:
    # Defesa em profundidade: esta skill é internal-only
    # (axtro/tenant_skill_catalog.py) e nunca deveria existir no disco de um
    # perfil-cliente sob multiplex_profiles — mas se um bug de allowlist
    # algum dia deixar passar, get_secret() falha alto (UnscopedSecretError)
    # em vez de silenciosamente usar a chave real da VPS da Axtro.
    key = get_secret("HERMES_VPS_API_SERVER_KEY")
    if not key:
        raise RuntimeError(
            "HERMES_VPS_API_SERVER_KEY não está no ambiente. Rode via cofre "
            "(doppler run / op run) para injetar a credencial."
        )
    return key


def _emit_telemetry(origin: str, task_type: str, decision: str, dry_run: bool) -> None:
    """Telemetria best-effort para o Control Tower. Nunca inclui segredo/credencial.
    Importa `requests` de forma preguiçosa; qualquer falha é silenciosa.
    """
    url = os.environ.get("CONTROL_TOWER_URL")
    if not url:
        return
    try:
        import requests  # import preguiçoso — não é dependência dos testes

        requests.post(
            url.rstrip("/") + "/api/telemetry",
            json={
                "agentId": "ask-vps-hermes",
                "kind": "relay.decision",
                "projectId": "hermes-agent",
                "message": "origin={0} task_type={1} decision={2} dry_run={3}".format(
                    origin, task_type, decision, dry_run
                ),
            },
            timeout=8,
        )
    except Exception:  # noqa: BLE001 — telemetria nunca derruba a skill
        pass


def _do_post(envelope_text: str, timeout: int) -> str:
    """EFEITO REAL: só chamado quando o gate liberou. Importa `requests` lazy."""
    import requests  # import preguiçoso — mantém dry-run/testes sem dependência

    resp = requests.post(
        f"{DEFAULT_URL}/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {_api_key()}",
            "Content-Type": "application/json",
        },
        json={
            "model": "hermes-agent",
            "messages": [{"role": "user", "content": envelope_text}],
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


def ask_vps_hermes(
    message: str,
    task_type=None,
    dry_run: bool = True,
    timeout: int = 120,
    origin: str = "local",
    env=None,
) -> dict:
    """Delega uma consulta de LEITURA para o Hermes da VPS.

    Fluxo: sanitiza -> classify_or_reject -> (BLOQUEADO devolve sem chamar a VPS)
    -> (dry-run devolve o envelope que MANDARIA, sem chamar) -> (só se PERMITIDO e
    gate liberado faz o POST). Sempre retorna um dict; nunca faz passthrough cru.
    """
    if env is None:
        env = os.environ
    plan = plan_relay(task_type, message, dry_run=dry_run, env=env)
    _emit_telemetry(origin, plan["task_type"], plan["decision"], plan["dry_run"])

    if plan["decision"] == "BLOQUEADO":
        return {
            **plan,
            "blocked": True,
            "response": None,
            "note": (
                "BLOQUEADO pela política da ponte — nada foi enviado à VPS. "
                "A ponte só repassa consulta de leitura, nunca instrução de ação."
            ),
        }

    if plan["dry_run"]:
        return {
            **plan,
            "blocked": False,
            "response": None,
            "note": (
                "DRY-RUN — envelope montado mas NÃO enviado. Para executar de verdade: "
                "--execute + HERMES_ALLOW_EXECUTE=true + ASK_VPS_HERMES_ENABLED=true."
            ),
        }

    # Caminho real: só aqui há rede, e só com envelope estruturado (nunca cru).
    response = _do_post(plan["envelope_text"], timeout)
    return {
        **plan,
        "blocked": False,
        "response": response,
        "note": "Consulta de leitura enviada à VPS.",
    }


def _cli(argv=None):
    p = argparse.ArgumentParser(
        description="Delegar uma CONSULTA DE LEITURA para o Hermes da VPS (dry-run por default)"
    )
    p.add_argument("message", help="A pergunta/consulta de leitura a delegar")
    p.add_argument(
        "--task-type",
        required=True,
        choices=sorted(TASK_TYPES_PERMITIDOS),
        help="Tipo da consulta (só leitura é permitida)",
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="tenta execução real (ainda exige HERMES_ALLOW_EXECUTE=true e ASK_VPS_HERMES_ENABLED=true)",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="força dry-run (é o default e SEMPRE vence)",
    )
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--origin", default="cli")
    args = p.parse_args(argv)

    # dry-run é o default; --dry-run explícito sempre vence; só --execute abaixa a flag.
    dry_run = not (args.execute and not args.dry_run)

    result = ask_vps_hermes(
        args.message,
        task_type=args.task_type,
        dry_run=dry_run,
        timeout=args.timeout,
        origin=args.origin,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
