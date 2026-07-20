"""
Testes PUROS da orquestracao de aprovacao one-tap (_call_approval_flow.py).

Sem rede. Provam as garantias centrais do fluxo:
  - a mensagem de aprovacao traz contato, numero e motivo, sem em/en-dash (u2014/u2013);
  - callback_data cabe no limite de 64 bytes do Telegram e faz roundtrip;
  - execute_approved_call e o UNICO caminho ate a discagem: pedido
    pendente/rejeitado/expirado/inexistente NUNCA chama make_call_fn;
  - aprovado dispara EXATAMENTE uma vez (replay/double-execute recusado);
  - o overlay de env adiciona SO o numero aprovado a allowlist da chamada;
  - os trilhos existentes continuam por cima: com o teto diario estourado
    ou os gates de env fechados, mesmo um pedido aprovado NAO disca
    (provado com o make_call REAL, com requests.post mockado);
  - wait_for_decision expira no prazo sem discar.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _call_approval_flow as flow  # noqa: E402
import _call_approval_store as cas  # noqa: E402


def _env(tmp):
    return {
        "TELNYX_CALL_APPROVAL_STORE_PATH": os.path.join(tmp, "store.json"),
        "TELNYX_CALL_APPROVAL_AUDIT_PATH": os.path.join(tmp, "audit.jsonl"),
    }


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = _env(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def _create(self, **kwargs):
        defaults = dict(contact="Luiza (Techmax)", to="+14075551234",
                        purpose="Confirmar a visita de amanha as 9h",
                        message="Bom dia, Luiza. Confirmando a visita de amanha as 9h.",
                        env=self.env)
        defaults.update(kwargs)
        return cas.create_request(**defaults)

    def _approve(self, req):
        cas.decide_request(req["id"], "approve", decided_by="111",
                           decided_by_name="Fernando", env=self.env)

    def _audit_events(self):
        path = Path(self.env["TELNYX_CALL_APPROVAL_AUDIT_PATH"])
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class MessageAndKeyboardTestCase(BaseCase):
    def test_message_has_contact_number_purpose(self):
        req = self._create()
        text = flow.build_approval_message(req)
        self.assertIn("Luiza (Techmax)", text)
        self.assertIn("+14075551234", text)
        self.assertIn("Confirmar a visita de amanha as 9h", text)
        self.assertIn(req["id"], text)
        self.assertIn("15 minutos", text)

    def test_message_has_no_em_or_en_dash(self):
        req = self._create()
        text = flow.build_approval_message(req)
        self.assertNotIn("\u2014", text)
        self.assertNotIn("\u2013", text)

    def test_callback_data_roundtrip_and_size(self):
        req = self._create()
        keyboard = flow.build_inline_keyboard(req["id"])
        buttons = keyboard["inline_keyboard"][0]
        self.assertEqual(len(buttons), 2)
        approve_data = buttons[0]["callback_data"]
        reject_data = buttons[1]["callback_data"]
        # Telegram limita callback_data a 64 bytes.
        self.assertLessEqual(len(approve_data.encode("utf-8")), 64)
        self.assertLessEqual(len(reject_data.encode("utf-8")), 64)
        self.assertEqual(flow.parse_callback_data(approve_data), ("a", req["id"]))
        self.assertEqual(flow.parse_callback_data(reject_data), ("r", req["id"]))

    def test_parse_rejects_garbage(self):
        for bad in ("", "callreq:", "callreq:x:cr1", "callreq:a:", "ea:once:1",
                    "callreq:a:" + "x" * 40, "callreq:a:../etc"):
            self.assertIsNone(flow.parse_callback_data(bad), bad)


class OnlyPathToDialTestCase(BaseCase):
    """Prova: o unico caminho ate a discagem passa por pedido APROVADO."""

    def _never_dial(self, **kwargs):
        self.fail("make_call foi chamado para um pedido nao aprovado")

    def test_pending_never_dials(self):
        req = self._create()
        out = flow.execute_approved_call(req["id"], self._never_dial, env=self.env)
        self.assertFalse(out["executed"])
        self.assertEqual(out["reason"], "not_approved")

    def test_rejected_never_dials(self):
        req = self._create()
        cas.decide_request(req["id"], "reject", decided_by="111", env=self.env)
        out = flow.execute_approved_call(req["id"], self._never_dial, env=self.env)
        self.assertFalse(out["executed"])
        self.assertEqual(out["reason"], "not_approved")

    def test_expired_never_dials(self):
        req = self._create()
        cas.expire_if_pending(req["id"], env=self.env)
        out = flow.execute_approved_call(req["id"], self._never_dial, env=self.env)
        self.assertFalse(out["executed"])

    def test_unknown_request_never_dials(self):
        out = flow.execute_approved_call("cr00000000", self._never_dial, env=self.env)
        self.assertFalse(out["executed"])
        self.assertEqual(out["reason"], "not_found")

    def test_refusals_are_audited(self):
        req = self._create()
        flow.execute_approved_call(req["id"], self._never_dial, env=self.env)
        events = [e["event"] for e in self._audit_events()]
        self.assertIn("execute_refused", events)


class ApprovedExecutionTestCase(BaseCase):
    def test_approved_dials_exactly_once(self):
        req = self._create()
        self._approve(req)
        calls = []

        def fake_make_call(to, message, dry_run=True, env=None, approved_request_id=None):
            calls.append({"to": to, "message": message, "dry_run": dry_run,
                          "env": env, "approved_request_id": approved_request_id})
            return {"sent": True, "call_control_id": "cc-1", "to": to}

        first = flow.execute_approved_call(req["id"], fake_make_call, env=self.env)
        second = flow.execute_approved_call(req["id"], fake_make_call, env=self.env)

        self.assertTrue(first["executed"])
        self.assertTrue(first["sent"])
        self.assertFalse(second["executed"])
        self.assertEqual(second["reason"], "already_claimed")
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0]["dry_run"])
        self.assertEqual(calls[0]["approved_request_id"], req["id"])

    def test_overlay_allowlists_only_the_approved_number(self):
        req = self._create()
        self._approve(req)
        captured = {}

        def fake_make_call(to, message, dry_run=True, env=None, approved_request_id=None):
            captured.update(env)
            return {"sent": True, "call_control_id": "cc-1"}

        base = dict(self.env)
        base["TELNYX_ALLOWED_RECIPIENTS"] = "+16174505166"
        flow.execute_approved_call(req["id"], fake_make_call, env=base)
        self.assertEqual(captured["TELNYX_ALLOWED_RECIPIENTS"],
                         "+16174505166,+14075551234")
        # O env base do processo nao foi mutado.
        self.assertEqual(base["TELNYX_ALLOWED_RECIPIENTS"], "+16174505166")

    def test_result_is_linked_to_the_approval_in_store_and_audit(self):
        req = self._create()
        self._approve(req)
        flow.execute_approved_call(
            req["id"],
            lambda **kw: {"sent": True, "call_control_id": "cc-99"},
            env=self.env,
        )
        stored = cas.get_request(req["id"], env=self.env)
        self.assertEqual(stored["execution"]["call_control_id"], "cc-99")
        executed = [e for e in self._audit_events() if e["event"] == "executed"]
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0]["request_id"], req["id"])

    def test_make_call_exception_is_recorded_and_never_retried(self):
        req = self._create()
        self._approve(req)
        calls = []

        def boom(**kwargs):
            calls.append(1)
            raise RuntimeError("Telnyx 500")

        out = flow.execute_approved_call(req["id"], boom, env=self.env)
        self.assertTrue(out["executed"])
        self.assertFalse(out["sent"])
        self.assertEqual(len(calls), 1)
        # Claim consumido: nem uma nova tentativa depois da falha.
        again = flow.execute_approved_call(req["id"], boom, env=self.env)
        self.assertFalse(again["executed"])
        self.assertEqual(len(calls), 1)


class RailsStayOnTopTestCase(BaseCase):
    """Com o make_call REAL (requests.post mockado): aprovacao nao pula
    os gates de env nem o teto diario."""

    def _real_make_call(self):
        import make_call as mc
        return mc

    def test_env_gates_closed_approved_call_does_not_dial(self):
        mc = self._real_make_call()
        req = self._create()
        self._approve(req)
        with mock.patch("make_call.requests.post") as post_mock:
            out = flow.execute_approved_call(req["id"], mc.make_call, env=dict(self.env))
        post_mock.assert_not_called()
        self.assertTrue(out["executed"])
        self.assertFalse(out["sent"])
        stored = cas.get_request(req["id"], env=self.env)
        self.assertFalse(stored["execution"]["sent"])

    def test_daily_cap_still_blocks_approved_call(self):
        mc = self._real_make_call()
        req = self._create()
        self._approve(req)
        ledger = Path(self.tmp.name) / "ledger.jsonl"
        today = datetime.now(timezone.utc).isoformat()
        with ledger.open("w", encoding="utf-8") as fh:
            for _ in range(2):
                fh.write(json.dumps({"at": today, "action": "make_call",
                                     "to": "***1234", "sent": True}) + "\n")
        env = dict(self.env)
        env.update({
            "HERMES_ALLOW_EXECUTE": "true",
            "TELNYX_VOICE_SMS_ENABLED": "true",
            "TELNYX_API_KEY": "sk-test",
            "TELNYX_CONNECTION_ID": "conn-test",
            "TELNYX_SEND_LEDGER_PATH": str(ledger),
            "TELNYX_DAILY_SEND_CAP": "2",
        })
        with mock.patch("make_call.requests.post") as post_mock:
            out = flow.execute_approved_call(req["id"], mc.make_call, env=env)
        post_mock.assert_not_called()
        self.assertFalse(out["sent"])
        self.assertTrue(out.get("blocked"))

    def test_gates_open_within_cap_dials_once_with_disclosure(self):
        mc = self._real_make_call()
        req = self._create()
        self._approve(req)
        env = dict(self.env)
        env.update({
            "HERMES_ALLOW_EXECUTE": "true",
            "TELNYX_VOICE_SMS_ENABLED": "true",
            "TELNYX_API_KEY": "sk-test",
            "TELNYX_CONNECTION_ID": "conn-test",
            "TELNYX_SEND_LEDGER_PATH": os.path.join(self.tmp.name, "ledger.jsonl"),
        })
        fake_resp = mock.Mock(status_code=200)
        fake_resp.json.return_value = {"data": {"call_control_id": "cc-7",
                                                "call_leg_id": "leg-7"}}
        with mock.patch("make_call.requests.post", return_value=fake_resp) as post_mock:
            out = flow.execute_approved_call(req["id"], mc.make_call, env=env)
        self.assertTrue(out["sent"])
        self.assertEqual(out["call_control_id"], "cc-7")
        self.assertEqual(out["approved_request_id"], req["id"])
        post_mock.assert_called_once()
        payload = post_mock.call_args[1]["json"]
        self.assertEqual(payload["to"], "+14075551234")
        # O client_state (mensagem TTS) comeca com a identificacao de IA.
        import base64
        spoken = base64.b64decode(payload["client_state"]).decode("utf-8")
        self.assertTrue(spoken.startswith(mc.DEFAULT_AI_DISCLOSURE))
        self.assertIn("Confirmando a visita", spoken)


class WaitForDecisionTestCase(BaseCase):
    def test_returns_when_decided(self):
        req = self._create()
        cas.decide_request(req["id"], "reject", decided_by="111", env=self.env)
        out = flow.wait_for_decision(req["id"], env=self.env,
                                     sleep_fn=lambda s: self.fail("nao devia dormir"))
        self.assertEqual(out["status"], "rejected")

    def test_expires_at_deadline_without_dialing(self):
        req = self._create()
        late = datetime.now(timezone.utc) + timedelta(seconds=901)
        out = flow.wait_for_decision(req["id"], env=self.env,
                                     sleep_fn=lambda s: None,
                                     now_fn=lambda: late)
        self.assertEqual(out["status"], "expired")
        self.assertEqual(out["reason"], "expired")
        stored = cas.get_request(req["id"], env=self.env)
        self.assertEqual(stored["status"], "expired")


if __name__ == "__main__":
    unittest.main()
