"""
Testes de read_inbox — regressão do achado da validação independente (Fable 5):
last_sms()/recent_sms() de BIBLIOTECA vazavam o OTP cru (a máscara só existia no
CLI). O daemon importa `from read_inbox import last_sms`, então a via de biblioteca
precisa mascarar por padrão igual ao CLI. Puro (stdlib), sem rede.
"""
import importlib
import json
import os
import sys
import tempfile
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

GATE = ("HERMES_ALLOW_EXECUTE", "TELNYX_VOICE_SMS_ENABLED")


class ReadInboxMaskingTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.inbox = os.path.join(self.tmpdir.name, "inbox.jsonl")
        with open(self.inbox, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"from": "+1555", "to": "+1617", "text": "Seu codigo e 483920",
                                 "verification_code": "483920", "received_at": "t1"}) + "\n")
            fh.write(json.dumps({"from": "+1999", "to": "+1617", "text": "codigo 778899",
                                 "verification_code": "778899", "received_at": "t2"}) + "\n")
        self._saved_env = {k: os.environ.get(k) for k in GATE + ("SMS_INBOX_PATH",)}
        for k in GATE:
            os.environ.pop(k, None)
        os.environ["SMS_INBOX_PATH"] = self.inbox
        # importa read_inbox com o SMS_INBOX_PATH corrente (path é lido no import)
        import read_inbox
        self.ri = importlib.reload(read_inbox)

    def tearDown(self):
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_last_sms_library_masks_by_default(self):
        out = json.dumps(self.ri.last_sms(), ensure_ascii=False)
        self.assertNotIn("483920", out)  # o mais recente (778899) tambem nao pode vazar
        self.assertNotIn("778899", out)

    def test_recent_sms_library_masks_by_default(self):
        out = json.dumps(self.ri.recent_sms(5), ensure_ascii=False)
        self.assertNotIn("483920", out)
        self.assertNotIn("778899", out)

    def test_last_code_library_masks_by_default(self):
        out = json.dumps(self.ri.last_code(), ensure_ascii=False)
        self.assertNotIn("778899", out)

    def test_reveal_true_without_gate_still_masks(self):
        # reveal=True mas gate fechado → continua mascarado (fail-closed)
        out = json.dumps(self.ri.last_sms(reveal=True), ensure_ascii=False)
        self.assertNotIn("778899", out)

    def test_reveal_true_with_gate_open_reveals(self):
        os.environ["HERMES_ALLOW_EXECUTE"] = "true"
        os.environ["TELNYX_VOICE_SMS_ENABLED"] = "true"
        out = json.dumps(self.ri.last_sms(reveal=True), ensure_ascii=False)
        # com o gate humano aberto E reveal, o codigo pode aparecer
        self.assertIn("778899", out)


if __name__ == "__main__":
    unittest.main()
