#!/usr/bin/env python3
"""policy.py — Guarda-corpo de compra do Hermes.

NUNCA cobra nada. Só decide se uma compra PODE ser proposta ao humano, aplicando:
  1. Allowlist de fornecedor (só fornecedores pré-aprovados).
  2. Teto mensal (padrão R$500) — soma o que já foi gasto no mês corrente.
  3. Teto por compra.
Toda compra, mesmo dentro dos limites, ainda exige aprovação humana explícita
(este módulo só devolve PODE_PERGUNTAR — a cobrança é ato humano).

Uso:
    python scripts/policy.py --vendor "OpenRouter" --amount 120.00
    python scripts/policy.py --status        # orçamento restante do mês

Config: hermes-purchase/config.json (copie de config.example.json).
Livro-caixa: hermes-purchase/ledger.jsonl (JSONL, uma compra por linha).
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = SKILL_DIR / "config.json"
LEDGER_PATH = SKILL_DIR / "ledger.jsonl"

DEFAULTS = {
    "currency": "BRL",
    "monthly_cap": 500.0,
    "per_purchase_cap": 300.0,
    "vendor_allowlist": [],  # ex: ["OpenRouter", "Railway", "Anthropic", "Supabase"]
}


def load_config() -> dict:
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            pass
    return cfg


def _current_month() -> str:
    now = datetime.now()
    return "{:04d}-{:02d}".format(now.year, now.month)


def load_ledger() -> list:
    if not LEDGER_PATH.exists():
        return []
    entries = []
    for line in LEDGER_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def month_to_date_spent(month: str = None) -> float:
    """Soma compras com status 'aprovada'/'paga' no mês (pendentes não contam)."""
    month = month or _current_month()
    total = 0.0
    for e in load_ledger():
        if e.get("month") == month and e.get("status") in ("aprovada", "paga"):
            try:
                total += float(e.get("amount", 0))
            except (TypeError, ValueError):
                continue
    return round(total, 2)


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def check(vendor: str, amount: float) -> dict:
    cfg = load_config()
    month = _current_month()
    spent = month_to_date_spent(month)
    remaining = round(cfg["monthly_cap"] - spent, 2)

    reasons = []
    allow = [v for v in cfg.get("vendor_allowlist", [])]
    if _norm(vendor) not in [_norm(v) for v in allow]:
        reasons.append("fornecedor '{}' fora da allowlist".format(vendor))
    if amount <= 0:
        reasons.append("valor inválido")
    if amount > cfg["per_purchase_cap"]:
        reasons.append("acima do teto por compra (R$ {:.2f})".format(cfg["per_purchase_cap"]))
    if amount > remaining:
        reasons.append("estoura o teto mensal (restam R$ {:.2f} de R$ {:.2f})".format(
            remaining, cfg["monthly_cap"]))

    decision = "PODE_PERGUNTAR" if not reasons else "BLOQUEADA"
    return {
        "decision": decision,
        "vendor": vendor,
        "amount": amount,
        "currency": cfg["currency"],
        "month": month,
        "spent_month": spent,
        "remaining_month": remaining,
        "blockers": reasons,
        "note": (
            "PODE_PERGUNTAR não é autorização — é só sinal verde para PEDIR aprovação "
            "humana. A cobrança em si é sempre ato humano."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description="Guarda-corpo de compra do Hermes")
    parser.add_argument("--vendor")
    parser.add_argument("--amount", type=float)
    parser.add_argument("--status", action="store_true", help="orçamento restante do mês")
    args = parser.parse_args()

    if args.status or not (args.vendor and args.amount is not None):
        cfg = load_config()
        month = _current_month()
        spent = month_to_date_spent(month)
        print(json.dumps({
            "month": month,
            "monthly_cap": cfg["monthly_cap"],
            "per_purchase_cap": cfg["per_purchase_cap"],
            "spent_month": spent,
            "remaining_month": round(cfg["monthly_cap"] - spent, 2),
            "vendor_allowlist": cfg.get("vendor_allowlist", []),
        }, ensure_ascii=False, indent=2))
        return

    print(json.dumps(check(args.vendor, args.amount), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
