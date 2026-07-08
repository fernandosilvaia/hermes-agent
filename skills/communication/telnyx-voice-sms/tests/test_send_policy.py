"""
Testes PUROS da política do lado de ENVIO (_send_policy.py).

Sem rede, sem importar requests. Provam o P0 de send/call fechado:
  - allowlist default = só o próprio número; terceiro é BLOQUEADO mesmo com o gate aberto;
  - teto diário bloqueia acima do cap;
  - gate dry-run: ação real só com --dry-run ausente + as duas envs "true";
  - plan_action integra tudo (o caminho dry-run/blocked nunca "executa").

NÃO importa send_sms.py/make_call.py (esses importam requests, indisponível no 3.9.6).

Rodar:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _send_policy as sndp  # noqa: E402

OWN = "+16174505166"
THIRD_PARTY = "+15559998877"


class AllowlistTestCase(unittest.TestCase):
    def test_default_allowlist_is_own_number_only(self):
        allow = sndp._load_recipient_allowlist({})
        self.assertEqual(allow, [OWN])

    def test_default_respects_custom_own_number(self):
        allow = sndp._load_recipient_allowlist({"TELNYX_NUMBER": "+551199999999"})
        self.assertEqual(allow, ["+551199999999"])

    def test_extra_recipients_from_env_csv(self):
        allow = sndp._load_recipient_allowlist(
            {"TELNYX_ALLOWED_RECIPIENTS": "+15551112222, +15553334444"})
        self.assertIn("+15551112222", allow)
        self.assertIn("+15553334444", allow)
        self.assertIn(OWN, allow)


class EvaluateSendTestCase(unittest.TestCase):
    def test_own_number_permitted(self):
        allow = sndp._load_recipient_allowlist({})
        self.assertEqual(sndp.evaluate_send(OWN, allow)["decision"], "PERMITIDO")

    def test_third_party_blocked(self):
        # ATAQUE: mandar SMS/ligação para número arbitrário -> BLOQUEADO.
        allow = sndp._load_recipient_allowlist({})
        decision = sndp.evaluate_send(THIRD_PARTY, allow)
        self.assertEqual(decision["decision"], "BLOQUEADO")
        self.assertIn("allowlist", decision["reason"])

    def test_non_e164_blocked(self):
        allow = sndp._load_recipient_allowlist({})
        self.assertEqual(sndp.evaluate_send("12345", allow)["decision"], "BLOQUEADO")
        self.assertEqual(sndp.evaluate_send("", allow)["decision"], "BLOQUEADO")
        self.assertEqual(sndp.evaluate_send(None, allow)["decision"], "BLOQUEADO")

    def test_third_party_permitted_only_after_allowlisting(self):
        allow = sndp._load_recipient_allowlist(
            {"TELNYX_ALLOWED_RECIPIENTS": THIRD_PARTY})
        self.assertEqual(sndp.evaluate_send(THIRD_PARTY, allow)["decision"], "PERMITIDO")


class DailyCapTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = os.path.join(self.tmp.name, "ledger.jsonl")
        self.now = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)

    def _seed(self, n_today, n_other_day=0):
        with open(self.ledger, "w", encoding="utf-8") as fh:
            for i in range(n_today):
                fh.write(json.dumps({"at": "2026-07-07T09:0{}:00+00:00".format(i % 10),
                                     "action": "send_sms", "sent": True}) + "\n")
            for i in range(n_other_day):
                fh.write(json.dumps({"at": "2026-07-06T09:00:00+00:00",
                                     "action": "send_sms", "sent": True}) + "\n")

    def test_missing_ledger_is_within_cap(self):
        status = sndp.check_daily_cap(self.ledger, cap=2, now=self.now)
        self.assertEqual(status["count"], 0)
        self.assertTrue(status["within_cap"])

    def test_below_cap_within(self):
        self._seed(1)
        status = sndp.check_daily_cap(self.ledger, cap=2, now=self.now)
        self.assertEqual(status["count"], 1)
        self.assertTrue(status["within_cap"])

    def test_at_cap_blocked(self):
        self._seed(2)
        status = sndp.check_daily_cap(self.ledger, cap=2, now=self.now)
        self.assertEqual(status["count"], 2)
        self.assertFalse(status["within_cap"])

    def test_above_cap_blocked(self):
        self._seed(5)
        self.assertFalse(sndp.check_daily_cap(self.ledger, cap=2, now=self.now)["within_cap"])

    def test_only_counts_today(self):
        self._seed(1, n_other_day=9)
        status = sndp.check_daily_cap(self.ledger, cap=2, now=self.now)
        self.assertEqual(status["count"], 1)

    def test_record_send_then_cap_roundtrip(self):
        sndp.record_send(self.ledger, "send_sms", OWN, now=self.now)
        sndp.record_send(self.ledger, "send_sms", OWN, now=self.now)
        status = sndp.check_daily_cap(self.ledger, cap=2, now=self.now)
        self.assertEqual(status["count"], 2)
        self.assertFalse(status["within_cap"])
        # o ledger nunca grava o número inteiro
        blob = Path(self.ledger).read_text(encoding="utf-8")
        self.assertNotIn(OWN, blob)


class GateTestCase(unittest.TestCase):
    BOTH = {"HERMES_ALLOW_EXECUTE": "true", "TELNYX_VOICE_SMS_ENABLED": "true"}

    def test_dry_run_flag_always_wins(self):
        # Mesmo com as duas envs setadas, --dry-run força modo seguro.
        self.assertFalse(sndp.gate_allows_execution(True, self.BOTH))

    def test_missing_env_stays_dry(self):
        self.assertFalse(sndp.gate_allows_execution(False, {}))
        self.assertFalse(sndp.gate_allows_execution(
            False, {"HERMES_ALLOW_EXECUTE": "true"}))
        self.assertFalse(sndp.gate_allows_execution(
            False, {"TELNYX_VOICE_SMS_ENABLED": "true"}))

    def test_execution_only_with_both_envs_and_no_dry_run(self):
        self.assertTrue(sndp.gate_allows_execution(False, self.BOTH))

    def test_env_values_must_be_exactly_true(self):
        self.assertFalse(sndp.gate_allows_execution(
            False, {"HERMES_ALLOW_EXECUTE": "TRUE ", "TELNYX_VOICE_SMS_ENABLED": "1"}))


class PlanActionTestCase(unittest.TestCase):
    """Integração pura: prova que o efeito real só é habilitado no caminho legítimo."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = os.path.join(self.tmp.name, "ledger.jsonl")

    def _env(self, **extra):
        env = {"TELNYX_SEND_LEDGER_PATH": self.ledger}
        env.update(extra)
        return env

    def test_third_party_blocked_even_with_gate_open(self):
        # P0: mesmo com execução 100% habilitada, terceiro fora da allowlist é BLOQUEADO.
        env = self._env(HERMES_ALLOW_EXECUTE="true", TELNYX_VOICE_SMS_ENABLED="true")
        plan = sndp.plan_action("send_sms", THIRD_PARTY, dry_run=False, env=env)
        self.assertTrue(plan["blocked"])
        self.assertFalse(plan["execute"])
        self.assertFalse(plan["sent"])

    def test_own_number_without_gate_is_dry_run(self):
        # Default seguro: sem o gate, nem para o próprio número dispara.
        plan = sndp.plan_action("send_sms", OWN, dry_run=True, env=self._env())
        self.assertTrue(plan["dry_run"])
        self.assertFalse(plan["execute"])
        self.assertFalse(plan["sent"])

    def test_own_number_dry_run_flag_wins_over_envs(self):
        env = self._env(HERMES_ALLOW_EXECUTE="true", TELNYX_VOICE_SMS_ENABLED="true")
        plan = sndp.plan_action("send_sms", OWN, dry_run=True, env=env)
        self.assertTrue(plan["dry_run"])
        self.assertFalse(plan["execute"])

    def test_own_number_with_gate_open_is_executable(self):
        # Caminho legítimo: humano abriu o gate p/ o próprio número -> pode executar.
        env = self._env(HERMES_ALLOW_EXECUTE="true", TELNYX_VOICE_SMS_ENABLED="true")
        plan = sndp.plan_action("send_sms", OWN, dry_run=False, env=env)
        self.assertTrue(plan["execute"])
        self.assertFalse(plan["dry_run"])
        self.assertFalse(plan["sent"])  # plano ainda não é envio; sent só após a API real

    def test_daily_cap_blocks_even_with_gate_open(self):
        env = self._env(HERMES_ALLOW_EXECUTE="true", TELNYX_VOICE_SMS_ENABLED="true",
                        TELNYX_DAILY_SEND_CAP="1")
        now = datetime.now(timezone.utc)
        sndp.record_send(self.ledger, "send_sms", OWN, now=now)  # já bateu o cap=1
        plan = sndp.plan_action("send_sms", OWN, dry_run=False, env=env)
        self.assertTrue(plan["blocked"])
        self.assertFalse(plan["execute"])


if __name__ == "__main__":
    unittest.main()
