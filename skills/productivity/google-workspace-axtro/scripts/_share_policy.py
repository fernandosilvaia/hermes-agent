"""_share_policy.py — Lógica PURA de decisão de compartilhamento do Drive.

P0 (canal de exfiltração): num daemon 24/7 que lê emails/Telegram não-confiáveis,
um prompt-injection pode mandar compartilhar um arquivo corporativo com um email
externo (até role=writer). O escopo do Drive é TOTAL (auth.py). Este módulo é a
guarda-corpo que decide, ANTES de qualquer chamada de API, se o compartilhamento
pode acontecer.

Importa SÓ stdlib (os, re) — NUNCA googleapiclient/google/requests. Por isso roda
no python3 do sistema (3.9.6) e é 100% testável sem rede nem credenciais.

Duas decisões puras vivem aqui:
  1. evaluate_share(email, role, approve_external) → destinatário externo é bloqueado
     por padrão; role=writer para externo é bloqueado sem aprovação explícita.
  2. resolve_execution(dry_run_flag, env) → o GATE PADRÃO de dry-run: a ação real só
     ocorre com --execute (não --dry-run) + HERMES_ALLOW_EXECUTE=true +
     GOOGLE_WORKSPACE_AXTRO_ENABLED=true. Dry-run é o default PERMANENTE.
"""
from __future__ import annotations

import os
import re

# Domínio próprio da empresa — o único destino "interno" por padrão.
DEFAULT_ALLOWED_DOMAINS = ("axtroai.com",)

# Env que carrega a allowlist de domínios (csv). Ex.: "axtroai.com,parceiro.com".
SHARE_ALLOWLIST_ENV = "GOOGLE_WORKSPACE_SHARE_ALLOWED_DOMAINS"

# Env (csv) com os domínios EXTERNOS que um humano pré-aprovou como destino de
# compartilhamento. `approve_external` é uma flag que o PRÓPRIO agente pode setar
# (logo, um prompt-injection também pode) — sozinha ela NÃO é um gate humano. Para
# o destino externo valer, o domínio precisa estar aqui, e esta env só é setada
# fora de banda pelo operador. Vazia por padrão → nenhum domínio externo é destino
# válido, nem com approve_external. Fecha o vetor de exfiltração para domínio arbitrário.
EXTERNAL_ALLOWLIST_ENV = "GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS"

# Envs do GATE PADRÃO de execução.
ALLOW_EXECUTE_ENV = "HERMES_ALLOW_EXECUTE"
SKILL_ENABLED_ENV = "GOOGLE_WORKSPACE_AXTRO_ENABLED"

# Shape mínimo de email: exatamente um @, sem espaços, partes não-vazias.
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+$")

_VALID_ROLES = ("reader", "commenter", "writer")


def _is_true(value: str | None) -> bool:
    """Só a string exata 'true' (case-insensitive, sem espaços) conta como verdadeiro."""
    return (value or "").strip().lower() == "true"


def _load_share_allowlist(env: dict | None = None) -> list:
    """Lê a env de domínios permitidos (csv). Vazia/ausente → só o domínio da empresa.

    Retorna lista de domínios minúsculos, sem duplicatas, sem entradas vazias.
    """
    env = os.environ if env is None else env
    raw = env.get(SHARE_ALLOWLIST_ENV, "") or ""
    domains = []
    for part in raw.split(","):
        d = part.strip().lower()
        if d and d not in domains:
            domains.append(d)
    if not domains:
        domains = list(DEFAULT_ALLOWED_DOMAINS)
    return domains


def _load_external_allowlist(env: dict | None = None) -> list:
    """Lê a env de domínios externos pré-aprovados (csv). Ausente/vazia → lista VAZIA.

    Diferente da allowlist interna, aqui NÃO há fallback: sem configuração humana
    explícita, nenhum domínio externo é destino válido.
    """
    env = os.environ if env is None else env
    raw = env.get(EXTERNAL_ALLOWLIST_ENV, "") or ""
    domains = []
    for part in raw.split(","):
        d = part.strip().lower()
        if d and d not in domains:
            domains.append(d)
    return domains


def _email_domain(email: str) -> str:
    """Retorna o domínio (minúsculo) de um email, ou '' se malformado."""
    if not email or not _EMAIL_RE.match(email.strip()):
        return ""
    domain = email.strip().rsplit("@", 1)[1].lower()
    # Domínio real tem ao menos um ponto (rejeita 'foo@bar').
    if "." not in domain:
        return ""
    return domain


def evaluate_share(email: str, role: str = "reader",
                   approve_external: bool = False,
                   env: dict | None = None) -> dict:
    """Decide se um compartilhamento pode ser feito. Função PURA (sem I/O de rede).

    Regras:
      - email sem '@' ou domínio vazio/inválido        → BLOQUEADO ("email invalido")
      - destinatário externo e approve_external=False   → BLOQUEADO ("externo exige aprovacao")
      - externo + role=writer e approve_external=False  → BLOQUEADO ("writer externo sem aprovacao")
      - externo + approve_external mas domínio NÃO está
        na allowlist de parceiros (env, fora de banda)  → BLOQUEADO (anti-exfiltração)
      - sem reasons                                     → PERMITIDO

    Retorna dict: decision, is_external, domain, role, reasons(list).
    """
    allowlist = _load_share_allowlist(env)
    external_allow = _load_external_allowlist(env)
    domain = _email_domain(email)
    is_external = domain not in allowlist  # domínio vazio → externo por definição

    if not domain:
        return {
            "decision": "BLOQUEADO",
            "is_external": True,
            "domain": "",
            "role": role,
            "reasons": ["email invalido"],
        }

    reasons = []
    if role not in _VALID_ROLES:
        reasons.append("role invalido (use reader|commenter|writer)")
    if is_external and not approve_external:
        reasons.append("destinatario externo exige aprovacao explicita")
    if is_external and role == "writer" and not approve_external:
        reasons.append("role=writer para externo bloqueado sem aprovacao")
    # approve_external é setável pelo próprio agente (logo, por prompt-injection).
    # Sozinha ela NÃO libera domínio arbitrário: o destino externo precisa estar
    # numa allowlist de parceiros que só um humano configura fora de banda (env).
    if is_external and approve_external and domain not in external_allow:
        reasons.append(
            "dominio externo nao esta na allowlist de parceiros "
            "(GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS); aprovacao do agente e insuficiente"
        )

    return {
        "decision": "BLOQUEADO" if reasons else "PERMITIDO",
        "is_external": is_external,
        "domain": domain,
        "role": role,
        "reasons": reasons,
    }


def evaluate_recipients(emails, approve_external: bool = False,
                        env: dict | None = None) -> dict:
    """Avalia uma LISTA de destinatários (to/cc/bcc de email, attendees de evento).

    Mesma política de destino externo de evaluate_share, aplicada a cada endereço.
    Fecha os "canais irmãos" do P0: gmail.send e calendar invite também podem
    exfiltrar dado corporativo para fora, não só drive.share.

    `emails` aceita string csv ("a@x.com,b@y.com") ou lista. Retorna dict PURO:
    decision (PERMITIDO|BLOQUEADO), external (lista), invalid (lista), reasons.
    """
    allowlist = _load_share_allowlist(env)
    external_allow = _load_external_allowlist(env)

    addrs = []
    if isinstance(emails, str):
        addrs = [e.strip() for e in emails.split(",") if e.strip()]
    elif isinstance(emails, (list, tuple)):
        for e in emails:
            if isinstance(e, str) and e.strip():
                addrs.append(e.strip())

    invalid, external = [], []
    for a in addrs:
        d = _email_domain(a)
        if not d:
            invalid.append(a)
        elif d not in allowlist:
            external.append(a)

    reasons = []
    if not addrs:
        reasons.append("nenhum destinatario valido")
    if invalid:
        reasons.append("destinatario(s) invalido(s): " + ", ".join(invalid))
    if external:
        if not approve_external:
            reasons.append("destinatario(s) externo(s) exige aprovacao explicita: " + ", ".join(external))
        else:
            # approve_external é setável pelo agente (prompt-injection) — sozinha
            # não libera domínio arbitrário; precisa da allowlist de parceiros (env fora de banda).
            not_allowed = [a for a in external if _email_domain(a) not in external_allow]
            if not_allowed:
                reasons.append(
                    "dominio externo fora da allowlist de parceiros "
                    "(GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS): " + ", ".join(not_allowed)
                )

    return {
        "decision": "BLOQUEADO" if reasons else "PERMITIDO",
        "external": external,
        "invalid": invalid,
        "reasons": reasons,
    }


def resolve_execution(dry_run_flag: bool, env: dict | None = None) -> dict:
    """GATE PADRÃO: dry-run é o default PERMANENTE. Função PURA (env injetável).

    A ação real só ocorre se TODAS forem verdadeiras ao mesmo tempo:
      (a) dry_run_flag == False  (nem --dry-run nem o default sem --execute),
      (b) HERMES_ALLOW_EXECUTE == "true",
      (c) GOOGLE_WORKSPACE_AXTRO_ENABLED == "true".
    Falta qualquer uma → dry-run. O flag --dry-run explícito SEMPRE vence
    (o humano sempre pode forçar o modo seguro).
    """
    env = os.environ if env is None else env
    allow_execute = _is_true(env.get(ALLOW_EXECUTE_ENV))
    skill_enabled = _is_true(env.get(SKILL_ENABLED_ENV))
    execute = (not dry_run_flag) and allow_execute and skill_enabled

    blockers = []
    if dry_run_flag:
        blockers.append("modo dry-run (padrao sem --execute, ou --dry-run explicito)")
    if not allow_execute:
        blockers.append("{} != 'true'".format(ALLOW_EXECUTE_ENV))
    if not skill_enabled:
        blockers.append("{} != 'true'".format(SKILL_ENABLED_ENV))

    return {"execute": execute, "dry_run": not execute, "blockers": blockers}
