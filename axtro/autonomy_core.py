#!/usr/bin/env python3
"""autonomy_core.py — O CÉREBRO da autonomia governada do Hermes.

Objetivo: dar PODER com TRILHOS. O Hermes age sozinho no que é seguro e pede
aprovação só no que é sensível. Uma decisão pura (sem rede, sem I/O além de ler
o contract.json) diz, para uma skill + ambiente:

    allow_real   → a AÇÃO REAL (não dry-run) pode ocorrer?
    mode         → production | staging | dry_run | blocked | killed | passthrough
    needs_approval → exige aprovação humana explícita?

Dois eixos combinados:

  ANEL DE AUTONOMIA (o QUE a skill faz)
    Ring 0  observação, leitura, diagnóstico, relatórios          → livre
    Ring 1  criar/editar arquivos, prompts, docs, testes          → livre
    Ring 2  executar skills internas seguras                      → gate operacional
    Ring 3  preparar mudança de produção, aprovar antes de aplicar→ aprovação humana
    Ring 4  execução autônoma avançada                            → só se LIBERADA no contrato

  CLASSE DE RISCO (o QUANTO pode causar dano)
    safe                   → executa sozinho
    medium_risk            → executa sozinho se tiver contrato E testes
    high_risk              → preflight + log + dry-run quando possível (máx staging)
    production_sensitive   → aprovação humana ou gate explícito
    financial_sensitive    → NUNCA gasto/compra/cobrança real sem aprovação
    external_communication → NUNCA msg/e-mail/ligação/SMS real sem aprovação

Regras de ouro (fail-CLOSED — na dúvida, NÃO faz ação real):
  - KILL SWITCH global (HERMES_KILL_SWITCH) bloqueia TUDO, antes de qualquer coisa.
  - Skill sensível SEM contrato → bloqueada (não sabemos suas regras).
  - Credencial declarada ausente → bloqueada (fail-closed).
  - Classe de aprovação sem aprovação humana → roda só em DRY-RUN (simula, nada real).
  - Neste build de segurança, financeiro/externo/produção NUNCA passam de 'staging'
    (produção real fica protegida mesmo com aprovação).

Este core NÃO substitui o gate de dupla-env dentro de cada script — é a 1a camada.
Ação real efetiva = autonomy_core autoriza  AND  gate no próprio script.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import contract_guard as cg  # noqa: E402  (reusa load_contract / is_sensitive_skill / REQUIRED_FIELDS)

# ── classes de risco ──────────────────────────────────────────────────────
RISK_SAFE = "safe"
RISK_MEDIUM = "medium_risk"
RISK_HIGH = "high_risk"
RISK_PROD = "production_sensitive"
RISK_FIN = "financial_sensitive"
RISK_EXT = "external_communication"
RISK_CLASSES = (RISK_SAFE, RISK_MEDIUM, RISK_HIGH, RISK_PROD, RISK_FIN, RISK_EXT)
# classes que só fazem ação REAL com aprovação humana explícita:
APPROVAL_CLASSES = (RISK_PROD, RISK_FIN, RISK_EXT)

# ── envs de controle (setadas FORA do daemon, por um humano) ──────────────
KILL_SWITCH_ENV = "HERMES_KILL_SWITCH"     # "on"/"true"/"1" → bloqueia tudo
HUMAN_APPROVAL_ENV = "HERMES_HUMAN_APPROVAL"  # aprovação humana p/ classes sensíveis
RING_GATE_ENV = "HERMES_RING_GATE"         # gate operacional p/ ring >= 2
ALLOW_EXECUTE_ENV = "HERMES_ALLOW_EXECUTE"  # gate de execução do script (2a camada)

# ── ranking de modo (mais restritivo vence via min()) ─────────────────────
_RANK = {"production": 3, "staging": 2, "dry_run": 1, "blocked": 0}
_NAME = {3: "production", 2: "staging", 1: "dry_run", 0: "blocked"}


def _t(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on", "enabled")


@dataclass
class AutonomyDecision:
    allow_real: bool          # ação real (não dry-run) autorizada?
    mode: str                 # production|staging|dry_run|blocked|killed|passthrough
    needs_approval: bool      # a classe exige aprovação humana?
    risk_class: str
    ring: object              # int | None
    reasons: list = field(default_factory=list)
    kill_switched: bool = False
    governed: bool = True
    skill_id: str = "?"

    @property
    def real_action(self) -> bool:
        return self.allow_real and self.mode in ("production", "staging")

    def as_dict(self) -> dict:
        return {"allow_real": self.allow_real, "mode": self.mode,
                "needs_approval": self.needs_approval, "risk_class": self.risk_class,
                "ring": self.ring, "reasons": self.reasons,
                "kill_switched": self.kill_switched, "governed": self.governed,
                "skill_id": self.skill_id}


def kill_switch_active(env=None) -> bool:
    env = os.environ if env is None else env
    return _t(env.get(KILL_SWITCH_ENV))


def has_tests(skill_dir) -> bool:
    d = Path(skill_dir) / "tests"
    return d.is_dir() and any(d.glob("test_*.py"))


def classify(contract, skill_dir) -> str:
    """Classe de risco: do contrato se declarada; senão heurística fail-closed."""
    if contract and contract.get("risk_class") in RISK_CLASSES:
        return contract["risk_class"]
    category = Path(skill_dir).parent.name.lower()
    if "communication" in category:
        return RISK_EXT
    if "finance" in category:
        return RISK_FIN
    # sem classe declarada: trata como high_risk (roda, mas com trilhos), nunca 'safe'.
    return RISK_HIGH


def _blocked(reason, risk="?", ring=None, sid="?", killed=False, mode="blocked"):
    return AutonomyDecision(allow_real=False, mode=("killed" if killed else mode),
                            needs_approval=False, risk_class=risk, ring=ring,
                            reasons=[reason], kill_switched=killed, skill_id=sid)


def decide(skill_dir, env=None, *, native=False, contract=None) -> AutonomyDecision:
    """Decisão de autonomia governada. Pura. Fail-closed."""
    env = os.environ if env is None else env
    sid = Path(skill_dir).name

    # ── 0. KILL SWITCH — hard stop, antes de tudo ─────────────────────────
    if kill_switch_active(env):
        return _blocked("KILL SWITCH ativo ({}) — toda execução bloqueada".format(KILL_SWITCH_ENV),
                        sid=sid, killed=True)

    # ── 1. nativa da Nous (não governada) → pass-through ──────────────────
    if native:
        return AutonomyDecision(allow_real=True, mode="passthrough", needs_approval=False,
                                risk_class="native", ring=None, governed=False, skill_id=sid,
                                reasons=["skill nativa da Nous — não governada pela Axtro (pass-through)"])

    # ── 2. carrega contrato ───────────────────────────────────────────────
    if contract is None:
        contract, errs = cg.load_contract(skill_dir)
    else:
        errs = []

    if contract is None:
        if errs and "invalido" in errs[0]:
            return _blocked("contract.json ilegível/inválido (fail-closed): " + errs[0], sid=sid)
        # ausente: sensível → bloqueia; não-sensível → legacy limitado a dry-run
        if cg.is_sensitive_skill(skill_dir, None):
            return _blocked("skill sensível SEM contract.json — bloqueada (legacy sensível)",
                            risk=RISK_HIGH, sid=sid)
        return AutonomyDecision(allow_real=False, mode="dry_run", needs_approval=False,
                                risk_class=RISK_MEDIUM, ring=None, skill_id=sid,
                                reasons=["skill legacy sem contract.json — limitada a dry-run"])

    # ── 3. contrato inválido (campos obrigatórios) ────────────────────────
    missing = [f for f in cg.REQUIRED_FIELDS if f not in contract]
    if missing:
        return _blocked("contract inválido — campos ausentes: " + ", ".join(missing), sid=sid)

    risk = classify(contract, skill_dir)
    ring = contract.get("autonomy_ring")
    reasons = []

    # ── 4. gates fail-closed que BLOQUEIAM de vez ─────────────────────────
    if not contract.get("stop_conditions"):
        return _blocked("stop_conditions vazio — ação real bloqueada", risk=risk, ring=ring, sid=sid)
    missing_creds = [c for c in contract.get("credentials", []) if not env.get(c)]
    if missing_creds:
        return _blocked("credenciais declaradas ausentes (fail-closed): " + ", ".join(missing_creds),
                        risk=risk, ring=ring, sid=sid)
    if contract.get("enabled") is not True:
        return _blocked("enabled=false — skill desligada (ligue o contrato p/ usar)",
                        risk=risk, ring=ring, sid=sid)

    # ── 5. teto de modo por production_ready + telemetry (R4/R6) ──────────
    prod_ok = contract.get("production_ready") is True
    telem_ok = bool(contract.get("telemetry_events"))
    rank = _RANK["production"] if (prod_ok and telem_ok) else _RANK["staging"]
    if not prod_ok:
        reasons.append("production_ready=false → no máximo 'staging'")
    elif not telem_ok:
        reasons.append("telemetry_events vazio → 'production' bloqueado")

    gate_ok = _t(env.get(RING_GATE_ENV)) or _t(env.get(HUMAN_APPROVAL_ENV))
    approval_ok = _t(env.get(HUMAN_APPROVAL_ENV))
    needs_approval = risk in APPROVAL_CLASSES

    # ── 6. gate de anel de autonomia ──────────────────────────────────────
    if isinstance(ring, int) and ring >= 4:
        liberated = _t(contract.get("ring4_autonomous")) or _t(contract.get("autonomous_execution_approved"))
        if not liberated:
            rank = min(rank, _RANK["dry_run"])
            needs_approval = True
            reasons.append("Ring 4 não liberado explicitamente no contrato → dry-run")
        else:
            reasons.append("Ring 4 liberado por contrato (execução autônoma avançada)")
    elif isinstance(ring, int) and ring >= 2:
        if not gate_ok:
            if risk in APPROVAL_CLASSES:
                rank = min(rank, _RANK["dry_run"])
                reasons.append("Ring {} sem gate → dry-run (classe exige aprovação)".format(ring))
            else:
                return _blocked("Ring {} exige gate explícito ({} ou {})".format(
                    ring, RING_GATE_ENV, HUMAN_APPROVAL_ENV), risk=risk, ring=ring, sid=sid)

    # ── 7. política por classe de risco ───────────────────────────────────
    if risk == RISK_SAFE:
        pass  # executa sozinho
    elif risk == RISK_MEDIUM:
        if not has_tests(skill_dir):
            rank = min(rank, _RANK["dry_run"])
            reasons.append("medium_risk sem testes → dry-run (precisa de contrato E testes)")
    elif risk == RISK_HIGH:
        rank = min(rank, _RANK["staging"])
        reasons.append("high_risk → máx 'staging' (preflight + log + dry-run quando possível)")
    elif risk in APPROVAL_CLASSES:
        if approval_ok:
            rank = min(rank, _RANK["staging"])  # nunca 'production' neste build
            reasons.append("{}: aprovação humana presente → 'staging' (produção real protegida)".format(risk))
        else:
            rank = min(rank, _RANK["dry_run"])
            reasons.append("{}: exige aprovação humana ({}) → dry-run (nada real)".format(risk, HUMAN_APPROVAL_ENV))

    mode = _NAME[rank]
    allow_real = rank >= _RANK["staging"]
    if allow_real and not reasons:
        reasons.append("ação real permitida (modo {})".format(mode))
    return AutonomyDecision(allow_real=allow_real, mode=mode, needs_approval=needs_approval,
                            risk_class=risk, ring=ring, reasons=reasons, skill_id=sid)
