"""Prova o materializador da ponte (axtro/bridge_sync.py, Fase 3/4 do plano
multi-tenant): geração de SOUL.md/.env/.skills_allowlist a partir de um
snapshot mockado (nunca bate na rede real), idempotência, e a regra de nunca
materializar sobre o perfil 'default'."""
import json
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bridge_sync as bs


FAKE_CONFIG = {
    "axtro_agent_url": "https://agent.axtroai.com",
    "bridge_key": "test-bridge-key",
    "supabase_url": "https://fake.supabase.co",
    "service_role_key": "test-service-role",
}


def _snapshot(**over):
    base = {
        "company": {"id": "11111111-1111-1111-1111-111111111111", "name": "Empresa Teste", "plan_id": "piloto", "slug": "empresa-teste"},
        "identity": {"name": "Atlas", "role": "Agente operacional", "soul": "Ajudar de verdade.",
                     "personality": "Direta.", "culture": "Qualidade.", "voice": "Clara.",
                     "non_negotiables": "Nunca agir sem aprovação em coisa sensível."},
        "goals": [{"title": "Responder rápido", "status": "ativa"}],
        "memoryItems": [{"content": "Cliente prefere respostas curtas."}],
        "skills": [],
        "connectors": [{"connector_key": "telegram", "status": "connected", "connected_at": "2026-01-01"}],
    }
    base.update(over)
    return base


class TestSnapshotAndCredential(unittest.TestCase):
    def test_snapshot_company_calls_correct_url_and_headers(self):
        fake_response = mock.Mock()
        fake_response.status_code = 200
        fake_response.json.return_value = _snapshot()
        fake_response.raise_for_status.return_value = None
        with mock.patch.object(bs.httpx, "get", return_value=fake_response) as m:
            result = bs.snapshot_company("abc-123", config=FAKE_CONFIG)
        m.assert_called_once_with(
            "https://agent.axtroai.com/api/agent-context/abc-123",
            headers={"Authorization": "Bearer test-bridge-key"},
            timeout=20,
        )
        self.assertEqual(result["company"]["name"], "Empresa Teste")

    def test_snapshot_company_404_raises_bridge_error(self):
        fake_response = mock.Mock()
        fake_response.status_code = 404
        with mock.patch.object(bs.httpx, "get", return_value=fake_response):
            with self.assertRaises(bs.BridgeError):
                bs.snapshot_company("does-not-exist", config=FAKE_CONFIG)

    def test_get_connector_credential_posts_rpc_with_service_role_only(self):
        fake_response = mock.Mock()
        fake_response.json.return_value = "telnyx-secret-value"
        fake_response.raise_for_status.return_value = None
        with mock.patch.object(bs.httpx, "post", return_value=fake_response) as m:
            value = bs.get_connector_credential("abc-123", "telegram", config=FAKE_CONFIG)
        _, kwargs = m.call_args
        self.assertEqual(kwargs["headers"]["apikey"], "test-service-role")
        self.assertNotIn("anon", kwargs["headers"]["apikey"])
        self.assertEqual(kwargs["json"], {"p_company_id": "abc-123", "p_connector_key": "telegram"})
        self.assertEqual(value, "telnyx-secret-value")

    def test_get_connector_credential_null_returns_none(self):
        fake_response = mock.Mock()
        fake_response.json.return_value = None
        fake_response.raise_for_status.return_value = None
        with mock.patch.object(bs.httpx, "post", return_value=fake_response):
            value = bs.get_connector_credential("abc-123", "telegram", config=FAKE_CONFIG)
        self.assertIsNone(value)


class TestMaterializeProfile(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self._patches = [
            mock.patch("bridge_sync.get_connector_credential", return_value="telegram-token-XYZ"),
            mock.patch("bridge_sync.sync_profile_skills", return_value={"returncode": 0, "stdout": "", "stderr": ""}),
            mock.patch("hermes_cli.profiles._get_default_hermes_home", return_value=self.root),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self._tmp.cleanup()

    def test_materialize_creates_soul_env_and_allowlist(self):
        profile_dir = bs.materialize_profile(_snapshot(), config=FAKE_CONFIG)

        soul = (profile_dir / "SOUL.md").read_text(encoding="utf-8")
        self.assertIn("Empresa Teste", soul)
        self.assertIn("Ajudar de verdade.", soul)

        env_content = (profile_dir / ".env").read_text(encoding="utf-8")
        self.assertIn("TELEGRAM_BOT_TOKEN=telegram-token-XYZ", env_content)

        # snapshot só tem "telegram" conectado, que não libera skill extra
        # (é adaptador de plataforma, não skill) — só a base entra.
        allowlist = (profile_dir / "skills" / ".skills_allowlist").read_text(encoding="utf-8")
        self.assertIn("research", allowlist)
        self.assertNotIn("google-workspace-axtro", allowlist)
        self.assertNotIn("ask-vps-hermes", allowlist)

        memory = (profile_dir / "memories" / "MEMORY.md").read_text(encoding="utf-8")
        self.assertIn("Responder rápido", memory)
        self.assertIn("Cliente prefere respostas curtas.", memory)

    def test_materialize_is_idempotent_second_call_same_content(self):
        profile_dir_1 = bs.materialize_profile(_snapshot(), config=FAKE_CONFIG)
        soul_1 = (profile_dir_1 / "SOUL.md").read_text(encoding="utf-8")
        profile_dir_2 = bs.materialize_profile(_snapshot(), config=FAKE_CONFIG)
        soul_2 = (profile_dir_2 / "SOUL.md").read_text(encoding="utf-8")
        self.assertEqual(soul_1, soul_2)
        self.assertEqual(profile_dir_1, profile_dir_2)

    def test_connected_google_connector_unlocks_generic_skill_never_axtro_variant(self):
        snap = _snapshot(connectors=[{"connector_key": "google", "status": "connected", "connected_at": "2026-01-01"}])
        profile_dir = bs.materialize_profile(snap, config=FAKE_CONFIG)
        allowlist = (profile_dir / "skills" / ".skills_allowlist").read_text(encoding="utf-8")
        self.assertIn("google-workspace", allowlist)
        self.assertNotIn("google-workspace-axtro", allowlist)

    def test_unmapped_connector_is_skipped_not_fatal(self):
        snap = _snapshot(connectors=[{"connector_key": "google", "status": "connected", "connected_at": "2026-01-01"}])
        profile_dir = bs.materialize_profile(snap, config=FAKE_CONFIG)
        env_content = (profile_dir / ".env").read_text(encoding="utf-8")
        self.assertEqual(env_content, "")

    def test_disconnected_connector_never_gets_credential_fetched(self):
        snap = _snapshot(connectors=[{"connector_key": "telegram", "status": "disconnected", "connected_at": None}])
        with mock.patch("bridge_sync.get_connector_credential") as cred_mock:
            bs.materialize_profile(snap, config=FAKE_CONFIG)
        cred_mock.assert_not_called()

    def test_slug_normalizing_to_default_is_refused(self):
        snap = _snapshot()
        snap["company"]["slug"] = "Default"
        with self.assertRaises(bs.BridgeError):
            bs.materialize_profile(snap, config=FAKE_CONFIG)


class TestUsageSnapshots(unittest.TestCase):
    def test_write_usage_snapshot_adds_deltas_to_current_state(self):
        get_resp = mock.Mock()
        get_resp.json.return_value = [{"llm_usd_spent": 1.5, "voice_minutes_used": 2.0, "tasks_executed": 3}]
        get_resp.raise_for_status.return_value = None
        post_resp = mock.Mock()
        post_resp.raise_for_status.return_value = None

        with mock.patch.object(bs.httpx, "get", return_value=get_resp), \
             mock.patch.object(bs.httpx, "post", return_value=post_resp) as post_mock:
            bs.write_usage_snapshot(
                "company-1", tasks_executed_delta=2, llm_usd_spent_delta=0.25,
                voice_minutes_used_delta=1.0, config=FAKE_CONFIG,
            )

        _, kwargs = post_mock.call_args
        self.assertEqual(kwargs["json"]["tasks_executed"], 5)
        self.assertAlmostEqual(kwargs["json"]["llm_usd_spent"], 1.75)
        self.assertAlmostEqual(kwargs["json"]["voice_minutes_used"], 3.0)
        self.assertEqual(kwargs["json"]["company_id"], "company-1")
        self.assertIn("merge-duplicates", kwargs["headers"]["Prefer"])

    def test_write_usage_snapshot_defaults_to_zero_when_no_row_exists(self):
        get_resp = mock.Mock()
        get_resp.json.return_value = []
        get_resp.raise_for_status.return_value = None
        post_resp = mock.Mock()
        post_resp.raise_for_status.return_value = None

        with mock.patch.object(bs.httpx, "get", return_value=get_resp), \
             mock.patch.object(bs.httpx, "post", return_value=post_resp) as post_mock:
            bs.write_usage_snapshot("company-new", tasks_executed_delta=1, config=FAKE_CONFIG)

        self.assertEqual(post_mock.call_args.kwargs["json"]["tasks_executed"], 1)

    def test_usage_batcher_accumulates_and_flushes_once_per_company(self):
        batcher = bs.UsageBatcher()
        batcher.add("company-1", tasks_executed=1, llm_usd_spent=0.1)
        batcher.add("company-1", tasks_executed=1, llm_usd_spent=0.2)
        batcher.add("company-2", voice_minutes_used=5.0)

        with mock.patch("bridge_sync.write_usage_snapshot") as write_mock:
            batcher.flush(config=FAKE_CONFIG)

        self.assertEqual(write_mock.call_count, 2)
        calls_by_company = {c.args[0]: c.kwargs for c in write_mock.call_args_list}
        self.assertEqual(calls_by_company["company-1"]["tasks_executed_delta"], 2)
        self.assertAlmostEqual(calls_by_company["company-1"]["llm_usd_spent_delta"], 0.3)
        self.assertAlmostEqual(calls_by_company["company-2"]["voice_minutes_used_delta"], 5.0)

    def test_usage_batcher_flush_is_empty_after_success(self):
        batcher = bs.UsageBatcher()
        batcher.add("company-1", tasks_executed=1)
        with mock.patch("bridge_sync.write_usage_snapshot"):
            batcher.flush(config=FAKE_CONFIG)
        with mock.patch("bridge_sync.write_usage_snapshot") as write_mock:
            batcher.flush(config=FAKE_CONFIG)
        write_mock.assert_not_called()

    def test_usage_batcher_keeps_deltas_on_write_failure_for_next_flush(self):
        batcher = bs.UsageBatcher()
        batcher.add("company-1", tasks_executed=3)
        with mock.patch("bridge_sync.write_usage_snapshot", side_effect=RuntimeError("network down")):
            batcher.flush(config=FAKE_CONFIG)
        with mock.patch("bridge_sync.write_usage_snapshot") as write_mock:
            batcher.flush(config=FAKE_CONFIG)
        write_mock.assert_called_once()
        self.assertEqual(write_mock.call_args.kwargs["tasks_executed_delta"], 3)


if __name__ == "__main__":
    unittest.main()
