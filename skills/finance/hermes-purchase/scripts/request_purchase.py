#!/usr/bin/env python3
"""request_purchase.py — Prepara um pedido de compra e faz ENFORCEMENT REAL do
gate humano na confirmação. Nunca cobra nada.

Fluxo (nunca toca cartão / gateway / checkout):
  1. `request` — valida na policy; se PODE_PERGUNTAR, gera um approval-token
     aleatório, grava no ledger APENAS o HASH sha256 do token (nunca o token cru,
     que o daemon veria no stdout), e entrega o token EM TEXTO só no canal humano
     (Telegram, via --notify). Status inicial: 'pendente'.
  2. Humano recebe o token no Telegram e aprova FORA do daemon.
  3. `confirm --id <ID> --status aprovada|paga|recusada --approval-token <TOKEN>` —
     só muda o status (e portanto só libera o teto) se:
       - o token conferir com o hash gravado (hmac.compare_digest), E
       - a env HERMES_PURCHASE_ALLOW_CONFIRM=true estiver setada (vive FORA do
         ambiente do daemon), E
       - o gate padrão de execução estiver aberto (não --dry-run + HERMES_ALLOW_EXECUTE).
     Sem o token humano + a env humana, o daemon NÃO consegue se auto-aprovar —
     nem se vazar o hash, porque precisa do token cru que só foi ao Telegram do dono.

Todo request/confirm (sucesso ou recusa) vira uma linha append-only em audit.log
(quem, quando, decisão, prefixo do hash — NUNCA o token cru).

Uso:
    python scripts/request_purchase.py request --vendor OpenRouter --amount 120 \
        --reason "recarga do teto mensal do briefing" --notify
    python scripts/request_purchase.py confirm --id 20260706-2130-a1b2 \
        --status aprovada --approval-token <TOKEN-DO-TELEGRAM>
    python scripts/request_purchase.py list [--month 2026-07]

Gate de segurança (default = dry-run permanente): a confirmação REAL só ocorre com
  (a) SEM --dry-run, (b) HERMES_ALLOW_EXECUTE=true, (c) HERMES_PURCHASE_ALLOW_CONFIRM=true,
  (d) approval-token correto. --dry-run explícito SEMPRE vence (força o modo seguro).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import policy
import _approval

SKILL_DIR = Path(__file__).resolve().parent.parent
AUDIT_PATH = SKILL_DIR / "audit.log"


def _gen_id() -> str:
    now = datetime.now()
    # id determinístico-ish por timestamp; sufixo do micro pra unicidade
    return "{:%Y%m%d-%H%M}-{:04x}".format(now, now.microsecond & 0xFFFF)


def _append(entry: dict) -> None:
    # fonte única de verdade do caminho do ledger: policy.LEDGER_PATH
    with open(policy.LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _rewrite(entries) -> None:
    with open(policy.LEDGER_PATH, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def _actor(env) -> str:
    return (env.get("HERMES_ACTOR") or env.get("USER") or "desconhecido")


def _audit(env, cmd: str, pid, decision: str, **extra) -> None:
    """Linha append-only em audit.log. NUNCA grava o token cru — só prefixo de hash."""
    rec = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "actor": _actor(env),
        "cmd": cmd,
        "id": pid,
        "decision": decision,
    }
    rec.update(extra)
    try:
        with open(AUDIT_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        # auditoria é best-effort; nunca deixa a auditoria derrubar a decisão
        pass


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def cmd_request(args, env=None):
    env = env if env is not None else os.environ
    verdict = policy.check(args.vendor, args.amount)
    if verdict["decision"] != "PODE_PERGUNTAR":
        _audit(env, "request", None, "BLOQUEADA_POLICY",
               vendor=args.vendor, amount=args.amount)
        _emit({"blocked": True, **verdict})
        sys.exit(2)

    # --dry-run explícito: preview, nenhum efeito (nem ledger, nem token, nem envio).
    if getattr(args, "dry_run", False):
        _audit(env, "request", None, "DRY_RUN", vendor=args.vendor, amount=args.amount)
        _emit({
            "ok": True, "dry_run": True, "status": "seria_pendente",
            "vendor": args.vendor, "amount": args.amount, "reason": args.reason,
            "would_do": ("gerar approval-token, gravar só o hash no ledger e entregar "
                         "o token ao canal humano (Telegram). Nada foi gravado nem enviado."),
            "spent_month": verdict["spent_month"], "remaining_month": verdict["remaining_month"],
        })
        return

    pid = _gen_id()
    token = _approval.generate_token()
    token_hash = _approval.hash_token(token)
    entry = {
        "id": pid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "month": verdict["month"],
        "vendor": args.vendor,
        "amount": args.amount,
        "currency": verdict["currency"],
        "reason": args.reason,
        "status": "pendente",
        # SÓ o hash — nunca o token cru. É isto que o daemon consegue ler.
        "approval_token_sha256": token_hash,
    }
    _append(entry)

    daemon_msg, human_msg = _approval.build_messages(
        pid, args.vendor, args.amount, args.reason,
        verdict["spent_month"], verdict["remaining_month"], token,
    )

    # Gate padrão de execução para a entrega REAL do token no Telegram.
    nd = _approval.decide_notify(env, getattr(args, "dry_run", False), args.notify)
    sent = None
    if nd["send"]:
        try:
            # reusa o entregador da skill de monitor, se disponível
            monitor = SKILL_DIR.parent.parent / "productivity" / "axtro-factory-monitor" / "scripts"
            sys.path.insert(0, str(monitor))
            import telegram_send  # type: ignore
            sent = telegram_send.send(human_msg)  # human_msg (com token) só vai p/ Telegram
        except Exception as e:  # noqa: BLE001
            sent = {"ok": False, "error": str(e)[:200]}

    delivered = bool(sent and sent.get("ok"))
    _audit(env, "request", pid, "PENDENTE",
           vendor=args.vendor, amount=args.amount,
           token_hash_prefix=_approval.hash_prefix(token_hash),
           notified=delivered)

    out = {
        "ok": True, "id": pid, "status": "pendente",
        "message": daemon_msg,  # SEM o token — é o que o daemon vê
        "approval_delivered": delivered,
        "approval_delivery": (
            "approval-token entregue no canal humano (Telegram)" if delivered else
            "approval-token NÃO entregue ({}). Rode em modo real com --notify + "
            "HERMES_ALLOW_EXECUTE=true + HERMES_PURCHASE_ENABLED=true para o dono "
            "receber o token no Telegram.".format(nd["reason"])
        ),
        "spent_month": verdict["spent_month"],
        "remaining_month": verdict["remaining_month"],
        "note": "O token cru nunca aparece aqui no stdout — só no Telegram do dono.",
    }
    _emit(out)


def cmd_confirm(args, env=None):
    env = env if env is not None else os.environ
    valid = {"aprovada", "paga", "recusada"}
    if args.status not in valid:
        _emit({"ok": False, "error": "status inválido; use {}".format(sorted(valid))})
        sys.exit(1)

    entries = policy.load_ledger()
    entry = None
    for e in entries:
        if e.get("id") == args.id:
            entry = e
            break
    if entry is None:
        _audit(env, "confirm", args.id, "ID_NAO_ENCONTRADO", status_to=args.status)
        _emit({"ok": False, "error": "id não encontrado: {}".format(args.id)})
        sys.exit(1)

    stored_hash = entry.get("approval_token_sha256")
    provided = getattr(args, "approval_token", None)
    decision = _approval.decide_confirm(
        provided, stored_hash, env, getattr(args, "dry_run", False),
    )

    # Auditoria: sempre, com prefixo do hash do token FORNECIDO (nunca o token cru).
    _audit(env, "confirm", args.id, decision["decision"],
           status_to=args.status,
           token_present=bool(provided),
           provided_hash_prefix=(_approval.hash_prefix(_approval.hash_token(provided))
                                 if provided else None))

    if decision["decision"] != "CONFIRMAR":
        out = {
            "ok": bool(decision["dry_run"]),
            "id": args.id,
            "decision": decision["decision"],
            "dry_run": decision["dry_run"],
            "reason": decision["reason"],
            "status": entry.get("status"),  # inalterado
        }
        if decision["dry_run"]:
            out["would_set_status"] = args.status
            out["note"] = "dry-run: nenhum status foi alterado, nenhum teto liberado."
        _emit(out)
        sys.exit(decision["exit_code"])

    # Aprovação real: token confere + env humana + gate de execução aberto.
    # Teto mensal VINCULANTE no momento da aprovação (fail-closed): mesmo com token
    # humano válido, aprovar/pagar não pode estourar o monthly_cap. Sem isto, o teto
    # seria só um guarda no `request` e N pendentes aprovados um a um o furariam.
    if args.status in ("aprovada", "paga"):
        cfg = policy.load_config()
        if _approval.would_exceed_monthly_cap(
                entries, args.id, entry.get("month"), entry.get("amount"), cfg["monthly_cap"]):
            spent = policy.month_to_date_spent(entry.get("month"))
            _audit(env, "confirm", args.id, "RECUSADA_ESTOURA_TETO",
                   status_to=args.status, amount=entry.get("amount"),
                   spent_month=spent, monthly_cap=cfg["monthly_cap"])
            _emit({
                "ok": False, "id": args.id, "decision": "RECUSADA_ESTOURA_TETO",
                "reason": ("aprovar estouraria o teto mensal (R$ {:.2f}); já aprovados/pagos "
                           "R$ {:.2f} no mês. Ajuste monthly_cap em config.json de forma "
                           "deliberada se for intencional.").format(cfg["monthly_cap"], spent),
                "status": entry.get("status"),  # inalterado
            })
            sys.exit(5)

    entry["status"] = args.status
    entry["decided_at"] = datetime.now().isoformat(timespec="seconds")
    _rewrite(entries)
    _emit({
        "ok": True, "id": args.id, "status": args.status, "decision": "CONFIRMAR",
        "remaining_month": policy.check("_", 0)["remaining_month"],
    })


def cmd_list(args, env=None):
    entries = policy.load_ledger()
    if args.month:
        entries = [e for e in entries if e.get("month") == args.month]
    # nunca vaza o hash inteiro na listagem — mostra só prefixo p/ correlação
    safe = []
    for e in entries:
        e2 = dict(e)
        h = e2.pop("approval_token_sha256", None)
        if h:
            e2["approval_hash_prefix"] = _approval.hash_prefix(h)
        safe.append(e2)
    _emit({"total": len(safe), "compras": safe})


def build_parser():
    parser = argparse.ArgumentParser(description="Pedido de compra com aprovação humana enforced")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_req = sub.add_parser("request")
    p_req.add_argument("--vendor", required=True)
    p_req.add_argument("--amount", type=float, required=True)
    p_req.add_argument("--reason", required=True)
    p_req.add_argument("--notify", action="store_true", help="entrega o token no Telegram do dono")
    p_req.add_argument("--dry-run", dest="dry_run", action="store_true",
                       help="preview seguro; nada é gravado nem enviado (sempre vence)")
    p_req.set_defaults(func=cmd_request)

    p_conf = sub.add_parser("confirm")
    p_conf.add_argument("--id", required=True)
    p_conf.add_argument("--status", required=True, help="aprovada|paga|recusada")
    p_conf.add_argument("--approval-token", dest="approval_token", default=None,
                        help="token entregue no Telegram do dono (obrigatório p/ efeito real)")
    p_conf.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="preview seguro; nenhum status é alterado (sempre vence)")
    p_conf.set_defaults(func=cmd_confirm)

    p_list = sub.add_parser("list")
    p_list.add_argument("--month")
    p_list.set_defaults(func=cmd_list)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
