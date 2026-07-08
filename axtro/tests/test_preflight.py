"""Testes do contract_preflight — o gate de runtime por exit code.
Prova: governada com enabled=false → bloqueia; nativa → pass-through; legacy
Axtro sem contract → bloqueia; erro → fail-closed."""
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro" / "tools"))
import contract_preflight as pf  # noqa: E402


class PreflightTestCase(unittest.TestCase):
    def test_governed_disabled_skill_blocks(self):
        code, msg = pf.preflight(str(REPO / "skills" / "finance" / "hermes-purchase"), env={})
        self.assertEqual(code, pf.EXIT_BLOCK)
        self.assertIn("BLOQUEADA", msg)

    def test_governed_skill_needs_creds_blocks_failclosed(self):
        code, msg = pf.preflight(str(REPO / "skills" / "productivity" / "google-workspace-axtro"), env={})
        self.assertEqual(code, pf.EXIT_BLOCK)

    def test_legacy_axtro_without_contract_blocks(self):
        code, msg = pf.preflight(str(REPO / "skills" / "productivity" / "axtro-factory-monitor"), env={})
        self.assertEqual(code, pf.EXIT_BLOCK)
        self.assertIn("legacy", msg.lower())

    def test_native_nous_skill_passthrough(self):
        # qualquer skill fora da GOVERNED_SKILLS.txt → pass-through, exit 0
        code, msg = pf.preflight(str(REPO / "skills" / "dogfood"), env={})
        self.assertEqual(code, pf.EXIT_ALLOW)
        self.assertIn("PASSTHROUGH", msg)

    def test_enabled_governed_skill_with_creds_and_gate_would_allow(self):
        # simula o estado de produção ativado: a hermes-purchase com enabled=true.
        # (não muta o arquivo — usa o guard direto para provar que o gate liberaria.)
        import contract_guard as cg
        c, _ = cg.load_contract(REPO / "skills" / "finance" / "hermes-purchase")
        c_on = dict(c); c_on["enabled"] = True
        d = cg.evaluate(c_on, {"HERMES_ALLOW_EXECUTE": "true"})
        self.assertTrue(d["allow_real"])  # ligar o contract libera → é controle REAL


if __name__ == "__main__":
    unittest.main()
