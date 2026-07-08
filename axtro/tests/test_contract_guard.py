"""Testes do contract_guard — prova que cada regra R1..R9 bloqueia/permite
corretamente, fail-closed. Puro, sem rede."""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import contract_guard as cg


def base_contract(**over):
    c = {
        "id": "x", "enabled": True, "production_ready": False,
        "activation_stage": "staging", "autonomy_ring": 0,
        "stop_conditions": ["nao faz X"], "telemetry_events": ["x.run"],
        "credentials": [],
    }
    c.update(over)
    return c


class EvaluateRulesTestCase(unittest.TestCase):
    def test_r1_sensitive_without_contract_blocks_real(self):
        d = cg.evaluate(None, {}, sensitive=True, native=False)
        self.assertFalse(d["allow_real"])
        self.assertEqual(d["max_mode"], "blocked")

    def test_r1b_nonsensitive_without_contract_is_dry_run(self):
        d = cg.evaluate(None, {}, sensitive=False, native=False)
        self.assertFalse(d["allow_real"])
        self.assertEqual(d["max_mode"], "dry_run")

    def test_r1c_native_without_contract_passthrough(self):
        d = cg.evaluate(None, {}, native=True)
        self.assertTrue(d["allow_real"])
        self.assertEqual(d["max_mode"], "passthrough")

    def test_r2_missing_required_field_blocks(self):
        c = base_contract(); del c["stop_conditions"]
        d = cg.evaluate(c, {})
        self.assertFalse(d["allow_real"])
        self.assertTrue(any("R2" in r for r in d["reasons"]))

    def test_r3_enabled_false_blocks_real_allows_dryrun(self):
        d = cg.evaluate(base_contract(enabled=False), {})
        self.assertFalse(d["allow_real"])
        self.assertEqual(d["max_mode"], "dry_run")

    def test_r5_empty_stop_conditions_blocks(self):
        d = cg.evaluate(base_contract(stop_conditions=[]), {})
        self.assertFalse(d["allow_real"])
        self.assertTrue(any("R5" in r for r in d["reasons"]))

    def test_r7_missing_credential_fails_closed(self):
        d = cg.evaluate(base_contract(credentials=["MINHA_CHAVE"]), {})  # env sem a chave
        self.assertFalse(d["allow_real"])
        self.assertTrue(any("R7" in r for r in d["reasons"]))

    def test_r7_credential_present_ok(self):
        d = cg.evaluate(base_contract(credentials=["MINHA_CHAVE"]), {"MINHA_CHAVE": "v"})
        self.assertTrue(d["allow_real"])

    def test_r8_ring2_requires_explicit_gate(self):
        d = cg.evaluate(base_contract(autonomy_ring=2), {})  # sem gate
        self.assertFalse(d["allow_real"])
        self.assertTrue(any("R8" in r for r in d["reasons"]))

    def test_r8_ring2_with_gate_allows(self):
        d = cg.evaluate(base_contract(autonomy_ring=2), {"HERMES_ALLOW_EXECUTE": "true"})
        self.assertTrue(d["allow_real"])

    def test_ring4_is_forbidden(self):
        d = cg.evaluate(base_contract(autonomy_ring=4), {"HERMES_ALLOW_EXECUTE": "true"})
        self.assertFalse(d["allow_real"])

    def test_r4_production_ready_false_caps_at_staging(self):
        d = cg.evaluate(base_contract(enabled=True, production_ready=False), {})
        self.assertTrue(d["allow_real"])
        self.assertEqual(d["max_mode"], "staging")

    def test_production_mode_requires_ready_and_telemetry(self):
        d = cg.evaluate(base_contract(enabled=True, production_ready=True,
                                      telemetry_events=["x.run"]), {})
        self.assertEqual(d["max_mode"], "production")
        # telemetry vazio: por especificacao, bloqueia PRODUCAO mas NAO a acao
        # real inteira (isso e o stop_conditions). Real segue em 'staging'.
        d2 = cg.evaluate(base_contract(enabled=True, production_ready=True,
                                       telemetry_events=[]), {})
        self.assertTrue(d2["allow_real"])
        self.assertEqual(d2["max_mode"], "staging")
        self.assertTrue(any("R6" in r for r in d2["reasons"]))

    def test_all_pass_ring0_enabled_allows_real(self):
        d = cg.evaluate(base_contract(enabled=True), {})
        self.assertTrue(d["allow_real"])


class RealContractsTestCase(unittest.TestCase):
    """Os 4 contracts reais das skills corrigidas: todos enabled=false → bloqueados."""
    SKILLS = [
        "productivity/google-workspace-axtro",
        "communication/telnyx-voice-sms",
        "productivity/ask-vps-hermes",
        "finance/hermes-purchase",
    ]

    def test_all_fixed_skills_block_real_action_while_disabled(self):
        repo = Path(__file__).resolve().parents[2]
        for s in self.SKILLS:
            d = cg.authorize(repo / "skills" / s, env={})
            self.assertFalse(d["allow_real"], "%s deveria bloquear (enabled=false)" % s)

    def test_enabling_a_contract_would_allow(self):
        # simula o humano setando enabled=true: a acao real passa a ser permitida
        # (respeitando os demais gates). Usa evaluate direto para nao mutar arquivo.
        repo = Path(__file__).resolve().parents[2]
        c, _ = cg.load_contract(repo / "skills" / "finance/hermes-purchase")
        self.assertFalse(cg.evaluate(c, {})["allow_real"])  # como está: bloqueado
        c_enabled = dict(c); c_enabled["enabled"] = True
        # ring 3 exige gate; com gate + enabled, libera
        d = cg.evaluate(c_enabled, {"HERMES_ALLOW_EXECUTE": "true"})
        self.assertTrue(d["allow_real"])


if __name__ == "__main__":
    unittest.main()
