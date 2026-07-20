"""
test_crm_call.py - proves crm_call.call_operation():
  - correctly calls the configured endpoint for READ operations (mocked
    HTTP, no real network), with zero gate required;
  - BLOCKS writes without --execute + both gate envs (dry-run proof), and
    only performs the real HTTP call once all three gate conditions hold;
  - --dry-run explicit always wins, even with both gate envs set;
  - never leaks the api_key in a dry-run preview or in the audit log;
  - degrades cleanly (blocked, no network) for unknown connection/operation
    or missing template params.

All HTTP is mocked via unittest.mock.patch("requests.request", ...) - no
real network access happens in this file.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import connection_store as store  # noqa: E402
import crm_call  # noqa: E402


def _fake_response(status_code=200, body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = body if body is not None else {"ok": True}
    return resp


class CrmCallTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store_path = Path(self._tmp.name) / "connections.json"
        self.audit_path = Path(self._tmp.name) / "audit.log"
        store.upsert_connection(
            "ecoloop", base_url="https://api.ecoloopcrm.com",
            auth={"style": "header", "header_name": "apikey"},
            api_key="sk_live_secret1234", path=self.store_path,
        )
        store.set_operation("ecoloop", "list_leads", {"method": "GET", "path": "/leads"}, path=self.store_path)
        store.set_operation("ecoloop", "get_lead", {"method": "GET", "path": "/leads/{id}"}, path=self.store_path)
        store.set_operation(
            "ecoloop", "update_stage",
            {"method": "PATCH", "path": "/leads/{id}", "body_template": {"stage": "{stage}"}},
            path=self.store_path,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self, **over):
        env = {"CRM_CONNECTOR_AUDIT_PATH": str(self.audit_path)}
        env.update(over)
        return env

    def _audit_lines(self):
        if not self.audit_path.exists():
            return []
        return [json.loads(line) for line in self.audit_path.read_text(encoding="utf-8").splitlines() if line]


class ReadOperationsAreFreelyCallable(CrmCallTestCase):
    @patch("requests.request")
    def test_list_leads_calls_the_configured_endpoint(self, mock_request):
        mock_request.return_value = _fake_response(body={"leads": [{"id": 1}]})
        result = crm_call.call_operation(
            "ecoloop", "list_leads", {}, env=self._env(), store_path=self.store_path,
        )
        self.assertTrue(result["executed"])
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["kind"], "read")
        mock_request.assert_called_once()
        method, url = mock_request.call_args.args
        self.assertEqual(method, "GET")
        self.assertEqual(url, "https://api.ecoloopcrm.com/leads")

    @patch("requests.request")
    def test_get_lead_substitutes_path_param(self, mock_request):
        mock_request.return_value = _fake_response(body={"id": 42})
        crm_call.call_operation(
            "ecoloop", "get_lead", {"id": "42"}, env=self._env(), store_path=self.store_path,
        )
        method, url = mock_request.call_args.args
        self.assertEqual(url, "https://api.ecoloopcrm.com/leads/42")

    @patch("requests.request")
    def test_read_sends_the_configured_auth_header(self, mock_request):
        mock_request.return_value = _fake_response()
        crm_call.call_operation(
            "ecoloop", "list_leads", {}, env=self._env(), store_path=self.store_path,
        )
        headers = mock_request.call_args.kwargs["headers"]
        self.assertEqual(headers.get("apikey"), "sk_live_secret1234")

    @patch("requests.request")
    def test_read_requires_no_gate_envs_at_all(self, mock_request):
        mock_request.return_value = _fake_response()
        # env={} on purpose - no HERMES_ALLOW_EXECUTE, no CRM_CONNECTOR_ENABLED.
        result = crm_call.call_operation(
            "ecoloop", "list_leads", {}, env={}, store_path=self.store_path,
        )
        self.assertTrue(result["executed"])
        mock_request.assert_called_once()

    @patch("requests.request")
    def test_explicit_dry_run_previews_a_read_without_network(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "get_lead", {"id": "42"}, dry_run=True,
            env=self._env(), store_path=self.store_path,
        )
        self.assertTrue(result["dry_run"])
        self.assertEqual(result["would_call"]["url"], "https://api.ecoloopcrm.com/leads/42")
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_dry_run_preview_never_leaks_the_api_key(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "get_lead", {"id": "42"}, dry_run=True,
            env=self._env(), store_path=self.store_path,
        )
        dumped = json.dumps(result)
        self.assertNotIn("sk_live_secret1234", dumped)


class WriteOperationsAreGated(CrmCallTestCase):
    @patch("requests.request")
    def test_write_defaults_to_dry_run_with_no_gate_envs(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"},
            env=self._env(), store_path=self.store_path,
        )
        self.assertTrue(result["dry_run"])
        self.assertFalse(result["executed"])
        self.assertFalse(result["blocked"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_write_still_dry_run_with_only_global_gate(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"}, dry_run=False,
            env=self._env(HERMES_ALLOW_EXECUTE="true"), store_path=self.store_path,
        )
        self.assertTrue(result["dry_run"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_write_still_dry_run_with_only_skill_gate(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"}, dry_run=False,
            env=self._env(CRM_CONNECTOR_ENABLED="true"), store_path=self.store_path,
        )
        self.assertTrue(result["dry_run"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_write_executes_with_both_gates_and_execute(self, mock_request):
        mock_request.return_value = _fake_response(status_code=200, body={"stage": "won"})
        result = crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"}, dry_run=False,
            env=self._env(HERMES_ALLOW_EXECUTE="true", CRM_CONNECTOR_ENABLED="true"),
            store_path=self.store_path,
        )
        self.assertFalse(result["dry_run"])
        self.assertTrue(result["executed"])
        mock_request.assert_called_once()
        method, url = mock_request.call_args.args
        self.assertEqual(method, "PATCH")
        self.assertEqual(url, "https://api.ecoloopcrm.com/leads/1")
        self.assertEqual(mock_request.call_args.kwargs["json"], {"stage": "won"})

    @patch("requests.request")
    def test_explicit_dry_run_always_wins_even_with_both_gates(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"}, dry_run=True,
            env=self._env(HERMES_ALLOW_EXECUTE="true", CRM_CONNECTOR_ENABLED="true"),
            store_path=self.store_path,
        )
        self.assertTrue(result["dry_run"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_dry_run_preview_of_a_write_never_leaks_the_api_key(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"},
            env=self._env(), store_path=self.store_path,
        )
        dumped = json.dumps(result)
        self.assertNotIn("sk_live_secret1234", dumped)
        self.assertIn("REDACTED", dumped)


class UnknownConnectionOrOperation(CrmCallTestCase):
    @patch("requests.request")
    def test_unknown_connection_is_blocked_without_network(self, mock_request):
        result = crm_call.call_operation(
            "does-not-exist", "list_leads", {}, env=self._env(), store_path=self.store_path,
        )
        self.assertTrue(result["blocked"])
        self.assertIn("ecoloop", result["available_connections"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_unknown_operation_is_blocked_without_network(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "delete_everything", {}, env=self._env(), store_path=self.store_path,
        )
        self.assertTrue(result["blocked"])
        self.assertIn("list_leads", result["available_operations"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_missing_path_param_is_blocked_without_network(self, mock_request):
        result = crm_call.call_operation(
            "ecoloop", "get_lead", {}, env=self._env(), store_path=self.store_path,
        )
        self.assertTrue(result["blocked"])
        mock_request.assert_not_called()


class AuditLogNeverLeaksSecrets(CrmCallTestCase):
    @patch("requests.request")
    def test_write_dry_run_is_audited_without_api_key_or_body(self, mock_request):
        crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"},
            env=self._env(), store_path=self.store_path,
        )
        lines = self._audit_lines()
        self.assertEqual(len(lines), 1)
        rec = lines[0]
        self.assertEqual(rec["connection"], "ecoloop")
        self.assertEqual(rec["operation"], "update_stage")
        self.assertTrue(rec["dry_run"])
        self.assertFalse(rec["executed"])
        dumped = json.dumps(rec)
        self.assertNotIn("sk_live_secret1234", dumped)
        self.assertNotIn("won", dumped)

    @patch("requests.request")
    def test_real_write_is_audited(self, mock_request):
        mock_request.return_value = _fake_response()
        crm_call.call_operation(
            "ecoloop", "update_stage", {"id": "1", "stage": "won"}, dry_run=False,
            env=self._env(HERMES_ALLOW_EXECUTE="true", CRM_CONNECTOR_ENABLED="true"),
            store_path=self.store_path,
        )
        lines = self._audit_lines()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0]["executed"])
        self.assertFalse(lines[0]["dry_run"])

    @patch("requests.request")
    def test_reads_do_not_pollute_the_write_audit_log(self, mock_request):
        mock_request.return_value = _fake_response()
        crm_call.call_operation("ecoloop", "list_leads", {}, env=self._env(), store_path=self.store_path)
        # Reads ARE audited too (crm_connector.read.executed) but under the
        # same log; assert the record correctly says kind=="read".
        lines = self._audit_lines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["kind"], "read")


class CliDryRunProof(CrmCallTestCase):
    """CLI-level proof (argv parsing -> call_operation), mirroring
    dispatch-job's CLI dry-run test."""

    @patch("requests.request")
    def test_cli_write_without_execute_flag_stays_dry_run(self, mock_request):
        argv = [
            "--connection", "ecoloop", "--operation", "update_stage",
            "--param", "id=1", "--param", "stage=won",
        ]
        with patch.dict(os.environ, self._env(), clear=False), \
             patch("connection_store.default_store_path", return_value=self.store_path):
            with patch("builtins.print") as mock_print:
                # A dry-run write result is NOT "blocked", so _cli() returns
                # normally (no SystemExit) - only sys.exit(2) on a blocked result.
                crm_call._cli(argv)
        printed = mock_print.call_args.args[0]
        payload = json.loads(printed)
        self.assertTrue(payload["dry_run"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_cli_execute_flag_alone_without_gate_envs_stays_dry_run(self, mock_request):
        argv = [
            "--connection", "ecoloop", "--operation", "update_stage",
            "--param", "id=1", "--param", "stage=won", "--execute",
        ]
        with patch.dict(os.environ, self._env(), clear=False), \
             patch("connection_store.default_store_path", return_value=self.store_path):
            with patch("builtins.print") as mock_print:
                crm_call._cli(argv)
        printed = mock_print.call_args.args[0]
        payload = json.loads(printed)
        self.assertTrue(payload["dry_run"])
        mock_request.assert_not_called()

    @patch("requests.request")
    def test_cli_execute_with_both_gate_envs_performs_real_call(self, mock_request):
        mock_request.return_value = _fake_response()
        argv = [
            "--connection", "ecoloop", "--operation", "update_stage",
            "--param", "id=1", "--param", "stage=won", "--execute",
        ]
        env = self._env(HERMES_ALLOW_EXECUTE="true", CRM_CONNECTOR_ENABLED="true")
        with patch.dict(os.environ, env, clear=False), \
             patch("connection_store.default_store_path", return_value=self.store_path):
            with patch("builtins.print") as mock_print:
                crm_call._cli(argv)
        printed = mock_print.call_args.args[0]
        payload = json.loads(printed)
        self.assertFalse(payload["dry_run"])
        self.assertTrue(payload["executed"])
        mock_request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
