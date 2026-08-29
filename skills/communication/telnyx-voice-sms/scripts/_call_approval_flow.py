"""
_call_approval_flow.py - orquestracao PURA (stdlib only) do fluxo de
aprovacao one-tap de ligacoes.

Concentra, sem rede e sem efeito colateral proprio:
  - o texto da mensagem de aprovacao enviada ao dono no Telegram;
  - o teclado inline (Aprovar / Rejeitar) e o formato do callback_data;
  - a espera pela decisao (poll no store, com expiracao no prazo);
  - a UNICA porta de execucao: execute_approved_call(), que so repassa ao
    make_call real depois de um claim atomico de uso unico sobre um pedido
    APROVADO. Pedido pendente/rejeitado/expirado NUNCA chega na discagem.

A discagem em si continua 100% no make_call.py existente, com TODOS os
trilhos preservados: dry-run default, HERMES_ALLOW_EXECUTE,
TELNYX_VOICE_SMS_ENABLED, teto diario e prefixo obrigatorio de
identificacao de IA. A aprovacao do Telegram substitui apenas o gate
humano por destino: o overlay de env adiciona o numero APROVADO (e so ele)
a allowlist desta unica chamada, espelhando _tenant_call_policy.build_tenant_env().
"""
from __future__ import annotations

import os
import time as _time
from datetime import datetime, timezone

import _call_approval_store as store

CALLBACK_PREFIX = "callreq"
VERB_APPROVE = "a"
VERB_REJECT = "r"

APPROVE_LABEL = "Aprovar e ligar"
REJECT_LABEL = "Rejeitar"


def build_callback_data(verb: str, request_id: str) -> str:
    return "{0}:{1}:{2}".format(CALLBACK_PREFIX, verb, request_id)


def parse_callback_data(data: str):
    """"callreq:a:cr1234" -> ("a", "cr1234"); qualquer outra coisa -> None."""
    parts = (data or "").split(":", 2)
    if len(parts) != 3 or parts[0] != CALLBACK_PREFIX:
        return None
    verb, request_id = parts[1], parts[2]
    if verb not in (VERB_APPROVE, VERB_REJECT):
        return None
    request_id = request_id.strip()
    if not request_id or len(request_id) > 32 or not all(
        ch.isalnum() or ch in "_-" for ch in request_id
    ):
        return None
    return verb, request_id


def build_inline_keyboard(request_id: str) -> dict:
    """reply_markup pronto para o sendMessage da Bot API do Telegram."""
    return {
        "inline_keyboard": [[
            {"text": APPROVE_LABEL,
             "callback_data": build_callback_data(VERB_APPROVE, request_id)},
            {"text": REJECT_LABEL,
             "callback_data": build_callback_data(VERB_REJECT, request_id)},
        ]]
    }


def _timeout_human(seconds) -> str:
    try:
        seconds = int(seconds)
    except (TypeError, ValueError):
        return "?"
    if seconds % 3600 == 0:
        hours = seconds // 3600
        return "{0} hora{1}".format(hours, "s" if hours != 1 else "")
    if seconds % 60 == 0:
        minutes = seconds // 60
        return "{0} minuto{1}".format(minutes, "s" if minutes != 1 else "")
    return "{0} segundos".format(seconds)


def build_approval_message(request: dict) -> str:
    """Texto simples (sem markdown) da mensagem de aprovacao no Telegram."""
    lines = [
        "Pedido de ligacao (aprovacao necessaria)",
        "",
        "Contato: {0}".format(request.get("contact") or "?"),
        "Numero: {0}".format(request.get("to") or "?"),
        "Motivo: {0}".format(request.get("purpose") or "?"),
        "",
        "Um toque em '{0}' e eu ligo agora.".format(APPROVE_LABEL),
        "'{0}' (ou silencio) cancela: sem aprovacao nao ha ligacao.".format(REJECT_LABEL),
        "Expira em {0} ({1} UTC).".format(
            _timeout_human(request.get("timeout_seconds")),
            request.get("expires_at") or "?",
        ),
        "Pedido: {0}".format(request.get("id") or "?"),
    ]
    return "\n".join(lines)


def build_allowlist_overlay(to: str, base_env=None) -> dict:
    """Env overlay de UMA chamada: allowlist ampliada so com o numero aprovado.

    Mesmo espirito de _tenant_call_policy.build_tenant_env(): a aprovacao
    humana explicita deste pedido faz o papel do ato humano de ampliar
    TELNYX_ALLOWED_RECIPIENTS, mas com escopo minimo (um numero, uma
    chamada) e sem tocar o ambiente real do processo. Todos os outros
    trilhos (gates de env, teto diario, ledger) vem do ambiente base.
    """
    env = dict(base_env if base_env is not None else os.environ)
    existing = (env.get("TELNYX_ALLOWED_RECIPIENTS", "") or "").strip()
    numbers = [n.strip() for n in existing.split(",") if n.strip()]
    if to not in numbers:
        numbers.append(to)
    env["TELNYX_ALLOWED_RECIPIENTS"] = ",".join(numbers)
    return env


def execute_approved_call(request_id: str, make_call_fn, env=None, now=None) -> dict:
    """UNICO caminho do fluxo de aprovacao ate a discagem real.

    1. O pedido precisa existir e estar APPROVED (pendente, rejeitado ou
       expirado sao recusados e auditados, sem nunca chamar make_call_fn).
    2. claim_execution() e atomico e de uso unico: double-tap, callback
       repetido ou retry nunca discam duas vezes.
    3. make_call_fn (o make_call real em producao) roda com o overlay de
       allowlist do numero aprovado e dry_run=False; TODOS os gates
       internos dele continuam valendo (env gates, teto diario, E.164).
    4. Resultado (discou ou bloqueou) vai para o store e o audit log,
       amarrado ao id da aprovacao que o autorizou.
    """
    request_id = str(request_id or "").strip()
    request = store.get_request(request_id, env=env)
    if request is None:
        store.append_audit("execute_refused", request_id, env=env, now=now,
                           reason="not_found")
        return {"request_id": request_id, "executed": False, "sent": False,
                "reason": "not_found"}
    if request.get("status") != store.STATUS_APPROVED:
        store.append_audit("execute_refused", request_id, env=env, now=now,
                           reason="status_{0}".format(request.get("status")))
        return {"request_id": request_id, "executed": False, "sent": False,
                "reason": "not_approved", "status": request.get("status")}

    claim = store.claim_execution(request_id, env=env, now=now)
    if not claim["ok"]:
        store.append_audit("execute_refused", request_id, env=env, now=now,
                           reason=claim["reason"])
        return {"request_id": request_id, "executed": False, "sent": False,
                "reason": claim["reason"], "status": claim.get("status")}

    overlay = build_allowlist_overlay(request["to"], base_env=env)
    kwargs = {"to": request["to"], "message": request["message"],
              "dry_run": False, "env": overlay}
    # So passa approved_request_id se a assinatura aceitar (nunca usar
    # try/except TypeError aqui: um TypeError interno DEPOIS da discagem
    # causaria uma segunda chamada).
    try:
        import inspect
        params = inspect.signature(make_call_fn).parameters
        accepts_id = "approved_request_id" in params or any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
    except (TypeError, ValueError):
        accepts_id = False
    if accepts_id:
        kwargs["approved_request_id"] = request_id
    try:
        result = make_call_fn(**kwargs)
    except Exception as exc:  # noqa: BLE001 - falha da API vira resultado, nunca re-disca
        store.record_execution_result(
            request_id, sent=False,
            reason="make_call falhou: {0}".format(exc)[:500],
            env=env, now=now,
        )
        return {"request_id": request_id, "executed": True, "sent": False,
                "reason": "make_call falhou: {0}".format(exc)[:500]}

    sent = bool(result.get("sent"))
    store.record_execution_result(
        request_id,
        sent=sent,
        call_control_id=result.get("call_control_id"),
        reason=None if sent else (result.get("reason") or
                                  ("dry_run" if result.get("dry_run") else "blocked")),
        env=env, now=now,
    )
    out = {"request_id": request_id, "executed": True, "sent": sent}
    out.update({k: v for k, v in result.items() if k not in out})
    return out


def wait_for_decision(request_id: str, env=None, poll_seconds=2.0,
                      sleep_fn=_time.sleep, now_fn=None) -> dict:
    """Espera bloqueante ate o pedido sair de pending (decisao ou prazo).

    No prazo (expires_at), marca o pedido como expired de forma atomica e
    retorna. Nunca disca; quem decide o que fazer com o resultado e o
    chamador (request_call_approval.py).
    """
    now_fn = now_fn or (lambda: datetime.now(timezone.utc))
    while True:
        request = store.get_request(request_id, env=env)
        if request is None:
            return {"status": None, "reason": "not_found", "request": None}
        if request.get("status") != store.STATUS_PENDING:
            return {"status": request["status"], "reason": "decided",
                    "request": request}
        expires_at = store._parse_iso(request.get("expires_at"))
        if expires_at is not None and now_fn() > expires_at:
            store.expire_if_pending(request_id, env=env, now=now_fn())
            request = store.get_request(request_id, env=env)
            return {"status": request.get("status") if request else None,
                    "reason": "expired", "request": request}
        sleep_fn(poll_seconds)
