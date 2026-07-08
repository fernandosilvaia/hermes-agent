"""contract_guard.py — Camada de enforcement que faz o contract.json virar
CONTROLE REAL, não só documentação.

Antes deste módulo, a segurança das skills Axtro vivia (a) na prosa do SKILL.md
e (b) no gate de dupla-env dentro de cada script. O contract.json era metadado
inerte: o loader do daemon Nous nem o lê. Este guard é a peça que faltava — uma
função pura que, dado o contract de uma skill e o ambiente, decide se uma AÇÃO
REAL (não dry-run) pode ocorrer, aplicando as regras de governança da Axtro.

100% stdlib. Sem rede, sem I/O além de ler o contract.json do disco (opcional —
`evaluate` recebe o dict pronto e é totalmente puro/testável).

REGRAS (todas fail-CLOSED — na dúvida, bloqueia a ação real):
  R1  contract ausente + skill sensível        → BLOQUEIA ação real (legacy sensível)
  R1b contract ausente + skill NÃO sensível     → LEGACY_LIMITED (só dry-run)
  R1c contract ausente + skill NATIVA (Nous)    → PASS-THROUGH (não é nosso; não bloqueia)
  R2  contract inválido (campos faltando)       → BLOQUEIA ação real
  R3  enabled != true                           → BLOQUEIA ação real (dry-run ok)
  R4  production_ready != true                  → no máximo 'staging' (bloqueia modo 'production')
  R5  stop_conditions vazio                     → BLOQUEIA ação real
  R6  telemetry_events vazio                    → bloqueia 'production'
  R7  credentials com env var ausente           → BLOQUEIA ação real (fail-closed)
  R8  autonomy_ring >= 2 sem gate explícito     → BLOQUEIA ação real
  R9  autonomy_ring == 3 (exige humano)         → só com gate humano explícito
  (R10) o gate de dupla-env do runtime (HERMES_ALLOW_EXECUTE + <SKILL>_ENABLED)
        continua valendo POR CIMA disto — este guard é uma camada ADICIONAL, não
        substitui o gate no script. Ação real = gate_env AND guard.allow_real.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

# Campos obrigatórios num contract Axtro (subset do axtro/CONTRACT_SCHEMA.json
# que importa para a decisão de execução).
REQUIRED_FIELDS = (
    "id", "enabled", "production_ready", "activation_stage",
    "autonomy_ring", "stop_conditions", "telemetry_events", "credentials",
)

# Sinais de que uma skill SEM contract é "sensível" (tem poder de efeito real) —
# usado só para skills legacy sem contract, para decidir R1 vs R1b.
SENSITIVE_TOOL_HINTS = (
    "terminal", "network", "http", "gmail", "email", "drive", "sms", "call",
    "telnyx", "stripe", "payment", "purchase", "vps", "deploy",
)
SENSITIVE_CATEGORY_HINTS = ("communication", "finance")
# Import/uso no código que indica capacidade de efeito real externo.
SENSITIVE_CODE_MARKERS = (
    "import requests", "urllib.request", "http.client", "socket",
    "googleapiclient", "subprocess", "os.system", "stripe",
)

ALLOW_EXECUTE_ENV = "HERMES_ALLOW_EXECUTE"
# Env genérica que um humano seta fora do daemon para satisfazer o gate de
# anel >= 2 (a skill pode ter a sua própria env específica também).
RING_GATE_ENV = "HERMES_RING_GATE"


def _is_true(v) -> bool:
    return str(v or "").strip().lower() == "true"


def load_contract(skill_dir) -> tuple:
    """Lê o contract.json de uma skill. Retorna (contract_dict | None, erros:list)."""
    path = Path(skill_dir) / "contract.json"
    if not path.is_file():
        return None, ["contract.json ausente"]
    try:
        return json.loads(path.read_text(encoding="utf-8")), []
    except (json.JSONDecodeError, OSError) as e:
        return None, ["contract.json ilegível/invalido: {}".format(str(e)[:120])]


def is_sensitive_skill(skill_dir, contract: dict | None = None) -> bool:
    """Heurística: a skill tem poder de efeito real? (para skills sem contract)."""
    skill_dir = Path(skill_dir)
    category = skill_dir.parent.name.lower()
    if any(h in category for h in SENSITIVE_CATEGORY_HINTS):
        return True
    if contract:
        tools = " ".join(str(t).lower() for t in contract.get("tools", []))
        if any(h in tools for h in SENSITIVE_TOOL_HINTS):
            return True
        if isinstance(contract.get("autonomy_ring"), int) and contract["autonomy_ring"] >= 2:
            return True
    # varre os scripts por marcadores de capacidade de rede/subprocess
    scripts = skill_dir / "scripts"
    if scripts.is_dir():
        for py in scripts.glob("*.py"):
            try:
                src = py.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if any(m in src for m in SENSITIVE_CODE_MARKERS):
                return True
    return False


def evaluate(contract: dict | None, env: dict | None = None, *,
             sensitive: bool = True, native: bool = False,
             skill_id: str = "?") -> dict:
    """Decisão PURA de governança. Não lê disco, não toca rede.

    Args:
      contract: o dict do contract.json, ou None se ausente.
      env: ambiente (default os.environ).
      sensitive: a skill tem poder de efeito real? (relevante quando contract=None)
      native: é skill nativa da Nous? (contract=None + native → pass-through)
      skill_id: rótulo para mensagens.

    Retorna dict:
      allow_real: bool  — a AÇÃO REAL pode ocorrer?
      max_mode: 'production' | 'staging' | 'dry_run' | 'blocked' | 'passthrough'
      reasons: list[str] — por que (rastreável)
    """
    env = os.environ if env is None else env
    reasons = []

    # ── R1: sem contract ──────────────────────────────────────────────────
    if contract is None:
        if native:
            return {"allow_real": True, "max_mode": "passthrough",
                    "reasons": ["skill nativa da Nous sem contract — pass-through (nao governada pela Axtro)"]}
        if sensitive:
            return {"allow_real": False, "max_mode": "blocked",
                    "reasons": ["R1: skill sensivel SEM contract.json — acao real bloqueada (legacy sensivel)"]}
        return {"allow_real": False, "max_mode": "dry_run",
                "reasons": ["R1b: skill legacy sem contract — limitada a dry-run"]}

    # ── R2: contract inválido (campos obrigatórios) ───────────────────────
    missing = [f for f in REQUIRED_FIELDS if f not in contract]
    if missing:
        reasons.append("R2: campos obrigatorios ausentes no contract: {}".format(", ".join(missing)))
        return {"allow_real": False, "max_mode": "blocked", "reasons": reasons}

    # ── R5: stop_conditions vazio ─────────────────────────────────────────
    if not contract.get("stop_conditions"):
        reasons.append("R5: stop_conditions vazio — acao real bloqueada")
        return {"allow_real": False, "max_mode": "blocked", "reasons": reasons}

    # ── R7: credenciais declaradas que estão ausentes no ambiente ─────────
    missing_creds = [c for c in contract.get("credentials", []) if not env.get(c)]
    if missing_creds:
        reasons.append("R7: credenciais declaradas ausentes no ambiente (fail-closed): {}".format(
            ", ".join(missing_creds)))
        return {"allow_real": False, "max_mode": "blocked", "reasons": reasons}

    # ── R3: enabled ───────────────────────────────────────────────────────
    if contract.get("enabled") is not True:
        reasons.append("R3: enabled != true — acao real bloqueada (dry-run permitido)")
        return {"allow_real": False, "max_mode": "dry_run", "reasons": reasons}

    # ── R8/R9: gate de anel de autonomia ──────────────────────────────────
    ring = contract.get("autonomy_ring")
    if isinstance(ring, int) and ring >= 2:
        # anel >= 2 exige gate explícito (env humana). Anel 4 nao e contratavel.
        if ring >= 4:
            reasons.append("R-proibido: autonomy_ring >= 4 nao e permitido")
            return {"allow_real": False, "max_mode": "blocked", "reasons": reasons}
        if not (_is_true(env.get(RING_GATE_ENV)) or _is_true(env.get(ALLOW_EXECUTE_ENV))):
            reasons.append("R8: autonomy_ring {} exige gate explicito ({} ou {}=true)".format(
                ring, RING_GATE_ENV, ALLOW_EXECUTE_ENV))
            return {"allow_real": False, "max_mode": "dry_run", "reasons": reasons}

    # ── R4/R6: production_ready + telemetry para modo 'production' ─────────
    prod_ok = contract.get("production_ready") is True
    telem_ok = bool(contract.get("telemetry_events"))
    if prod_ok and telem_ok:
        max_mode = "production"
    else:
        max_mode = "staging"
        if not prod_ok:
            reasons.append("R4: production_ready != true — no maximo 'staging' (nunca 'production')")
        if not telem_ok:
            reasons.append("R6: telemetry_events vazio — 'production' bloqueado")

    # Chegou aqui: enabled=true, contract valido, creds presentes, stop nao-vazio,
    # gate de anel satisfeito. Ação real liberada (no modo max_mode).
    reasons.append("acao real permitida (modo {})".format(max_mode))
    return {"allow_real": True, "max_mode": max_mode, "reasons": reasons}


def authorize(skill_dir, env: dict | None = None, *, native: bool = False) -> dict:
    """Conveniência: carrega o contract de skill_dir e chama evaluate, inferindo
    a sensibilidade quando não há contract."""
    contract, errs = load_contract(skill_dir)
    sid = (contract or {}).get("id", Path(skill_dir).name)
    if contract is None and errs and "invalido" in errs[0]:
        # contract ilegível é pior que ausente: fail-closed sempre.
        return {"allow_real": False, "max_mode": "blocked", "reasons": ["R2: " + errs[0]]}
    sensitive = is_sensitive_skill(skill_dir, contract)
    out = evaluate(contract, env, sensitive=sensitive, native=native, skill_id=sid)
    out["skill_id"] = sid
    out["contract_errors"] = errs
    return out


def contract_allows_real(skill_dir, env: dict | None = None) -> bool:
    """Atalho booleano para as skills combinarem com o gate de dupla-env:
    real_action = gate_env AND contract_allows_real(SKILL_DIR)."""
    return authorize(skill_dir, env).get("allow_real", False)
