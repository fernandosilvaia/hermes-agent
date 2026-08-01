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

    def test_absolute_path_slug_is_refused_not_written_outside_profiles_root(self):
        # Regression for the critical finding from the 2026-07-31 adversarial
        # review: a company whose slug/name is an absolute path to an
        # already-existing directory (e.g. "/tmp") used to make
        # profile_exists() return True, skipping create_profile() — the only
        # place validate_profile_name() ran — and writing SOUL.md/.env/
        # skills straight into that real path instead of profiles/<slug>/.
        snap = _snapshot()
        snap["company"]["slug"] = str(self.root)  # an absolute path that DOES exist
        with self.assertRaises(bs.BridgeError):
            bs.materialize_profile(snap, config=FAKE_CONFIG)
        self.assertFalse((self.root / "SOUL.md").exists())
        self.assertFalse((self.root / ".env").exists())

    def test_path_traversal_slug_is_refused(self):
        snap = _snapshot()
        snap["company"]["slug"] = "../../etc/cron.d"
        with self.assertRaises(bs.BridgeError):
            bs.materialize_profile(snap, config=FAKE_CONFIG)

    def test_slug_with_slash_is_refused(self):
        snap = _snapshot()
        snap["company"]["slug"] = "empresa/nova"
        with self.assertRaises(bs.BridgeError):
            bs.materialize_profile(snap, config=FAKE_CONFIG)

    def test_reserved_name_slug_is_refused(self):
        snap = _snapshot()
        snap["company"]["slug"] = "root"
        with self.assertRaises(bs.BridgeError):
            bs.materialize_profile(snap, config=FAKE_CONFIG)

    def test_rejected_slug_never_reaches_create_profile_or_credential_fetch(self):
        snap = _snapshot()
        snap["company"]["slug"] = "/etc"
        with mock.patch("hermes_cli.profiles.create_profile") as create_mock, \
             mock.patch("bridge_sync.get_connector_credential") as cred_mock:
            with self.assertRaises(bs.BridgeError):
                bs.materialize_profile(snap, config=FAKE_CONFIG)
        create_mock.assert_not_called()
        cred_mock.assert_not_called()


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


class TestListActiveCompanies(unittest.TestCase):
    def test_queries_telegram_connected_only(self):
        fake_response = mock.Mock()
        fake_response.json.return_value = [{"company_id": "c1"}, {"company_id": "c2"}]
        fake_response.raise_for_status.return_value = None
        with mock.patch.object(bs.httpx, "get", return_value=fake_response) as m:
            result = bs.list_active_companies(config=FAKE_CONFIG)
        _, kwargs = m.call_args
        self.assertEqual(kwargs["params"]["connector_key"], "eq.telegram")
        self.assertEqual(kwargs["params"]["status"], "eq.connected")
        self.assertEqual(kwargs["headers"]["apikey"], "test-service-role")
        self.assertEqual(result, ["c1", "c2"])

    def test_excludes_given_company_ids(self):
        fake_response = mock.Mock()
        fake_response.json.return_value = [{"company_id": "c1"}, {"company_id": "alfred-kings-id"}]
        fake_response.raise_for_status.return_value = None
        with mock.patch.object(bs.httpx, "get", return_value=fake_response):
            result = bs.list_active_companies(config=FAKE_CONFIG, exclude_company_ids={"alfred-kings-id"})
        self.assertEqual(result, ["c1"])
        self.assertNotIn("alfred-kings-id", result)

    def test_dedupes_repeated_company_ids(self):
        fake_response = mock.Mock()
        fake_response.json.return_value = [{"company_id": "c1"}, {"company_id": "c1"}]
        fake_response.raise_for_status.return_value = None
        with mock.patch.object(bs.httpx, "get", return_value=fake_response):
            result = bs.list_active_companies(config=FAKE_CONFIG)
        self.assertEqual(result, ["c1"])


class TestWatchPollDiscover(unittest.TestCase):
    def test_discovers_and_materializes_each_cycle(self):
        with mock.patch("bridge_sync._bridge_config", return_value=FAKE_CONFIG), \
             mock.patch("bridge_sync.list_active_companies", return_value=["c1", "c2"]), \
             mock.patch("bridge_sync.snapshot_company", side_effect=lambda cid, **_: _snapshot(company={"id": cid, "name": cid, "plan_id": "piloto", "slug": cid})), \
             mock.patch("bridge_sync.materialize_profile") as materialize_mock, \
             mock.patch("bridge_sync.time.sleep"):
            bs.watch_poll_discover(iterations=1)
        materialized_ids = {c.args[0]["company"]["id"] for c in materialize_mock.call_args_list}
        self.assertEqual(materialized_ids, {"c1", "c2"})

    def test_excluded_company_never_reaches_materialize(self):
        with mock.patch("bridge_sync._bridge_config", return_value=FAKE_CONFIG), \
             mock.patch("bridge_sync.list_active_companies", return_value=["c1"]) as discover_mock, \
             mock.patch("bridge_sync.snapshot_company", return_value=_snapshot()), \
             mock.patch("bridge_sync.materialize_profile") as materialize_mock, \
             mock.patch("bridge_sync.time.sleep"):
            bs.watch_poll_discover(iterations=1, exclude_company_ids={"excluded-id"})
        # exclusion happens inside list_active_companies itself; confirm the
        # exclude set is actually threaded through to it.
        self.assertEqual(discover_mock.call_args.kwargs["exclude_company_ids"], {"excluded-id"})
        materialize_mock.assert_called_once()

    def test_unchanged_snapshot_is_not_rematerialized(self):
        with mock.patch("bridge_sync._bridge_config", return_value=FAKE_CONFIG), \
             mock.patch("bridge_sync.list_active_companies", return_value=["c1"]), \
             mock.patch("bridge_sync.snapshot_company", return_value=_snapshot()), \
             mock.patch("bridge_sync.materialize_profile") as materialize_mock, \
             mock.patch("bridge_sync.time.sleep"):
            bs.watch_poll_discover(iterations=3)
        materialize_mock.assert_called_once()

    def test_discovery_failure_does_not_crash_the_loop(self):
        with mock.patch("bridge_sync._bridge_config", return_value=FAKE_CONFIG), \
             mock.patch("bridge_sync.list_active_companies", side_effect=RuntimeError("supabase down")), \
             mock.patch("bridge_sync.materialize_profile") as materialize_mock, \
             mock.patch("bridge_sync.time.sleep"):
            bs.watch_poll_discover(iterations=2)  # must not raise
        materialize_mock.assert_not_called()

    def test_one_company_failing_does_not_block_the_others(self):
        def _snapshot_side_effect(cid, **_):
            if cid == "broken":
                raise RuntimeError("network blip")
            return _snapshot(company={"id": cid, "name": cid, "plan_id": "piloto", "slug": cid})

        with mock.patch("bridge_sync._bridge_config", return_value=FAKE_CONFIG), \
             mock.patch("bridge_sync.list_active_companies", return_value=["broken", "c2"]), \
             mock.patch("bridge_sync.snapshot_company", side_effect=_snapshot_side_effect), \
             mock.patch("bridge_sync.materialize_profile") as materialize_mock, \
             mock.patch("bridge_sync.time.sleep"):
            bs.watch_poll_discover(iterations=1)
        materialized_ids = {c.args[0]["company"]["id"] for c in materialize_mock.call_args_list}
        self.assertEqual(materialized_ids, {"c2"})


class TestRunForeverInBackground(unittest.TestCase):
    def test_restarts_watch_poll_discover_after_unexpected_exception(self):
        calls = {"n": 0}

        def _flaky(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom")
            return None  # second call "succeeds" (returns, ending the while True loop)

        with mock.patch("bridge_sync.watch_poll_discover", side_effect=_flaky) as watch_mock, \
             mock.patch("bridge_sync.time.sleep"):
            bs.run_forever_in_background(interval_seconds=1)
        self.assertEqual(watch_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main()
