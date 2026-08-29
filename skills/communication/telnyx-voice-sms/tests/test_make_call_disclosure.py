"""
Testes do prefixo OBRIGATORIO de identificacao de IA em make_call.py.

Provam que toda ligacao construida comeca se identificando como assistente
de IA em nome do Fernando/Axtro ANTES do conteudo:
  - apply_ai_disclosure prefixa sempre, e idempotente e nunca fica vazio;
  - TELNYX_AI_DISCLOSURE_TEXT troca o texto mas nao consegue desligar
    (vazio/espacos volta ao default);
  - o caminho REAL de execucao (requests.post mockado) manda o client_state
    (a fala TTS) ja prefixado, em qualquer chamada, inclusive --self.

Mocka requests.post: nenhuma chamada de rede real.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import base64
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import make_call as mc  # noqa: E402

GATES_OPEN = {
    "HERMES_ALLOW_EXECUTE": "true",
    "TELNYX_VOICE_SMS_ENABLED": "true",
    "TELNYX_API_KEY": "sk-test",
    "TELNYX_CONNECTION_ID": "conn-test",
}


class ApplyDisclosureTestCase(unittest.TestCase):
    def test_prefixes_the_message(self):
        out = mc.apply_ai_disclosure("Bom dia, tudo bem?", env={})
        self.assertTrue(out.startswith(mc.DEFAULT_AI_DISCLOSURE))
        self.assertTrue(out.endswith("Bom dia, tudo bem?"))

    def test_is_idempotent(self):
        once = mc.apply_ai_disclosure("Oi", env={})
        twice = mc.apply_ai_disclosure(once, env={})
        self.assertEqual(once, twice)

    def test_empty_message_still_discloses(self):
        self.assertEqual(mc.apply_ai_disclosure("", env={}), mc.DEFAULT_AI_DISCLOSURE)
        self.assertEqual(mc.apply_ai_disclosure(None, env={}), mc.DEFAULT_AI_DISCLOSURE)

    def test_env_override_changes_text_but_cannot_disable(self):
        custom = "This is an AI assistant calling on behalf of Fernando Silva at Axtro AI."
        out = mc.apply_ai_disclosure("Hello", env={"TELNYX_AI_DISCLOSURE_TEXT": custom})
        self.assertTrue(out.startswith(custom))
        # Vazio ou so espacos NAO desligam o prefixo.
        for disabled in ("", "   "):
            out = mc.apply_ai_disclosure("Hello", env={"TELNYX_AI_DISCLOSURE_TEXT": disabled})
            self.assertTrue(out.startswith(mc.DEFAULT_AI_DISCLOSURE))

    def test_default_has_no_em_or_en_dash(self):
        self.assertNotIn("\u2014", mc.DEFAULT_AI_DISCLOSURE)
        self.assertNotIn("\u2013", mc.DEFAULT_AI_DISCLOSURE)


class ExecutedCallSpeaksDisclosureTestCase(unittest.TestCase):
    def _dial(self, to, message, env):
        fake_resp = mock.Mock(status_code=200)
        fake_resp.json.return_value = {"data": {"call_control_id": "cc-1",
                                                "call_leg_id": "leg-1"}}
        with mock.patch("make_call.requests.post", return_value=fake_resp) as post_mock:
            plan = mc.make_call(to, message, dry_run=False, env=env)
        post_mock.assert_called_once()
        payload = post_mock.call_args[1]["json"]
        spoken = base64.b64decode(payload["client_state"]).decode("utf-8")
        return plan, spoken

    def test_self_call_starts_with_disclosure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(GATES_OPEN)
            env["TELNYX_SEND_LEDGER_PATH"] = os.path.join(tmp, "ledger.jsonl")
            plan, spoken = self._dial("+16174505166", "teste interno", env)
        self.assertTrue(plan["sent"])
        self.assertTrue(spoken.startswith(mc.DEFAULT_AI_DISCLOSURE))
        self.assertIn("teste interno", spoken)

    def test_allowlisted_third_party_call_starts_with_disclosure(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(GATES_OPEN)
            env["TELNYX_SEND_LEDGER_PATH"] = os.path.join(tmp, "ledger.jsonl")
            env["TELNYX_ALLOWED_RECIPIENTS"] = "+14075551234"
            plan, spoken = self._dial("+14075551234", "Confirmando a visita.", env)
        self.assertTrue(plan["sent"])
        self.assertTrue(spoken.startswith(mc.DEFAULT_AI_DISCLOSURE))

    def test_approved_request_id_is_stamped_on_the_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(GATES_OPEN)
            env["TELNYX_SEND_LEDGER_PATH"] = os.path.join(tmp, "ledger.jsonl")
            fake_resp = mock.Mock(status_code=200)
            fake_resp.json.return_value = {"data": {"call_control_id": "cc-1"}}
            with mock.patch("make_call.requests.post", return_value=fake_resp):
                plan = mc.make_call("+16174505166", "oi", dry_run=False, env=env,
                                    approved_request_id="cr12345678")
        self.assertEqual(plan["approved_request_id"], "cr12345678")

    def test_dry_run_still_never_dials(self):
        with mock.patch("make_call.requests.post") as post_mock:
            plan = mc.make_call("+16174505166", "oi", dry_run=True, env=dict(GATES_OPEN))
        post_mock.assert_not_called()
        self.assertFalse(plan["sent"])
        self.assertTrue(plan["dry_run"])


if __name__ == "__main__":
    unittest.main()
