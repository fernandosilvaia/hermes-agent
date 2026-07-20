"""
request_call_approval.py - pede aprovacao one-tap no Telegram para uma
ligacao e, aprovada, dispara a ligacao pelo caminho existente (make_call.py).

FLUXO ("no maximo um pedido no telegram"):
  1. O agente decide que precisa ligar para alguem (nome + numero + motivo).
  2. Este script cria um pedido pendente no store persistente
     ($HERMES_HOME/telnyx_voice_sms/call_approvals.json) e manda UMA mensagem
     ao dono no canal home do Telegram com botoes inline Aprovar/Rejeitar.
  3. Um toque em Aprovar (tratado pelo gateway, que roda
     decide_call_request.py) grava a decisao no store; este processo, que
     fica esperando, ve a aprovacao e disca IMEDIATAMENTE via make_call().
     Rejeitar ou silencio ate o prazo (default 15 min,
     TELNYX_CALL_APPROVAL_TIMEOUT_SECONDS) cancela: nada e discado.

TRILHOS QUE CONTINUAM VALENDO (nada disso e pulado pela aprovacao):
  - make_call() so disca com HERMES_ALLOW_EXECUTE=true E
    TELNYX_VOICE_SMS_ENABLED=true, dentro do teto diario
    (TELNYX_DAILY_SEND_CAP) e com destino E.164 valido;
  - a aprovacao do pedido substitui APENAS o gate humano por destino: o
    numero aprovado entra na allowlist SO desta chamada (overlay de env,
    nunca o os.environ real), espelhando o fluxo tenant-scoped;
  - a ligacao comeca SEMPRE se identificando como assistente de IA
    (prefixo obrigatorio em make_call.py, nao ha como desligar);
  - claim de uso unico: cada aprovacao autoriza NO MAXIMO uma discagem.

ENV (alem das do make_call.py):
  TELEGRAM_BOT_TOKEN                        token do bot (mesmo do gateway)
  TELEGRAM_HOME_CHANNEL                     chat id do dono (canal home)
  TELEGRAM_HOME_CHANNEL_THREAD_ID           opcional, topico do canal home
  TELNYX_CALL_APPROVAL_CHAT_ID              opcional, override do chat id
  TELNYX_CALL_APPROVAL_TIMEOUT_SECONDS      prazo (default 900 = 15 min)
  TELNYX_CALL_APPROVAL_STORE_PATH           override do store JSON
  TELNYX_CALL_APPROVAL_AUDIT_PATH           override do audit JSONL

USO:
  # pedir aprovacao e esperar (dispara a ligacao se aprovado):
  python request_call_approval.py --to +14075551234 --contact "Luiza (Techmax)" \
      --purpose "Confirmar a visita tecnica de amanha as 9h"

  # so criar e enviar o pedido, sem esperar (volta o id):
  python request_call_approval.py --to ... --contact ... --purpose ... --no-wait

  # conferir/executar um pedido ja aprovado:
  python request_call_approval.py --status cr1a2b3c4d
  python request_call_approval.py --execute cr1a2b3c4d

  # auditoria ("que ligacoes voce pediu essa semana?"):
  python request_call_approval.py --list --days 7

  # --dry-run mostra o que faria sem gravar nem enviar nada.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _call_approval_flow as flow  # noqa: E402
import _call_approval_store as store  # noqa: E402
from _send_policy import is_valid_e164  # noqa: E402

TELEGRAM_API_BASE = "https://api.telegram.org"


def _bot_token(env=None) -> str:
    env = env if env is not None else os.environ
    token = (env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if token:
        return token
    # Fallback: config.yaml do gateway (mesma fonte que o gateway usa).
    try:
        import yaml  # type: ignore
        cfg_path = store._get_hermes_home(env) / "config.yaml"
        if cfg_path.is_file():
            with open(cfg_path, encoding="utf-8") as fh:
                cfg = yaml.safe_load(fh) or {}
            platforms = cfg.get("platforms") or {}
            telegram = platforms.get("telegram") or {}
            token = str(telegram.get("token") or "").strip()
            if token:
                return token
    except Exception:
        pass
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN nao esta no ambiente (e nao achei platforms.telegram.token "
        "no config.yaml). O pedido de aprovacao precisa do mesmo bot do gateway."
    )


def _owner_chat_id(env=None, cli_value=None) -> str:
    env = env if env is not None else os.environ
    for value in (cli_value,
                  env.get("TELNYX_CALL_APPROVAL_CHAT_ID"),
                  env.get("TELEGRAM_HOME_CHANNEL")):
        value = (value or "").strip()
        if value:
            return value
    raise RuntimeError(
        "nao sei para qual chat mandar o pedido: defina TELEGRAM_HOME_CHANNEL "
        "(canal home do dono) ou TELNYX_CALL_APPROVAL_CHAT_ID, ou passe --chat-id."
    )


def _telegram_call(method: str, payload: dict, env=None) -> dict:
    import requests

    token = _bot_token(env)
    resp = requests.post(
        "{0}/bot{1}/{2}".format(TELEGRAM_API_BASE, token, method),
        json=payload,
        timeout=15,
    )
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 400 or not data.get("ok"):
        raise RuntimeError(
            "Telegram {0} retornou {1}: {2}".format(
                method, resp.status_code, data.get("description") or resp.text[:200]
            )
        )
    return data.get("result") or {}


def send_approval_message(request: dict, env=None, chat_id=None) -> dict:
    """Manda a mensagem com botoes Aprovar/Rejeitar e grava a referencia."""
    env = env if env is not None else os.environ
    chat_id = _owner_chat_id(env, chat_id)
    payload = {
        "chat_id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
        "text": flow.build_approval_message(request),
        "reply_markup": flow.build_inline_keyboard(request["id"]),
    }
    thread_id = (env.get("TELEGRAM_HOME_CHANNEL_THREAD_ID") or "").strip()
    if thread_id.isdigit():
        payload["message_thread_id"] = int(thread_id)
    result = _telegram_call("sendMessage", payload, env=env)
    return store.record_message_ref(
        request["id"], chat_id=chat_id, message_id=result.get("message_id"), env=env,
    )


def _edit_message_after_expiry(request: dict, env=None) -> None:
    """Best-effort: marca a mensagem como expirada e tira os botoes."""
    chat_id = request.get("telegram_chat_id")
    message_id = request.get("telegram_message_id")
    if not chat_id or not message_id:
        return
    text = flow.build_approval_message(request) + "\n\nExpirado sem resposta. Nao vou ligar."
    try:
        _telegram_call("editMessageText", {
            "chat_id": int(chat_id) if str(chat_id).lstrip("-").isdigit() else chat_id,
            "message_id": int(message_id),
            "text": text,
        }, env=env)
    except Exception:
        pass


def _execute(request_id: str, env=None) -> dict:
    from make_call import make_call
    return flow.execute_approved_call(request_id, make_call_fn=make_call, env=env)


def run_request(to: str, contact: str, purpose: str, message=None,
                timeout_seconds=None, chat_id=None, wait=True,
                poll_seconds=2.0, dry_run=False, env=None) -> dict:
    env = env if env is not None else os.environ
    if not is_valid_e164(to):
        return {"error": "destino nao e E.164 valido", "to": to}
    if dry_run:
        return {
            "dry_run": True,
            "would_create_request": {
                "contact": contact, "to": to, "purpose": purpose,
                "message": (message or purpose),
                "timeout_seconds": timeout_seconds or store.approval_timeout_seconds(env),
            },
            "would_send_telegram_to": _owner_chat_id(env, chat_id),
            "note": "nada foi gravado nem enviado (--dry-run)",
        }
    request = store.create_request(
        contact=contact, to=to, purpose=purpose, message=message,
        timeout_seconds=timeout_seconds, env=env,
    )
    try:
        request = send_approval_message(request, env=env, chat_id=chat_id)
    except Exception as exc:
        # Sem a mensagem nao ha como aprovar: expira o pedido na hora.
        store.expire_if_pending(request["id"], env=env)
        return {"error": "falha ao enviar o pedido no Telegram: {0}".format(exc),
                "request_id": request["id"], "approved": False}
    if not wait:
        return {"request_id": request["id"], "status": store.STATUS_PENDING,
                "waiting": False,
                "note": "pedido enviado; confira depois com --status/--execute"}
    outcome = flow.wait_for_decision(request["id"], env=env, poll_seconds=poll_seconds)
    status = outcome.get("status")
    if status == store.STATUS_APPROVED:
        result = _execute(request["id"], env=env)
        result["approved"] = True
        result["status"] = store.STATUS_APPROVED
        return result
    if status == store.STATUS_EXPIRED:
        final = outcome.get("request") or store.get_request(request["id"], env=env) or request
        _edit_message_after_expiry(final, env=env)
    return {"request_id": request["id"], "approved": False, "status": status,
            "note": "nenhuma ligacao foi feita"}


def _cli():
    p = argparse.ArgumentParser(
        description="Aprovacao one-tap no Telegram para ligacoes Telnyx (Hermes)"
    )
    p.add_argument("--to", help="numero destino E.164")
    p.add_argument("--contact", help="nome de quem vamos ligar (pessoa/empresa)")
    p.add_argument("--purpose", help="objetivo da ligacao (vai na mensagem de aprovacao)")
    p.add_argument("--message", default=None,
                   help="texto TTS da ligacao (default: o proprio --purpose)")
    p.add_argument("--timeout-seconds", type=int, default=None,
                   help="prazo de aprovacao (default TELNYX_CALL_APPROVAL_TIMEOUT_SECONDS ou 900)")
    p.add_argument("--chat-id", default=None, help="override do chat do dono")
    p.add_argument("--no-wait", dest="wait", action="store_false",
                   help="so cria e envia o pedido; nao espera a decisao")
    p.add_argument("--poll-seconds", type=float, default=2.0)
    p.add_argument("--dry-run", action="store_true",
                   help="mostra o que faria sem gravar nem enviar nada")
    p.add_argument("--status", metavar="REQUEST_ID", default=None,
                   help="mostra um pedido existente")
    p.add_argument("--execute", metavar="REQUEST_ID", default=None,
                   help="executa um pedido JA aprovado (claim de uso unico)")
    p.add_argument("--list", dest="list_requests", action="store_true",
                   help="lista os pedidos recentes (auditoria)")
    p.add_argument("--days", type=float, default=7.0, help="janela do --list em dias")
    args = p.parse_args()

    if args.list_requests:
        out = store.list_requests(days=args.days)
    elif args.status:
        out = store.get_request(args.status) or {"error": "pedido nao encontrado",
                                                 "request_id": args.status}
    elif args.execute:
        if args.dry_run:
            out = {"dry_run": True, "request_id": args.execute,
                   "note": "nada executado (--dry-run)"}
        else:
            out = _execute(args.execute)
    else:
        missing = [name for name, value in
                   (("--to", args.to), ("--contact", args.contact), ("--purpose", args.purpose))
                   if not value]
        if missing:
            p.error("faltou " + ", ".join(missing))
        out = run_request(
            to=args.to, contact=args.contact, purpose=args.purpose,
            message=args.message, timeout_seconds=args.timeout_seconds,
            chat_id=args.chat_id, wait=args.wait,
            poll_seconds=args.poll_seconds, dry_run=args.dry_run,
        )

    print(json.dumps(out, ensure_ascii=False, indent=2))
    if isinstance(out, dict) and out.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    _cli()
