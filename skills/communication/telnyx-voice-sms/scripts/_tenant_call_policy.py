"""
_tenant_call_policy.py — Lógica PURA (stdlib only) do consumidor telnyx-call
tenant-scoped (consume_tenant_calls.py).

Mesmo padrão de _dispatch_policy.py (skills/operations/dispatch-job) e
_send_policy.py (esta skill): concentra toda DECISÃO em funções sem rede,
testáveis sem `requests`. O consumidor (consume_tenant_calls.py) só
orquestra chamadas de rede em torno do que este módulo decide.

Responsabilidades:
  - validar que um job puxado da fila é mesmo um telnyx-call JÁ APROVADO por
    humano antes de gastar uma chamada de rede pra resolver a credencial —
    defesa em profundidade. O Control Tower já garante isso server-side
    (createJob() força requires_human_gate=true pra telnyx-call, e o
    endpoint de credencial só libera com o job "claimed", ou seja, já
    aprovado), mas este consumidor NUNCA confia cegamente num campo vindo da
    rede sem checar de novo aqui — mesmo espírito de "vence o mais
    restritivo" do resto do projeto;
  - montar o `env` POR-CHAMADA que _send_policy.py (reusado SEM NENHUMA
    modificação) vai usar pra decidir se a ligação é permitida — nunca
    os.environ real, sempre um dict novo escopado a ESTE job/ESTA
    org/ESTE destino. É essa construção que garante que este consumidor
    passa pelas MESMAS travas de dry-run/gate/allowlist/teto diário que o
    uso interno da Axtro em make_call.py, sem bypass;
  - interpretar o resultado de make_call() (sent/blocked/dry_run) no
    vocabulário de status do Control Tower
    (POST /api/hermes/jobs/:id/status).
"""
from __future__ import annotations

import os
import re

# Mesma regra E.164 de _send_policy.py (duplicada de propósito — defesa em
# profundidade; este módulo nunca assume que o job já veio validado).
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def is_valid_e164(number) -> bool:
    return bool(number) and bool(_E164_RE.match(str(number).strip()))


def validate_job_gate(job) -> list:
    """Devolve a lista de problemas (vazia = job seguro pra prosseguir com a
    resolução de credencial). Fail-closed: qualquer campo ausente/errado
    vira problema, nunca crasha.

    NÃO confia cegamente no que o Control Tower mandou: reconfirma aqui que
    o job é telnyx-call, que passou pelo gate humano (requires_human_gate
    True + result.approved_by preenchido — só approveJob() no Control Tower
    preenche isso) e que tenant_call tem o formato mínimo esperado.
    """
    if not isinstance(job, dict):
        return ["job não é um objeto válido"]

    problems = []
    if job.get("executor") != "telnyx-call":
        problems.append("executor não é telnyx-call")
    if job.get("requires_human_gate") is not True:
        problems.append("requires_human_gate não é true — job não passou pelo gate humano")
    approved_by = ((job.get("result") or {}).get("approved_by") or "").strip()
    if not approved_by:
        problems.append("result.approved_by ausente — nada prova aprovação humana real")

    tenant_call = job.get("tenant_call") or {}
    org_id = (tenant_call.get("org_id") or "").strip()
    to = (tenant_call.get("to") or "").strip()
    if not org_id:
        problems.append("tenant_call.org_id ausente")
    if not is_valid_e164(to):
        problems.append("tenant_call.to ausente ou não é E.164 válido")

    return problems


def org_ledger_path(env, org_id) -> str:
    """Ledger de teto diário POR ORG — nunca o TELNYX_SEND_LEDGER_PATH global
    da Axtro (senão uma org com muitas chamadas estouraria o teto do uso
    interno, ou vice-versa)."""
    env = env if env is not None else os.environ
    base_dir = env.get("TENANT_TELNYX_LEDGER_DIR", "/opt/data/tenant_telnyx_ledgers")
    safe_org = re.sub(r"[^A-Za-z0-9_-]", "_", str(org_id))[:120] or "unknown_org"
    return os.path.join(base_dir, "{0}.jsonl".format(safe_org))


def build_tenant_env(job, credential, real_env=None) -> dict:
    """Monta o `env` por-chamada que make_call()/_send_policy.py (REUSADOS
    sem modificação) vão usar pra decidir se esta ligação específica é
    permitida.

    NUNCA é os.environ real — sempre um dict novo, escopado a ESTE job. A
    credencial (apiKey/number/connectionId) é a da conta Telnyx PRÓPRIA da
    org (resolvida via POST /api/hermes/jobs/:id/telnyx-credential), nunca a
    global da Axtro. O "allowlist" deste dict (TELNYX_ALLOWED_RECIPIENTS) é
    só o destino DESTE job — nunca uma lista ampla reaproveitada entre
    ligações/orgs; cada chamada a build_tenant_env recomeça do zero.
    """
    real_env = real_env if real_env is not None else os.environ
    org_id = job["tenant_call"]["org_id"]
    to = job["tenant_call"]["to"]
    return {
        "TELNYX_API_KEY": credential["apiKey"],
        "TELNYX_CONNECTION_ID": credential["connectionId"],
        "TELNYX_NUMBER": credential["number"],
        "TELNYX_ALLOWED_RECIPIENTS": to,
        # _send_policy.py só conhece a env TELNYX_VOICE_SMS_ENABLED por nome
        # (gate_allows_execution é hardcoded nesse nome) — aqui ela reflete
        # TENANT_TELNYX_CALLS_ENABLED do ambiente REAL deste consumidor: uma
        # flag PRÓPRIA deste fluxo. Ligar o uso interno da Axtro
        # (TELNYX_VOICE_SMS_ENABLED real, em make_call.py/send_sms.py) NUNCA
        # libera chamadas tenant-scoped, e vice-versa — são interruptores
        # independentes, mesmo reusando o mesmo código de decisão.
        "TELNYX_VOICE_SMS_ENABLED": real_env.get("TENANT_TELNYX_CALLS_ENABLED", ""),
        # Gate global compartilhado — mesmo nome/papel de dispatch-job e do
        # uso interno desta skill (HERMES_ALLOW_EXECUTE precisa estar "true"
        # pra QUALQUER efeito real no repo, não só telnyx).
        "HERMES_ALLOW_EXECUTE": real_env.get("HERMES_ALLOW_EXECUTE", ""),
        "TELNYX_SEND_LEDGER_PATH": org_ledger_path(real_env, org_id),
        "TELNYX_DAILY_SEND_CAP": real_env.get("TENANT_TELNYX_DAILY_CALL_CAP", "5"),
    }


def interpret_call_result(result: dict) -> dict:
    """Traduz o dict devolvido por make_call() pro vocabulário de status do
    Control Tower (POST /api/hermes/jobs/:id/status).

    JobStatus (control-tower/src/lib/hermes-jobs.ts) não tem um valor
    "dry_run" dedicado — dry-run e bloqueio por política usam "blocked" (só
    "done" quando a Telnyx confirmou o disparo de verdade, result["sent"]).
    """
    if result.get("sent"):
        return {
            "status": "done",
            "result": {
                "message": "Ligação disparada via Telnyx (conta própria do tenant) para {0}. call_control_id={1}".format(
                    result.get("to"), result.get("call_control_id"),
                ),
            },
        }
    if result.get("dry_run"):
        return {
            "status": "blocked",
            "result": {
                "message": (
                    "dry-run: HERMES_ALLOW_EXECUTE e/ou TENANT_TELNYX_CALLS_ENABLED não estão "
                    "abertos neste consumidor — nenhuma ligação real foi feita."
                ),
            },
        }
    return {
        "status": "blocked",
        "result": {"error": result.get("reason", "bloqueado pela política de envio (ver _send_policy.py)")},
    }
