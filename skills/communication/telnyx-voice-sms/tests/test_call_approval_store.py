"""
Testes PUROS do store de aprovacao one-tap (_call_approval_store.py).

Sem rede, so stdlib. Provam:
  - criacao de pedido pendente com prazo (default 15 min, env override);
  - decisao atomica e IDEMPOTENTE (a primeira transicao vence; double-tap
    e replay de callback nunca mudam nada);
  - tap depois do prazo NUNCA aprova (vira expired);
  - claim de execucao de USO UNICO sobre pedido aprovado (exatamente uma
    discagem possivel por aprovacao);
  - audit log durvel: toda transicao vira linha JSONL;
  - list_requests responde "que ligacoes voce pediu essa semana".

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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
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
                        purpose="Confirmar a visita de amanha", message="",
                        env=self.env)
        defaults.update(kwargs)
        return cas.create_request(**defaults)

    def _audit_events(self):
        path = Path(self.env["TELNYX_CALL_APPROVAL_AUDIT_PATH"])
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


class CreateRequestTestCase(BaseCase):
    def test_creates_pending_with_default_timeout(self):
        req = self._create()
        self.assertEqual(req["status"], "pending")
        self.assertEqual(req["timeout_seconds"], 900)
        self.assertTrue(req["id"].startswith("cr"))
        self.assertIsNone(req["decided_at"])
        self.assertIsNone(req["execution"])

    def test_message_defaults_to_purpose(self):
        req = self._create(message="")
        self.assertEqual(req["message"], "Confirmar a visita de amanha")

    def test_timeout_env_override(self):
        env = dict(self.env)
        env["TELNYX_CALL_APPROVAL_TIMEOUT_SECONDS"] = "60"
        req = self._create(env=env)
        self.assertEqual(req["timeout_seconds"], 60)

    def test_empty_purpose_raises(self):
        with self.assertRaises(cas.CallApprovalStoreError):
            self._create(purpose="")

    def test_created_is_audited(self):
        req = self._create()
        events = self._audit_events()
        self.assertEqual(events[0]["event"], "created")
        self.assertEqual(events[0]["request_id"], req["id"])
        self.assertEqual(events[0]["to"], "+14075551234")

    def test_store_file_is_owner_only(self):
        self._create()
        mode = os.stat(self.env["TELNYX_CALL_APPROVAL_STORE_PATH"]).st_mode & 0o777
        self.assertEqual(mode, 0o600)


class DecideRequestTestCase(BaseCase):
    def test_approve_records_decision_and_audit(self):
        req = self._create()
        result = cas.decide_request(req["id"], "approve", decided_by="111",
                                    decided_by_name="Fernando", env=self.env)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "approved")
        stored = cas.get_request(req["id"], env=self.env)
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["decided_by"], "111")
        self.assertEqual(stored["decided_by_name"], "Fernando")
        self.assertIsNotNone(stored["decided_at"])
        events = [e["event"] for e in self._audit_events()]
        self.assertIn("approved", events)

    def test_reject_never_leaves_approved(self):
        req = self._create()
        result = cas.decide_request(req["id"], "reject", decided_by="111", env=self.env)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(cas.get_request(req["id"], env=self.env)["status"], "rejected")

    def test_double_tap_is_idempotent_first_decision_wins(self):
        req = self._create()
        first = cas.decide_request(req["id"], "approve", decided_by="111", env=self.env)
        second = cas.decide_request(req["id"], "reject", decided_by="222", env=self.env)
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["reason"], "already_decided")
        stored = cas.get_request(req["id"], env=self.env)
        self.assertEqual(stored["status"], "approved")
        self.assertEqual(stored["decided_by"], "111")

    def test_tap_after_deadline_never_approves(self):
        req = self._create()
        late = datetime.now(timezone.utc) + timedelta(seconds=901)
        result = cas.decide_request(req["id"], "approve", decided_by="111",
                                    env=self.env, now=late)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "expired")
        self.assertEqual(cas.get_request(req["id"], env=self.env)["status"], "expired")

    def test_unknown_request(self):
        result = cas.decide_request("cr00000000", "approve", env=self.env)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "not_found")

    def test_invalid_decision(self):
        req = self._create()
        result = cas.decide_request(req["id"], "yolo", env=self.env)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "invalid_decision")
        self.assertEqual(cas.get_request(req["id"], env=self.env)["status"], "pending")


class ExpireTestCase(BaseCase):
    def test_expire_if_pending(self):
        req = self._create()
        result = cas.expire_if_pending(req["id"], env=self.env)
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "expired")

    def test_expire_does_not_touch_decided(self):
        req = self._create()
        cas.decide_request(req["id"], "approve", decided_by="111", env=self.env)
        result = cas.expire_if_pending(req["id"], env=self.env)
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "approved")


class ClaimExecutionTestCase(BaseCase):
    def test_claim_requires_approved(self):
        req = self._create()
        for status_setter in (None, "reject"):
            pass
        pending = cas.claim_execution(req["id"], env=self.env)
        self.assertFalse(pending["ok"])
        self.assertEqual(pending["reason"], "not_approved")

    def test_claim_exactly_once(self):
        req = self._create()
        cas.decide_request(req["id"], "approve", decided_by="111", env=self.env)
        first = cas.claim_execution(req["id"], env=self.env)
        second = cas.claim_execution(req["id"], env=self.env)
        self.assertTrue(first["ok"])
        self.assertFalse(second["ok"])
        self.assertEqual(second["reason"], "already_claimed")

    def test_rejected_and_expired_can_never_be_claimed(self):
        rejected = self._create()
        cas.decide_request(rejected["id"], "reject", decided_by="111", env=self.env)
        expired = self._create()
        cas.expire_if_pending(expired["id"], env=self.env)
        for req_id in (rejected["id"], expired["id"]):
            result = cas.claim_execution(req_id, env=self.env)
            self.assertFalse(result["ok"])
            self.assertEqual(result["reason"], "not_approved")

    def test_execution_result_links_call_to_approval(self):
        req = self._create()
        cas.decide_request(req["id"], "approve", decided_by="111", env=self.env)
        cas.claim_execution(req["id"], env=self.env)
        stored = cas.record_execution_result(req["id"], sent=True,
                                             call_control_id="cc-42", env=self.env)
        self.assertTrue(stored["execution"]["sent"])
        self.assertEqual(stored["execution"]["call_control_id"], "cc-42")
        events = self._audit_events()
        executed = [e for e in events if e["event"] == "executed"]
        self.assertEqual(len(executed), 1)
        self.assertEqual(executed[0]["request_id"], req["id"])
        self.assertEqual(executed[0]["call_control_id"], "cc-42")


class ListRequestsTestCase(BaseCase):
    def test_lists_recent_first_and_filters_by_days(self):
        old_now = datetime.now(timezone.utc) - timedelta(days=30)
        old = self._create(now=old_now)
        recent = self._create(contact="Gabriel (Ecoloop)", to="+13055550000",
                              purpose="Status da instalacao")
        week = cas.list_requests(days=7, env=self.env)
        self.assertEqual([r["id"] for r in week], [recent["id"]])
        month = cas.list_requests(days=60, env=self.env)
        self.assertEqual(len(month), 2)
        self.assertEqual(month[0]["id"], recent["id"])
        self.assertEqual(month[1]["id"], old["id"])


if __name__ == "__main__":
    unittest.main()
