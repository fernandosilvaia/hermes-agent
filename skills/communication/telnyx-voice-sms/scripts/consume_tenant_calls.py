"""
consume_tenant_calls.py — Consumidor DEDICADO (não o worker genérico do
MacBook) de jobs "telnyx-call" na fila do Control Tower: ligações
tenant-scoped, feitas com a credencial Telnyx PRÓPRIA de cada org (nunca a
TELNYX_API_KEY/TELNYX_NUMBER globais do Hermes, que continuam servindo só o
uso interno da Axtro em make_call.py/send_sms.py — este consumidor não altera
esse comportamento em nada).

Por que um consumidor NOVO e não o MacBook Worker (scripts/axtro-local-worker.mjs
no control-tower)? Aquele worker só sabe rodar claude-code/codex/shell (edita
código, cria branch, abre PR) — telnyx-call não é nada disso, é uma chamada de
API pontual que precisa rodar na VPS (onde a skill telnyx-voice-sms já vive) com
uma credencial resolvida em tempo de execução. Forçar isso no worker do MacBook
seria torcer a forma errada; um consumidor pequeno e focado, do mesmo jeito que
o worker do MacBook, é mais simples de auditar.

Fluxo (UMA checagem por execução — mesmo padrão do scripts/axtro-local-worker.mjs:
não é um daemon, roda via cron/systemd timer):
  1. GET /api/hermes/jobs/next?worker=<id>&executors=telnyx-call — puxa o
     próximo job telnyx-call "queued" (ou seja, já aprovado por humano via
     POST /api/hermes/jobs/:id/approve — telnyx-call SEMPRE nasce
     pending_approval, nunca há um caminho pra pular isso). O parâmetro
     `executors` é o que impede este consumidor de roubar da fila
     COMPARTILHADA um job claude-code/codex/shell que não sabe executar (e
     vice-versa, impede o MacBook Worker de roubar um telnyx-call) — ver
     claimNext() em control-tower/src/lib/hermes-jobs.ts.
  2. validate_job_gate() (_tenant_call_policy.py): reconfirma LOCALMENTE que
     o job é telnyx-call, passou pelo gate humano (requires_human_gate=true
     + result.approved_by preenchido) e tem tenant_call.org_id/to válidos —
     nunca confia cegamente no que veio da rede.
  3. POST /api/hermes/jobs/:id/telnyx-credential — resolve a credencial
     Telnyx DECIFRADA da org dona do job. Uso ÚNICO: o próprio endpoint
     marca o job "running" atomicamente ao responder (ver comentário lá) —
     uma segunda tentativa pro mesmo job falha.
  4. build_tenant_env() constrói um `env` NOVO por-chamada (nunca os.environ
     real) com essa credencial + allowlist restrita ao destino DESTE job +
     ledger de teto diário POR ORG + os gates padrão. Chama make_call() de
     telnyx-voice-sms SEM MODIFICAR sua lógica de decisão — _send_policy.py
     roda exatamente como roda pro uso interno da Axtro, só que apontado pra
     um `env` diferente. Isso é o que garante que "job já aprovado no
     Control Tower" NÃO pula o dry-run/allowlist/teto LOCAL desta skill.
  5. POST /api/hermes/jobs/:id/status — reporta o resultado.

GATE PADRÃO (dry-run é o default PERMANENTE, mesma regra do resto do
projeto): mesmo com o job JÁ aprovado por um humano no Control Tower, a
ligação real só acontece se, no AMBIENTE REAL deste processo:
  (a) --dry-run não foi passado (flag de CLI só pra teste manual — o modo
      normal via cron NUNCA passa isso),
  (b) HERMES_ALLOW_EXECUTE == "true" (gate global compartilhado com o resto
      do repo),
  (c) TENANT_TELNYX_CALLS_ENABLED == "true" — flag PRÓPRIA deste fluxo,
      DIFERENTE de TELNYX_VOICE_SMS_ENABLED (uso interno da Axtro). Ligar
      uma não liga a outra.
Faltando qualquer uma, _send_policy.plan_action devolve dry_run=true e
NENHUMA chamada chega na Telnyx — exatamente como o resto da skill.

Env deste consumidor (ambiente REAL do processo — nunca por-tenant):
    HOUSE_API_URL                  (opcional, padrão https://house.axtroai.com)
    HOUSE_INGEST_TOKEN             (obrigatória — mesmo token de máquina do
                                     MacBook Worker / dispatch-job)
    HERMES_ALLOW_EXECUTE           (gate global compartilhado)
    TENANT_TELNYX_CALLS_ENABLED    (gate específico deste consumidor)
    TENANT_TELNYX_LEDGER_DIR       (opcional, padrão /opt/data/tenant_telnyx_ledgers)
    TENANT_TELNYX_DAILY_CALL_CAP   (opcional, padrão "5" — por org)
    WORKER_ID                      (opcional, padrão tenant-telnyx-<hostname>)

Uso (cron/systemd timer, dry-run é o default até os gates acima abrirem):
    python consume_tenant_calls.py
    python consume_tenant_calls.py --dry-run   # força modo seguro, ignora os gates
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from _tenant_call_policy import build_tenant_env, interpret_call_result, validate_job_gate  # noqa: E402
from make_call import make_call as _default_make_call  # noqa: E402

DEFAULT_URL = os.environ.get("HOUSE_API_URL", "https://house.axtroai.com")


def _token() -> str:
    token = os.environ.get("HOUSE_INGEST_TOKEN") or os.environ.get("INGEST_TOKEN")
    if not token:
        raise RuntimeError(
            "HOUSE_INGEST_TOKEN não está no ambiente. Rode via cofre (doppler run / op run) — "
            "mesmo token de máquina do MacBook Worker (control-tower/scripts/axtro-local-worker.mjs) "
            "/ dispatch-job."
        )
    return token


def _worker_id() -> str:
    explicit = os.environ.get("WORKER_ID")
    if explicit:
        return explicit
    try:
        host = os.uname().nodename
    except Exception:  # noqa: BLE001 — hostname nunca deve derrubar o script
        host = "vps"
    return "tenant-telnyx-{0}".format(host)


def _headers() -> dict:
    return {"x-axtro-token": _token(), "Content-Type": "application/json"}


# ── Fronteira de rede (lazy `requests`, substituível em teste — mesmo padrão
# de dispatch_job.py: _do_post/_emit_telemetry) ─────────────────────────────
def _do_get_next(url, headers, timeout):
    import requests  # import preguiçoso — mantém o módulo importável sem rede

    return requests.get(url, headers=headers, timeout=timeout)


def _do_post_credential(url, headers, timeout):
    import requests

    return requests.post(url, headers=headers, timeout=timeout)


def _do_post_status(url, headers, payload, timeout):
    import requests

    return requests.post(url, headers=headers, json=payload, timeout=timeout)


def poll_next_job(timeout=20):
    """GET /api/hermes/jobs/next?executors=telnyx-call. None = fila vazia
    (204, estado normal). Lança RuntimeError em qualquer outro erro HTTP."""
    url = "{0}/api/hermes/jobs/next?worker={1}&executors=telnyx-call".format(
        DEFAULT_URL.rstrip("/"), _worker_id(),
    )
    resp = _do_get_next(url, _headers(), timeout)
    if resp.status_code == 204:
        return None
    if resp.status_code != 200:
        raise RuntimeError(
            "Control Tower retornou {0} ao pedir o próximo job: {1}".format(resp.status_code, resp.text)
        )
    return resp.json().get("job")


def resolve_credential(job_id, timeout=20):
    """POST /api/hermes/jobs/:id/telnyx-credential. Uso único — ver docstring
    do módulo. Devolve (credential_dict, None) ou (None, motivo_do_erro);
    NUNCA lança (o chamador decide reportar "blocked" sem derrubar o processo)."""
    url = "{0}/api/hermes/jobs/{1}/telnyx-credential".format(DEFAULT_URL.rstrip("/"), job_id)
    resp = _do_post_credential(url, _headers(), timeout)
    if resp.status_code != 200:
        return None, "Control Tower recusou resolver a credencial ({0}): {1}".format(
            resp.status_code, resp.text[:500],
        )
    body = resp.json()
    credential = body.get("credential")
    if not credential:
        return None, "resposta de telnyx-credential sem campo 'credential'"
    return credential, None


def report_status(job_id, status, result, timeout=20):
    """POST /api/hermes/jobs/:id/status — best-effort (loga se falhar, nunca
    lança: perder o report não pode derrubar o processo, o job fica visível
    como 'running'/'claimed' pro operador investigar manualmente)."""
    url = "{0}/api/hermes/jobs/{1}/status".format(DEFAULT_URL.rstrip("/"), job_id)
    try:
        resp = _do_post_status(url, _headers(), {"status": status, "result": result}, timeout)
        if resp.status_code != 200:
            sys.stderr.write(
                "[consume_tenant_calls] falha ao reportar status: {0} {1}\n".format(resp.status_code, resp.text)
            )
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write("[consume_tenant_calls] erro ao reportar status: {0}\n".format(exc))


def process_job(job, dry_run=False, timeout=20, make_call_fn=None, real_env=None):
    """Processa UM job já puxado da fila (status "claimed" no Control
    Tower). NUNCA chama a API da Telnyx diretamente — delega a
    make_call_fn (default: make_call.py real), que só age de verdade se
    _send_policy.plan_action liberar (dry-run é o default permanente).

    Devolve sempre um dict {"status", "result"} pronto pra report_status —
    nunca lança (falha de credencial/gate vira "blocked", não uma exceção).
    """
    make_call_fn = make_call_fn or _default_make_call
    real_env = real_env if real_env is not None else os.environ

    problems = validate_job_gate(job)
    if problems:
        return {"status": "blocked", "result": {"error": "; ".join(problems)}}

    credential, err = resolve_credential(job["id"], timeout)
    if err or not credential:
        return {"status": "blocked", "result": {"error": err or "credencial não resolvida"}}

    tenant_env = build_tenant_env(job, credential, real_env)
    tenant_call = job.get("tenant_call") or {}
    to = tenant_call.get("to")
    message = tenant_call.get("message") or "Ligação solicitada."

    try:
        call_result = make_call_fn(
            to=to,
            message=message,
            from_number=credential.get("number"),
            dry_run=dry_run,
            env=tenant_env,
        )
    except Exception as exc:  # noqa: BLE001 — erro da API Telnyx (ou TELNYX_CONNECTION_ID ausente)
        return {"status": "blocked", "result": {"error": "make_call falhou: {0}".format(exc)[:2000]}}

    return interpret_call_result(call_result)


def run_once(dry_run=False, timeout=20, make_call_fn=None, real_env=None):
    """Um ciclo completo: puxa (no máximo) um job, processa, reporta. Devolve
    um resumo (útil em teste/CLI); imprime progresso no stdout, mesmo
    espírito de scripts/axtro-local-worker.mjs no control-tower."""
    job = poll_next_job(timeout)
    if not job:
        print("[consume_tenant_calls] fila vazia (nenhum job telnyx-call). Nada a fazer.")
        return {"polled": False}

    print("[consume_tenant_calls] job recebido: {0} — {1}".format(job.get("id"), job.get("task")))
    outcome = process_job(job, dry_run=dry_run, timeout=timeout, make_call_fn=make_call_fn, real_env=real_env)
    print("[consume_tenant_calls] resultado: {0}".format(outcome["status"]))
    report_status(job["id"], outcome["status"], outcome.get("result"), timeout=timeout)
    return {"polled": True, "job_id": job.get("id"), "outcome": outcome}


def _cli(argv=None):
    p = argparse.ArgumentParser(
        description="Consumidor dedicado de jobs telnyx-call (ligações tenant-scoped) do Control Tower.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "força modo seguro mesmo se HERMES_ALLOW_EXECUTE/TENANT_TELNYX_CALLS_ENABLED "
            "estiverem abertos — só para teste manual; o modo normal (cron) NUNCA passa isso."
        ),
    )
    p.add_argument("--timeout", type=int, default=20)
    args = p.parse_args(argv)

    try:
        summary = run_once(dry_run=args.dry_run, timeout=args.timeout)
    except Exception as exc:  # noqa: BLE001 — mesmo padrão de axtro-local-worker.mjs (main().catch)
        sys.stderr.write("[consume_tenant_calls] erro fatal: {0}\n".format(exc))
        sys.exit(1)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    _cli()
