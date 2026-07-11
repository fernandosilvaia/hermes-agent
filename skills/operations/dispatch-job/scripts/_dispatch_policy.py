"""
_dispatch_policy.py — Lógica de decisão PURA da skill dispatch-job.

Este módulo contém TODA a decisão de segurança do dispatch:
  - allowlist de repo_path (mesma env AXTRO_REPO_ALLOWLIST do MacBook Worker,
    scripts/axtro-local-worker.mjs no control-tower),
  - validação de branch (sempre hermes/*) e executor (claude-code|shell —
    "codex" ainda não é executável nesta máquina, ver docs do worker),
  - classificação de risco por keyword (banco/auth/pagamento/deploy) que
    FORÇA requires_human_gate=true, mesmo que o chamador peça false,
  - montagem do payload (CreateJobInput do Control Tower,
    ver src/lib/hermes-jobs.ts) — nunca envia nada sozinho, só monta,
  - avaliação do GATE PADRÃO triplo de dry-run.

Regra de ouro: este módulo NÃO importa nada externo (só stdlib `re`/`os`), pra
poder ser testado sem rede e sem `requests`. A função que faz o POST real
vive em dispatch_job.py e importa `requests` de forma preguiçosa — mesmo
padrão de skills/productivity/ask-vps-hermes/scripts/_relay_policy.py.

Este módulo NUNCA decide QUANDO disparar um job — só decide SE um pedido de
dispatch é seguro, dado que alguém (humano ou agente, fora deste módulo) já
decidiu chamar a skill. Não há gatilho automático aqui.
"""
from __future__ import annotations

import os
import re

# ---------------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------------

# Nome da env-var específica desta skill no gate padrão.
SKILL_ENABLED_ENV = "DISPATCH_JOB_ENABLED"

# Mesma allowlist do MacBook Worker (scripts/axtro-local-worker.mjs no
# control-tower) — os dois únicos repos que o Worker executa jobs de verdade.
# Configurável via a MESMA env var (AXTRO_REPO_ALLOWLIST, lista separada por
# vírgula) pra nunca dessincronizar do que o worker realmente aceita.
DEFAULT_REPO_ALLOWLIST = (
    "/Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower",
    "/Users/fernandosilva/Developer/AxtroAI/02_PRODUTOS/lab/hermes-agent",
)

# Executores que o worker desta máquina de fato executa hoje ("codex" está no
# schema mas o CLI não está instalado — ver IMPLEMENTATION_STATUS.md do
# control-tower). Esta skill recusa pedir um executor que o worker só ia
# bloquear/reportar como blocked mesmo assim.
ALLOWED_EXECUTORS = {"claude-code", "shell"}

# Mesma lista DEFAULT_FORBIDDEN de src/lib/hermes-jobs.ts (createJob no
# Control Tower já une isto de qualquer forma no servidor) — duplicada aqui
# de propósito, defesa em profundidade: o payload já nasce seguro antes de
# qualquer rede, mesmo que o servidor mudasse essa regra no futuro.
DEFAULT_FORBIDDEN = (
    "git push origin main",
    "rm -rf /",
    "drop table",
    "truncate",
    "git reset --hard",
    "git clean -fd",
    "git push --force",
)

# Teto client-side (defesa em profundidade — o Control Tower/worker também
# aplicam os deles). Pedidos maiores são BLOQUEADOS, não silenciosamente
# reduzidos: força quem chama a ser deliberado, nunca surpreende.
MAX_RUNTIME_MINUTES_CEILING = 90
MAX_COST_USD_CEILING = 10.0

# Termos de risco alto: dinheiro, auth/segredo, banco, deploy/produção,
# ações destrutivas. Se a task menciona qualquer um destes, o gate humano é
# FORÇADO — a skill não aceita requires_human_gate=false nesse caso, mesmo
# que o chamador peça (regra de ouro do projeto, "vence o mais restritivo").
_HIGH_RISK_MARKERS = [
    # banco de dados / migration
    r"\bmigration\b", r"migra[çc][ãa]o", r"\bbanco de dados\b", r"\bdatabase\b",
    r"\bdrop\s+table\b", r"\btruncate\b", r"\balter\s+table\b",
    # autenticação / segredo / credencial
    r"\bauth\b", r"autentica[çc][ãa]o", r"\bsenha\b", r"\bpassword\b",
    r"\bsecret\b", r"\bsegredo\b", r"\bcredencial", r"\bcredential",
    r"\btoken\s+(de\s+)?(admin|root|api|acesso)", r"\bapi[_\s-]?key\b",
    r"\.env\b",
    # pagamento / financeiro
    r"\bpagamento\b", r"\bpayment\b", r"\bstripe\b", r"\bcobran[çc]a\b",
    r"\bcharge\b", r"\bbilling\b", r"\bfatura\b", r"\binvoice\b",
    # deploy / produção / infra
    r"\bdeploy\b", r"\bprodu[çc][ãa]o\b", r"\bproduction\b", r"\bdns\b",
    r"\brailway\b", r"\bvercel\b", r"\bwebhook\s+secret\b",
    # ação destrutiva
    r"\bdelet[ae]r?\b", r"\bapagar\b", r"\bdestruct", r"force\s*push",
]
_HIGH_RISK_RE = re.compile("|".join(_HIGH_RISK_MARKERS), re.IGNORECASE)


# ---------------------------------------------------------------------------
# Funções puras
# ---------------------------------------------------------------------------

def repo_allowlist_from_env(env=None):
    """Lê AXTRO_REPO_ALLOWLIST (mesma env do worker) ou usa o default local."""
    if env is None:
        env = os.environ
    raw = env.get("AXTRO_REPO_ALLOWLIST", "")
    if not raw.strip():
        return list(DEFAULT_REPO_ALLOWLIST)
    return [p.strip() for p in raw.split(",") if p.strip()]


def find_high_risk_keywords(text):
    """Devolve a lista de termos de risco alto encontrados em `text` (vazia = nenhum)."""
    if not text:
        return []
    return sorted({m.group(0).lower() for m in _HIGH_RISK_RE.finditer(text)})


def classify_risk(task, requires_human_gate=None):
    """Decide o requires_human_gate EFETIVO pra este pedido.

    Regras (nessa ordem, a primeira que bater decide):
      1. task contém termo de risco alto -> True, FORÇADO (chamador não pode baixar).
      2. chamador não declarou nada (None) -> True, default seguro.
      3. chamador declarou explicitamente -> respeita a escolha (True ou False).
    """
    matched = find_high_risk_keywords(task)
    if matched:
        return {
            "effective_gate": True,
            "forced": True,
            "matched_keywords": matched,
            "reason": (
                "task contém termo(s) de risco alto ({0}) — requires_human_gate "
                "forçado para true, independente do que foi pedido"
            ).format(", ".join(matched)),
        }
    if requires_human_gate is None:
        return {
            "effective_gate": True,
            "forced": False,
            "matched_keywords": [],
            "reason": "requires_human_gate não foi declarado explicitamente — default seguro é true",
        }
    return {
        "effective_gate": bool(requires_human_gate),
        "forced": False,
        "matched_keywords": [],
        "reason": "requires_human_gate declarado explicitamente pelo chamador",
    }


def validate_request(
    *,
    project_id,
    repo_path,
    branch,
    executor,
    skill_id,
    task,
    allowed_commands,
    expected_outputs,
    max_runtime_minutes=90,
    max_cost_usd=10,
    repo_allowlist=None,
):
    """Devolve a lista de problemas (vazia = pedido válido). Fail-closed: campo
    ausente/tipo errado sempre vira problema, nunca crasha."""
    problems = []
    allowlist = repo_allowlist if repo_allowlist is not None else repo_allowlist_from_env()

    if not project_id or not isinstance(project_id, str):
        problems.append("project_id ausente ou inválido")
    if not skill_id or not isinstance(skill_id, str):
        problems.append("skill_id ausente ou inválido")
    if not task or not isinstance(task, str) or not task.strip():
        problems.append("task ausente/vazia — descreva a tarefa em linguagem clara")
    if not isinstance(allowed_commands, (list, tuple)) or not allowed_commands:
        problems.append("allowed_commands ausente ou vazio — lista fechada é obrigatória")
    if not isinstance(expected_outputs, (list, tuple)) or not expected_outputs:
        problems.append("expected_outputs ausente ou vazio")

    if not repo_path or repo_path not in allowlist:
        problems.append(
            "repo_path '{0}' fora da allowlist {1}".format(repo_path, allowlist)
        )
    if not branch or not str(branch).startswith("hermes/"):
        problems.append(
            "branch '{0}' não começa com hermes/ (regra de ouro do Local Worker)".format(branch)
        )
    if executor not in ALLOWED_EXECUTORS:
        problems.append(
            "executor '{0}' fora de {1} (codex ainda não é executável nesta máquina)".format(
                executor, sorted(ALLOWED_EXECUTORS)
            )
        )

    try:
        if float(max_runtime_minutes) <= 0 or float(max_runtime_minutes) > MAX_RUNTIME_MINUTES_CEILING:
            problems.append(
                "max_runtime_minutes deve estar entre 1 e {0}".format(MAX_RUNTIME_MINUTES_CEILING)
            )
    except (TypeError, ValueError):
        problems.append("max_runtime_minutes inválido")

    try:
        if float(max_cost_usd) < 0 or float(max_cost_usd) > MAX_COST_USD_CEILING:
            problems.append(
                "max_cost_usd deve estar entre 0 e {0}".format(MAX_COST_USD_CEILING)
            )
    except (TypeError, ValueError):
        problems.append("max_cost_usd inválido")

    return problems


def build_payload(
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
):
    """Monta o payload (CreateJobInput) já com o gate humano EFETIVO calculado
    por classify_risk. Não valida (chame validate_request antes) nem envia
    nada — só monta o dict que iria no corpo do POST /api/hermes/jobs."""
    risk = classify_risk(task, requires_human_gate)
    forbidden = sorted(set((forbidden_commands or ())) | set(DEFAULT_FORBIDDEN))

    payload = {
        "project_id": project_id,
        "repo_path": repo_path,
        "branch": branch,
        "executor": executor,
        "skill_id": skill_id,
        "task": task,
        "allowed_commands": list(allowed_commands),
        "forbidden_commands": forbidden,
        "expected_outputs": list(expected_outputs),
        "max_runtime_minutes": max_runtime_minutes,
        "max_cost_usd": max_cost_usd,
        "requires_human_gate": risk["effective_gate"],
    }
    if agent_id:
        payload["agent_id"] = agent_id
    return payload, risk


def gate_allows_execute(dry_run_flag, env=None):
    """GATE PADRÃO. POST real só se as TRÊS condições forem verdadeiras:
      (a) --dry-run NÃO passado (dry_run_flag is False),
      (b) HERMES_ALLOW_EXECUTE == "true",
      (c) DISPATCH_JOB_ENABLED == "true".
    Falta qualquer uma -> dry-run. --dry-run explícito SEMPRE vence."""
    if env is None:
        env = os.environ
    if dry_run_flag:
        return False
    allow = env.get("HERMES_ALLOW_EXECUTE", "").strip().lower() == "true"
    enabled = env.get(SKILL_ENABLED_ENV, "").strip().lower() == "true"
    return allow and enabled


def plan_dispatch(
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
    dry_run=True,
    env=None,
    repo_allowlist=None,
):
    """Orquestra a decisão SEM tocar em rede. Espelha plan_relay() de
    ask-vps-hermes: dispatch_job.py usa isto pra decidir se faz o POST."""
    problems = validate_request(
        project_id=project_id,
        repo_path=repo_path,
        branch=branch,
        executor=executor,
        skill_id=skill_id,
        task=task,
        allowed_commands=allowed_commands,
        expected_outputs=expected_outputs,
        max_runtime_minutes=max_runtime_minutes,
        max_cost_usd=max_cost_usd,
        repo_allowlist=repo_allowlist,
    )
    permitido = not problems

    plan = {
        "skill": "dispatch_job",
        "decision": "BLOQUEADO" if problems else "PERMITIDO",
        "reasons": problems,
        "dry_run": True,
        "would_execute": False,
        "payload": None,
        "risk": None,
    }
    if not permitido:
        return plan

    payload, risk = build_payload(
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
    )
    will_execute = gate_allows_execute(dry_run, env)
    plan["payload"] = payload
    plan["risk"] = risk
    plan["dry_run"] = not will_execute
    plan["would_execute"] = will_execute
    return plan
