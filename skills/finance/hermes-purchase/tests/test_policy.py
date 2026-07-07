"""
Testes do guarda-corpo de compra (policy.py + request_purchase.py).
Sem rede, sem Telegram real — usa config/ledger temporários isolados por teste.

    python -m unittest discover -s tests
    # ou: pytest tests/
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import policy  # noqa: E402


class PolicyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        policy.CONFIG_PATH = Path(self.tmpdir.name) / "config.json"
        policy.LEDGER_PATH = Path(self.tmpdir.name) / "ledger.jsonl"
        with open(policy.CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump({
                "currency": "BRL",
                "monthly_cap": 500.0,
                "per_purchase_cap": 300.0,
                "vendor_allowlist": ["OpenRouter", "Railway", "Anthropic"],
            }, fh)

    def _write_ledger(self, entries):
        with open(policy.LEDGER_PATH, "w", encoding="utf-8") as fh:
            for e in entries:
                fh.write(json.dumps(e) + "\n")

    def test_allowed_vendor_within_caps_can_ask(self):
        result = policy.check("OpenRouter", 120.0)
        self.assertEqual(result["decision"], "PODE_PERGUNTAR")
        self.assertEqual(result["blockers"], [])

    def test_vendor_outside_allowlist_is_blocked(self):
        result = policy.check("Loja Desconhecida", 50.0)
        self.assertEqual(result["decision"], "BLOQUEADA")
        self.assertTrue(any("allowlist" in b for b in result["blockers"]))

    def test_amount_above_per_purchase_cap_is_blocked(self):
        result = policy.check("Railway", 400.0)
        self.assertEqual(result["decision"], "BLOQUEADA")
        self.assertTrue(any("por compra" in b for b in result["blockers"]))

    def test_zero_or_negative_amount_is_blocked(self):
        self.assertEqual(policy.check("Anthropic", 0)["decision"], "BLOQUEADA")
        self.assertEqual(policy.check("Anthropic", -10)["decision"], "BLOQUEADA")

    def test_pending_purchase_does_not_consume_monthly_cap(self):
        month = policy._current_month()
        self._write_ledger([
            {"id": "p1", "month": month, "amount": 200, "status": "pendente"},
        ])
        self.assertEqual(policy.month_to_date_spent(), 0.0)

    def test_approved_and_paid_purchases_consume_monthly_cap(self):
        month = policy._current_month()
        self._write_ledger([
            {"id": "p1", "month": month, "amount": 200, "status": "aprovada"},
            {"id": "p2", "month": month, "amount": 50, "status": "paga"},
            {"id": "p3", "month": month, "amount": 999, "status": "recusada"},
        ])
        self.assertEqual(policy.month_to_date_spent(), 250.0)

    def test_purchase_that_would_exceed_remaining_monthly_budget_is_blocked(self):
        month = policy._current_month()
        self._write_ledger([
            {"id": "p1", "month": month, "amount": 250, "status": "aprovada"},
        ])
        # restam 250 do teto de 500; pedir 260 (dentro do teto por compra de 300) deve bloquear
        result = policy.check("OpenRouter", 260.0)
        self.assertEqual(result["decision"], "BLOQUEADA")
        self.assertTrue(any("teto mensal" in b for b in result["blockers"]))

    def test_vendor_match_is_case_insensitive(self):
        result = policy.check("openrouter", 10.0)
        self.assertEqual(result["decision"], "PODE_PERGUNTAR")

    def test_status_never_grants_spending_only_asking(self):
        # invariante de segurança: a nota de PODE_PERGUNTAR nunca pode virar autorização de
        # gasto — testa que o campo existe e deixa isso explícito no contrato do módulo.
        result = policy.check("OpenRouter", 50.0)
        self.assertIn("não é autorização", result["note"])


if __name__ == "__main__":
    unittest.main()
