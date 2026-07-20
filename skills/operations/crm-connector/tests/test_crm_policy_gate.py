"""
test_crm_policy_gate.py - PURE tests of the read/write classification and
the triple gate (_crm_policy.infer_kind / gate_allows_execute). No network,
no store, mirrors telnyx-voice-sms's test_send_policy.py and dispatch-job's
test_dispatch_policy.py in spirit.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _crm_policy as policy  # noqa: E402


class InferKindIsMethodOnly(unittest.TestCase):
    def test_get_is_read(self):
        self.assertEqual(policy.infer_kind("GET"), "read")

    def test_head_is_read(self):
        self.assertEqual(policy.infer_kind("HEAD"), "read")

    def test_get_lowercase_is_still_read(self):
        self.assertEqual(policy.infer_kind("get"), "read")

    def test_post_is_write(self):
        self.assertEqual(policy.infer_kind("POST"), "write")

    def test_put_is_write(self):
        self.assertEqual(policy.infer_kind("PUT"), "write")

    def test_patch_is_write(self):
        self.assertEqual(policy.infer_kind("PATCH"), "write")

    def test_delete_is_write(self):
        self.assertEqual(policy.infer_kind("DELETE"), "write")

    def test_unknown_or_malformed_method_defaults_to_write(self):
        # Fail-closed: anything not recognized as a read method is treated
        # as a write (never assume something unfamiliar is safe).
        self.assertEqual(policy.infer_kind("TRACE"), "write")
        self.assertEqual(policy.infer_kind(""), "write")
        self.assertEqual(policy.infer_kind(None), "write")


class GateAllowsExecute(unittest.TestCase):
    def test_explicit_dry_run_always_wins(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "CRM_CONNECTOR_ENABLED": "true"}
        self.assertFalse(policy.gate_allows_execute(True, env))

    def test_no_envs_set_blocks_real_execution(self):
        self.assertFalse(policy.gate_allows_execute(False, {}))

    def test_only_global_gate_set_still_blocks(self):
        env = {"HERMES_ALLOW_EXECUTE": "true"}
        self.assertFalse(policy.gate_allows_execute(False, env))

    def test_only_skill_gate_set_still_blocks(self):
        env = {"CRM_CONNECTOR_ENABLED": "true"}
        self.assertFalse(policy.gate_allows_execute(False, env))

    def test_both_envs_set_and_dry_run_flag_false_allows(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "CRM_CONNECTOR_ENABLED": "true"}
        self.assertTrue(policy.gate_allows_execute(False, env))

    def test_case_and_whitespace_insensitive(self):
        env = {"HERMES_ALLOW_EXECUTE": " True ", "CRM_CONNECTOR_ENABLED": " TRUE"}
        self.assertTrue(policy.gate_allows_execute(False, env))

    def test_falsy_values_do_not_allow(self):
        env = {"HERMES_ALLOW_EXECUTE": "1", "CRM_CONNECTOR_ENABLED": "yes"}
        self.assertFalse(policy.gate_allows_execute(False, env))

    def test_defaults_to_os_environ_when_env_omitted(self):
        old = dict(os.environ)
        try:
            os.environ["HERMES_ALLOW_EXECUTE"] = "true"
            os.environ["CRM_CONNECTOR_ENABLED"] = "true"
            self.assertTrue(policy.gate_allows_execute(False))
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
