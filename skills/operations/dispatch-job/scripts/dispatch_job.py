"""
dispatch_job.py — Monta e (quando o gate liberar) envia um HermesJob para a
fila do Control Tower (POST /api/hermes/jobs, mesmo padrão de auth do
MacBook Worker: HOUSE_API_URL + HOUSE_INGEST_TOKEN via x-axtro-token).

Esta é uma CAPACIDADE CALLABLE, não um gatilho automático: quem decide QUANDO
chamar esta skill é quem invoca (humano, ou o agente durante uma conversa
onde o Fernando pediu algo específico) — o módulo não varre nada sozinho nem
se agenda em cron. Toda a decisão de SEGURANÇA (allowlist de repo/branch/
executor, classificação de risco, gate humano efetivo, gate triplo de
execução) vive em `_dispatch_policy.py` (módulo PURO e testável).

GATE PADRÃO (dry-run é o default PERMANENTE). O POST real só acontece se, ao
mesmo tempo: (a) --dry-run NÃO foi passado, (b) HERMES_ALLOW_EXECUTE == "true",
(c) DISPATCH_JOB_ENABLED == "true". Falta qualquer uma -> dry-run.

Uso como biblioteca:
    from dispatch_job import dispatch_job
    result = dispatch_job(
        project_id="control-tower",
        repo_path="/Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower",
        branch="hermes/fix-null-check-leads-route",
        executor="claude-code",
        skill_id="pr_builder_interno",
        task="POST /api/leads quebra com 500 quando decisionMaker.email vem "
             "undefined mesmo depois da validação — adicionar teste de "
             "regressão e corrigir o null-check em src/app/api/leads/route.ts",
        allowed_commands=["npm run test", "npm run typecheck", "npm run lint"],
        expected_outputs=["teste de regressão", "fix aplicado"],
        requires_human_gate=False,   # bug pequeno e bem definido, sem risco alto
    )

Uso como CLI (dry-run por default):
    python dispatch_job.py \
        --project-id control-tower \
        --repo-path /Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower \
        --branch hermes/fix-null-check-leads-route \
        --executor claude-code \
        --skill-id pr_builder_interno \
        --task "corrigir null-check em POST /api/leads" \
        --allowed-commands "npm run test" "npm run typecheck" \
        --expected-outputs "teste de regressão" "fix aplicado"

    # pra executar de verdade (POST real):
    HERMES_ALLOW_EXECUTE=true DISPATCH_JOB_ENABLED=true python dispatch_job.py --execute ...

Env:
    HOUSE_API_URL               (opcional, padrão https://house.axtroai.com)
    HOUSE_INGEST_TOKEN          (obrigatória p/ execução real — mesmo token do worker)
    HERMES_ALLOW_EXECUTE        (gate global — "true" libera execução real)
    DISPATCH_JOB_ENABLED        (gate da skill — "true" libera execução real)
    AXTRO_REPO_ALLOWLIST        (opcional — mesma allowlist do MacBook Worker)
    CONTROL_TOWER_URL           (opcional — telemetria best-effort; pode ser igual a HOUSE_API_URL)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Garante que o módulo de política (mesmo diretório) seja importável tanto
# quando rodado como script (`python dispatch_job.py`) quanto importado.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _dispatch_policy import plan_dispatch  # noqa: E402

DEFAULT_URL = os.environ.get("HOUSE_API_URL", "https://house.axtroai.com")


def _token() -> str:
    token = os.environ.get("HOUSE_INGEST_TOKEN") or os.environ.get("INGEST_TOKEN")
    if not token:
        raise RuntimeError(
            "HOUSE_INGEST_TOKEN não está no ambiente. Rode via cofre "
            "(doppler run / op run) para injetar a credencial — mesmo padrão do "
            "MacBook Worker (scripts/axtro-local-worker.mjs no control-tower)."
        )
    return token


def _emit_telemetry(decision: str, skill_id: str, dry_run: bool, requires_human_gate) -> None:
    """Telemetria best-effort para o Control Tower. Nunca inclui o token.
    Importa `requests` de forma preguiçosa; qualquer falha é silenciosa."""
    url = os.environ.get("CONTROL_TOWER_URL") or os.environ.get("HOUSE_API_URL")
    if not url:
        return
    try:
        import requests  # import preguiçoso — não é dependência dos testes

        requests.post(
            url.rstrip("/") + "/api/telemetry",
            json={
                "agentId": "dispatch-job",
                "kind": "info",
                "projectId": "hermes-agent",
                "skill": skill_id,
                "message": "decision={0} dry_run={1} requires_human_gate={2}".format(
                    decision, dry_run, requires_human_gate
                ),
            },
            timeout=8,
        )
    except Exception:  # noqa: BLE001 — telemetria nunca derruba a skill
        pass


def _do_post(payload: dict, timeout: int) -> dict:
    """EFEITO REAL: só chamado quando o gate liberou. Importa `requests` lazy.
    POST /api/hermes/jobs — mesmo endpoint/contrato do control-tower
    (src/app/api/hermes/jobs/route.ts), autenticado com x-axtro-token."""
    import requests  # import preguiçoso — mantém dry-run/testes sem dependência

    resp = requests.post(
        f"{DEFAULT_URL}/api/hermes/jobs",
        headers={
            "x-axtro-token": _token(),
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=timeout,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Control Tower retornou {resp.status_code}: {resp.text}")
    return resp.json()


def dispatch_job(
    *,
    project_id,
    repo_path,
    branch,
    executor,
    skill_id,
    task,
    allowed_commands,
    expected_outputs,
    forbidden_commands=None,
    max_runtime_minutes=45,
    max_cost_usd=5,
    requires_human_gate=None,
    agent_id=None,
    dry_run: bool = True,
    timeout: int = 30,
    env=None,
) -> dict:
    """Monta o payload de um HermesJob e (só se o gate liberar) faz o POST.

    Fluxo: valida -> BLOQUEADO devolve sem tocar rede -> dry-run devolve o
    payload que SERIA enviado, sem tocar rede -> só com tudo liberado faz o
    POST de verdade. Sempre retorna um dict; nunca lança em caminho de
    validação (só _do_post/_token podem lançar, e só no caminho real)."""
    if env is None:
        env = os.environ
    plan = plan_dispatch(
        project_id=project_id,
        repo_path=repo_path,
        branch=branch,
        executor=executor,
        skill_id=skill_id,
        task=task,
        allowed_commands=allowed_commands,
        expected_outputs=expected_outputs,
        forbidden_commands=forbidden_commands,
        max_runtime_minutes=max_runtime_minutes,
        max_cost_usd=max_cost_usd,
        requires_human_gate=requires_human_gate,
        agent_id=agent_id,
        dry_run=dry_run,
        env=env,
    )
    _emit_telemetry(
        plan["decision"], skill_id, plan["dry_run"],
        plan["payload"]["requires_human_gate"] if plan["payload"] else None,
    )

    if plan["decision"] == "BLOQUEADO":
        return {
            **plan,
            "blocked": True,
            "job": None,
            "note": "BLOQUEADO pela política do dispatch — nada foi enviado ao Control Tower.",
        }

    if plan["dry_run"]:
        return {
            **plan,
            "blocked": False,
            "job": None,
            "note": (
                "DRY-RUN — payload montado mas NÃO enviado. Para executar de verdade: "
                "--execute + HERMES_ALLOW_EXECUTE=true + DISPATCH_JOB_ENABLED=true. "
                "requires_human_gate efetivo: {0} ({1}).".format(
                    plan["risk"]["effective_gate"], plan["risk"]["reason"]
                )
            ),
        }

    # Caminho real: só aqui há rede.
    response = _do_post(plan["payload"], timeout)
    job = response.get("job") if isinstance(response, dict) else None
    return {
        **plan,
        "blocked": False,
        "job": job,
        "note": (
            "Job criado no Control Tower (status={0}). ".format(job.get("status") if job else "?")
            + (
                "requires_human_gate=true — o worker NÃO executa até um humano aprovar "
                "via POST /api/hermes/jobs/:id/approve."
                if plan["payload"]["requires_human_gate"]
                else "requires_human_gate=false — o worker pode puxar e executar na próxima checagem."
            )
        ),
    }


def _parse_bool_none(value):
    if value is None:
        return None
    return value.strip().lower() in ("1", "true", "yes", "sim")


def _cli(argv=None):
    p = argparse.ArgumentParser(
        description="Montar (e, se liberado, enviar) um HermesJob para o Control Tower (dry-run por default)"
    )
    p.add_argument("--project-id", required=True)
    p.add_argument("--repo-path", required=True)
    p.add_argument("--branch", required=True, help="deve começar com hermes/")
    p.add_argument("--executor", required=True, choices=["claude-code", "shell"])
    p.add_argument("--skill-id", required=True)
    p.add_argument("--task", required=True, help="descrição clara da tarefa, em linguagem natural")
    p.add_argument("--allowed-commands", nargs="+", required=True)
    p.add_argument("--expected-outputs", nargs="+", required=True)
    p.add_argument("--forbidden-commands", nargs="*", default=None)
    p.add_argument("--max-runtime-minutes", type=int, default=45)
    p.add_argument("--max-cost-usd", type=float, default=5)
    p.add_argument(
        "--requires-human-gate",
        default=None,
        choices=["true", "false"],
        help="opcional; se omitido, o default seguro é true. Termo de risco alto na "
             "task FORÇA true mesmo se você passar false.",
    )
    p.add_argument("--agent-id", default=None)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute", action="store_true",
        help="tenta execução real (ainda exige HERMES_ALLOW_EXECUTE=true e DISPATCH_JOB_ENABLED=true)",
    )
    mode.add_argument(
        "--dry-run", action="store_true",
        help="força dry-run (é o default e SEMPRE vence)",
    )
    p.add_argument("--timeout", type=int, default=30)
    args = p.parse_args(argv)

    # dry-run é o default; --dry-run explícito sempre vence; só --execute abaixa a flag.
    dry_run = not (args.execute and not args.dry_run)

    result = dispatch_job(
        project_id=args.project_id,
        repo_path=args.repo_path,
        branch=args.branch,
        executor=args.executor,
        skill_id=args.skill_id,
        task=args.task,
        allowed_commands=args.allowed_commands,
        expected_outputs=args.expected_outputs,
        forbidden_commands=args.forbidden_commands,
        max_runtime_minutes=args.max_runtime_minutes,
        max_cost_usd=args.max_cost_usd,
        requires_human_gate=_parse_bool_none(args.requires_human_gate),
        agent_id=args.agent_id,
        dry_run=dry_run,
        timeout=args.timeout,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("blocked"):
        sys.exit(2)


if __name__ == "__main__":
    _cli()
