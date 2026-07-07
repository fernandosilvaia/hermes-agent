#!/usr/bin/env python3
"""request_purchase.py — Prepara um pedido de compra para APROVAÇÃO HUMANA.

Fluxo (nunca cobra nada):
  1. `request` — valida na policy; se PODE_PERGUNTAR, registra no ledger como
     'pendente' e monta a mensagem de aprovação (opcionalmente envia no Telegram).
  2. Humano aprova/recusa fora do agente.
  3. `confirm --id <ID> --status aprovada|paga|recusada` — atualiza o ledger.
     Só 'aprovada'/'paga' contam no teto mensal. NENHUM passo aqui toca o cartão.

Uso:
    python scripts/request_purchase.py request --vendor OpenRouter --amount 120 \
        --reason "recarga do teto mensal do briefing" [--notify]
    python scripts/request_purchase.py confirm --id 20260706-2130-a1b2 --status aprovada
    python scripts/request_purchase.py list [--month 2026-07]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

import policy

SKILL_DIR = Path(__file__).resolve().parent.parent
LEDGER_PATH = SKILL_DIR / "ledger.jsonl"


def _gen_id() -> str:
    now = datetime.now()
    # id determinístico-ish por timestamp; sufixo do micro pra unicidade
    return "{:%Y%m%d-%H%M}-{:04x}".format(now, now.microsecond & 0xFFFF)


def _append(entry: dict) -> None:
    with open(LEDGER_PATH, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _rewrite(entries) -> None:
    with open(LEDGER_PATH, "w", encoding="utf-8") as fh:
        for e in entries:
            fh.write(json.dumps(e, ensure_ascii=False) + "\n")


def cmd_request(args):
    verdict = policy.check(args.vendor, args.amount)
    if verdict["decision"] != "PODE_PERGUNTAR":
        print(json.dumps({"blocked": True, **verdict}, ensure_ascii=False, indent=2))
        sys.exit(2)

    pid = _gen_id()
    entry = {
        "id": pid,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "month": verdict["month"],
        "vendor": args.vendor,
        "amount": args.amount,
        "currency": verdict["currency"],
        "reason": args.reason,
        "status": "pendente",
    }
    _append(entry)

    msg = (
        "🧾 *Pedido de compra* (aprovação necessária)\n"
        "ID: {id}\n"
        "Fornecedor: {vendor}\n"
        "Valor: R$ {amount:.2f}\n"
        "Motivo: {reason}\n"
        "Teto do mês: R$ {spent:.2f} usados · R$ {rem:.2f} restantes\n\n"
        "Responda aprovando ou recusando. Nada foi cobrado — a compra é ato seu."
    ).format(
        id=pid, vendor=args.vendor, amount=args.amount, reason=args.reason,
        spent=verdict["spent_month"], rem=verdict["remaining_month"],
    )

    sent = None
    if args.notify:
        try:
            # reusa o entregador da skill de monitor, se disponível
            monitor = SKILL_DIR.parent.parent / "productivity" / "axtro-factory-monitor" / "scripts"
            sys.path.insert(0, str(monitor))
            import telegram_send  # type: ignore
            sent = telegram_send.send(msg)
        except Exception as e:  # noqa: BLE001
            sent = {"ok": False, "error": str(e)[:200]}

    print(json.dumps({
        "ok": True, "id": pid, "status": "pendente",
        "message": msg, "notified": sent, **{k: verdict[k] for k in ("spent_month", "remaining_month")},
    }, ensure_ascii=False, indent=2))


def cmd_confirm(args):
    entries = policy.load_ledger()
    found = False
    valid = {"aprovada", "paga", "recusada"}
    if args.status not in valid:
        print(json.dumps({"ok": False, "error": "status inválido; use {}".format(valid)}))
        sys.exit(1)
    for e in entries:
        if e.get("id") == args.id:
            e["status"] = args.status
            e["decided_at"] = datetime.now().isoformat(timespec="seconds")
            found = True
            break
    if not found:
        print(json.dumps({"ok": False, "error": "id não encontrado: {}".format(args.id)}))
        sys.exit(1)
    _rewrite(entries)
    print(json.dumps({
        "ok": True, "id": args.id, "status": args.status,
        "remaining_month": policy.check("_", 0)["remaining_month"],
    }, ensure_ascii=False, indent=2))


def cmd_list(args):
    entries = policy.load_ledger()
    if args.month:
        entries = [e for e in entries if e.get("month") == args.month]
    print(json.dumps({"total": len(entries), "compras": entries}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description="Pedido de compra com aprovação humana")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_req = sub.add_parser("request")
    p_req.add_argument("--vendor", required=True)
    p_req.add_argument("--amount", type=float, required=True)
    p_req.add_argument("--reason", required=True)
    p_req.add_argument("--notify", action="store_true", help="envia no Telegram")
    p_req.set_defaults(func=cmd_request)

    p_conf = sub.add_parser("confirm")
    p_conf.add_argument("--id", required=True)
    p_conf.add_argument("--status", required=True, help="aprovada|paga|recusada")
    p_conf.set_defaults(func=cmd_confirm)

    p_list = sub.add_parser("list")
    p_list.add_argument("--month")
    p_list.set_defaults(func=cmd_list)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
