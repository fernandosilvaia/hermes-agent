"""test_dispatch_guard.py — PROOF that axtro/dispatch_guard.py (the hook wired
into tools/terminal_tool.terminal_tool) makes the same governance decisions as
the already-tested autonomy_core / contract_preflight stack, and that it does
NOT add friction to anything that isn't a direct invocation of a governed
skill's own script.

Two layers of proof:
  1. Synthetic fixtures (injected via the ``governed_roots`` override) — full
     control over the contract, so every branch (block/dry_run/allow/kill
     switch) is exercised deterministically.
  2. The REAL repo state (real GOVERNED_SKILLS.txt, real contract.json files)
     — ``skills/communication/telnyx-voice-sms`` ships with
     ``"enabled": false`` today, so it doubles as a live, concrete
     "governed-and-disabled skill" fixture without needing any mocking.
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
sys.path.insert(0, str(REPO / "axtro" / "tools"))
sys.path.insert(0, str(REPO))
import dispatch_guard as dg  # noqa: E402
import contract_preflight as pf  # noqa: E402


class DispatchGuardFixtures(unittest.TestCase):
    """Synthetic governed-skill fixtures, fully isolated from the real repo."""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _make_skill(self, name, contract):
        d = self.root / name
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "run.py").write_text("print('ran')\n", encoding="utf-8")
        (d / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
        return d

    def _base_contract(self, **over):
        c = {
            "id": "fixture", "enabled": True, "production_ready": True,
            "activation_stage": "production", "autonomy_ring": 1,
            "stop_conditions": ["manual"], "telemetry_events": ["ev"],
            "credentials": [],
        }
        c.update(over)
        return c

    # ── ungoverned / non-matching commands: zero friction ─────────────────
    def test_ungoverned_command_returns_none(self):
        self.assertIsNone(dg.check("echo hello", workdir=str(self.root)))

    def test_unrecognized_interpreter_returns_none(self):
        # make binary invocations (git, npm, ...) are never matched.
        self.assertIsNone(dg.check("git status", workdir=str(self.root)))

    def test_mentioning_governed_path_without_executing_is_not_matched(self):
        d = self._make_skill("governed_disabled", self._base_contract(enabled=False))
        roots = {"governed_disabled": d}
        # cat/ls/grep are not recognized interpreters — inspecting a governed
        # skill's files must never be blocked.
        self.assertIsNone(dg.check(f"cat {d}/contract.json", workdir=str(self.root),
                                    governed_roots=roots))
        self.assertIsNone(dg.check(f"ls {d}/scripts", workdir=str(self.root),
                                    governed_roots=roots))

    # ── governed + blocked ─────────────────────────────────────────────────
    def test_governed_disabled_skill_blocks(self):
        d = self._make_skill("governed_disabled", self._base_contract(enabled=False))
        roots = {"governed_disabled": d}
        r = dg.check("python3 scripts/run.py", workdir=str(d), governed_roots=roots)
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "block")
        self.assertEqual(r["mode"], "blocked")
        self.assertIn("enabled", r["message"])

    def test_governed_sensitive_skill_missing_contract_blocks(self):
        # No contract.json + a source marker (import subprocess) that makes
        # contract_guard.is_sensitive_skill() classify it as sensitive (R1):
        # legacy sensitive skills without a contract are hard-blocked, not
        # just limited to dry-run (that's R1b, for non-sensitive legacy).
        d = self.root / "governed_legacy"
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "run.py").write_text(
            "import subprocess  # sensivel\nprint('ran')\n", encoding="utf-8")
        roots = {"governed_legacy": d}
        r = dg.check("python3 scripts/run.py", workdir=str(d), governed_roots=roots)
        self.assertEqual(r["action"], "block")

    def test_governed_nonsensitive_skill_missing_contract_is_dry_run_only(self):
        # R1b: missing contract + not flagged sensitive -> dry-run only, not
        # a hard block. Real action is still refused either way.
        d = self.root / "governed_legacy_plain"
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "run.py").write_text("print('ran')\n", encoding="utf-8")
        roots = {"governed_legacy_plain": d}
        r = dg.check("python3 scripts/run.py", workdir=str(d), governed_roots=roots)
        self.assertEqual(r["action"], "dry_run")

    # ── kill switch ─────────────────────────────────────────────────────────
    def test_kill_switch_blocks_even_a_normally_allowed_skill(self):
        d = self._make_skill("governed_ok", self._base_contract())
        roots = {"governed_ok": d}
        env = {"HERMES_KILL_SWITCH": "on"}
        r = dg.check("python3 scripts/run.py", workdir=str(d), env=env, governed_roots=roots)
        self.assertEqual(r["action"], "block")
        self.assertEqual(r["mode"], "killed")

    def test_without_kill_switch_same_skill_is_allowed(self):
        d = self._make_skill("governed_ok", self._base_contract())
        roots = {"governed_ok": d}
        r = dg.check("python3 scripts/run.py", workdir=str(d), env={}, governed_roots=roots)
        self.assertEqual(r["action"], "allow")

    # ── dry-run mode rewrites only the matched segment ─────────────────────
    # risk_class=financial_sensitive with no HERMES_HUMAN_APPROVAL forces
    # dry_run regardless of production_ready (mirrors the real
    # axtro/skill_examples/charge-customer fixture).
    def _needs_approval_contract(self, **over):
        return self._base_contract(risk_class="financial_sensitive", **over)

    def test_dry_run_mode_injects_flag_into_matched_segment_only(self):
        d = self._make_skill("governed_needs_approval", self._needs_approval_contract())
        roots = {"governed_needs_approval": d}
        r = dg.check("echo before && python3 scripts/run.py --execute && echo after",
                      workdir=str(d), env={}, governed_roots=roots)
        self.assertEqual(r["action"], "dry_run")
        self.assertEqual(
            r["command"],
            "echo before && python3 scripts/run.py --execute --dry-run && echo after",
        )

    def test_dry_run_mode_does_not_duplicate_existing_flag(self):
        d = self._make_skill("governed_needs_approval", self._needs_approval_contract())
        roots = {"governed_needs_approval": d}
        r = dg.check("python3 scripts/run.py --dry-run", workdir=str(d), env={},
                      governed_roots=roots)
        self.assertEqual(r["action"], "dry_run")
        self.assertEqual(r["command"].count("--dry-run"), 1)

    # ── direct execution (no interpreter prefix) ────────────────────────────
    def test_direct_execution_without_interpreter_is_matched(self):
        d = self._make_skill("governed_disabled", self._base_contract(enabled=False))
        roots = {"governed_disabled": d}
        r = dg.check("./scripts/run.py", workdir=str(d), governed_roots=roots)
        self.assertEqual(r["action"], "block")

    # ── malformed command never raises, never blocks something unrelated ───
    def test_malformed_quoting_does_not_raise_and_is_unmatched(self):
        r = dg.check('python3 "unterminated', workdir=str(self.root))
        self.assertIsNone(r)


class DispatchGuardRealRepoState(unittest.TestCase):
    """Uses the REAL axtro/GOVERNED_SKILLS.txt + real contract.json files —
    no mocking. telnyx-voice-sms ships with enabled=false today; this is the
    concrete "governed-and-disabled skill" the task description asks for.
    """

    def _telnyx_creds_env(self):
        # Supply fake credentials so the R7 (missing creds) gate doesn't mask
        # the R3 (enabled=false) gate we're specifically proving here.
        return {
            "TELNYX_API_KEY": "fake", "TELNYX_CONNECTION_ID": "fake",
            "TELNYX_INBOX_API_KEY": "fake", "TELNYX_PUBLIC_KEY": "fake",
            "TELNYX_NUMBER": "fake",
        }

    def test_real_telnyx_skill_is_blocked_because_disabled(self):
        cmd = ("python3 skills/communication/telnyx-voice-sms/scripts/send_sms.py "
               "--to +16174505166 --text hi --execute")
        r = dg.check(cmd, workdir=str(REPO), env=self._telnyx_creds_env())
        self.assertIsNotNone(r, "expected the real telnyx-voice-sms skill to be recognized as governed")
        self.assertEqual(r["action"], "block")
        self.assertIn("enabled=false", r["message"])

    def test_real_attom_property_skill_is_governed_and_allowed_when_enabled(self):
        """Prova end-to-end (GOVERNED_SKILLS.txt + contract.json reais) que a
        skill imobiliária do Alfred Kings está registrada na governança —
        não só coberta pelos próprios testes unitários dela. Ativada
        2026-07-26 (enabled=true, risk_class=safe) por decisão do Fernando,
        então o caminho real hoje é "allow" com credencial presente, não
        mais bloqueado por enabled=false."""
        cmd = ("python3 skills/real-estate/attom-property/scripts/attom_call.py "
               "--kind detail --address1 x --address2 y")
        r = dg.check(cmd, workdir=str(REPO), env={"ATTOM_API_KEY": "fake"})
        self.assertIsNotNone(r, "expected the real attom-property skill to be recognized as governed")
        self.assertEqual(r["action"], "allow")

    def test_real_attom_property_skill_blocked_without_credential(self):
        """Mesma skill real, sem ATTOM_API_KEY no env — fail-closed (R7),
        nunca chama a API sem credencial."""
        cmd = ("python3 skills/real-estate/attom-property/scripts/attom_call.py "
               "--kind detail --address1 x --address2 y")
        r = dg.check(cmd, workdir=str(REPO), env={})
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "block")
        self.assertIn("ATTOM_API_KEY", r["message"])

    def test_real_safe_diagnostic_example_is_allowed(self):
        cmd = "python3 axtro/skill_examples/safe-diagnostic/scripts/run.py"
        r = dg.check(cmd, workdir=str(REPO), env={})
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "allow")
        self.assertEqual(r["mode"], "production")

    def test_reading_the_disabled_skills_contract_is_not_blocked(self):
        # A human/agent inspecting the contract must never be treated as
        # "running" the skill.
        cmd = "cat skills/communication/telnyx-voice-sms/contract.json"
        r = dg.check(cmd, workdir=str(REPO), env=self._telnyx_creds_env())
        self.assertIsNone(r)

    def test_real_crm_connector_write_op_is_recognized_and_gated(self):
        # skills/operations/crm-connector (new skill, this change) also
        # ships enabled=false today - same concrete proof shape as the
        # telnyx test above, for a DIFFERENT governed skill, confirming the
        # PR #10 chokepoint recognizes it too (not just the fixtures it was
        # written against). crm_call.py has zero declared `credentials` (its
        # secrets live in a HERMES_HOME connection-store file, not env vars,
        # see contract.json's notes), so no fake-creds env is needed here -
        # this isolates the R3 (enabled=false) gate cleanly.
        cmd = (
            "python3 skills/operations/crm-connector/scripts/crm_call.py "
            "--connection ecoloop --operation update_stage "
            "--param id=1 --param stage=won --execute"
        )
        r = dg.check(cmd, workdir=str(REPO), env={})
        self.assertIsNotNone(r, "expected the real crm-connector skill to be recognized as governed")
        self.assertEqual(r["action"], "block")
        self.assertIn("enabled=false", r["message"])

    def test_real_crm_connector_read_op_is_also_recognized(self):
        # The chokepoint gates the SCRIPT invocation, not the individual
        # operation - a read-shaped CLI call is matched and blocked exactly
        # like the write one above, because the skill itself is
        # enabled=false. (crm_call.py's OWN read/write distinction, which
        # lets reads through freely once the skill is enabled, is proven
        # separately in skills/operations/crm-connector/tests/test_crm_call.py -
        # this test is only about the outer governance chokepoint.)
        cmd = "python3 skills/operations/crm-connector/scripts/crm_call.py --connection ecoloop --operation list_leads"
        r = dg.check(cmd, workdir=str(REPO), env={})
        self.assertIsNotNone(r)
        self.assertEqual(r["action"], "block")

    def test_reading_the_crm_connector_contract_is_not_blocked(self):
        cmd = "cat skills/operations/crm-connector/contract.json"
        r = dg.check(cmd, workdir=str(REPO), env={})
        self.assertIsNone(r)


class DispatchGuardHermesHomePaths(unittest.TestCase):
    """PROOF that the P0 gap is closed: a governed skill invoked from a path
    shaped like the REAL Docker production layout — ``HERMES_HOME/skills/...``
    (default profile) or ``HERMES_HOME/profiles/<name>/skills/...`` (a named
    profile) — physically copied there by ``tools/skills_sync.py`` at
    container boot, is now recognized and governed exactly like the repo
    checkout path already was.

    Uses a REAL governed rel from the actual ``axtro/GOVERNED_SKILLS.txt``
    (``skills/finance/hermes-purchase``) but a SYNTHETIC, disabled
    ``contract.json`` at a temp location that is NOT the repo checkout — so
    a match can only happen via the new HERMES_HOME-aware root, never via
    the pre-existing ``REPO`` root (which points at a completely different
    absolute path, the real repo copy of this skill).

    Each test also explicitly replays the OLD (pre-fix) single-root,
    REPO-only lookup against the exact same command/workdir and asserts it
    returns ``None`` — i.e. this is the concrete "would have silently
    passed through before" case the task asked to prove, not vacuous new
    coverage.
    """

    GOVERNED_REL = "skills/finance/hermes-purchase"

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name).resolve()

    def tearDown(self):
        self._tmp.cleanup()

    def _seed_disabled_skill(self, root: Path, rel: str = None) -> Path:
        """Write a governed-and-disabled skill fixture under *root*/*rel*
        (default: GOVERNED_REL), mirroring exactly what tools/skills_sync.py
        physically produces under HERMES_HOME at container boot."""
        rel = rel or self.GOVERNED_REL
        d = root / rel
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "run.py").write_text("print('ran')\n", encoding="utf-8")
        contract = {
            "id": "hermes-purchase-fixture", "enabled": False, "production_ready": True,
            "activation_stage": "production", "autonomy_ring": 1,
            "stop_conditions": ["manual"], "telemetry_events": ["ev"],
            "credentials": [],
        }
        (d / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
        return d

    def _assert_would_not_have_matched_pre_fix(self, command: str, workdir: str):
        """Replays the OLD _governed_roots() shape ({rel: single REPO/rel
        Path}, exactly what dispatch_guard.py computed before this fix) and
        confirms the exact same command/workdir would have returned None —
        i.e. this specific case would have silently passed through as
        ungoverned prior to this change."""
        pre_fix_roots = {rel: (dg.REPO / rel).resolve() for rel in pf._governed_set()}
        pre_fix_match = dg._match_governed_skill(command, workdir, governed_roots=pre_fix_roots)
        self.assertIsNone(
            pre_fix_match,
            "expected the pre-fix, REPO-only root lookup to MISS this HERMES_HOME-shaped "
            "path (proving this test exercises the actual gap) — it unexpectedly matched, "
            "so this fixture isn't isolated from the repo checkout as intended",
        )

    # ── default profile: HERMES_HOME/skills/<rel> ──────────────────────────
    def test_default_profile_hermes_home_skill_path_is_blocked(self):
        skill_dir = self._seed_disabled_skill(self.tmp)
        command = "python3 scripts/run.py"

        self._assert_would_not_have_matched_pre_fix(command, str(skill_dir))

        with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.tmp)}):
            r = dg.check(command, workdir=str(skill_dir))
        self.assertIsNotNone(
            r, "governed skill under HERMES_HOME/skills/... was not recognized — "
               "the exact production gap this fix closes")
        self.assertEqual(r["action"], "block")
        self.assertEqual(r["mode"], "blocked")
        self.assertEqual(r["skill"], self.GOVERNED_REL)
        self.assertIn("enabled", r["message"])

    # ── named profile: HERMES_HOME/profiles/<name>/skills/<rel> ────────────
    def test_named_profile_hermes_home_skill_path_is_blocked(self):
        profile_home = self.tmp / "profiles" / "alfred"
        profile_home.mkdir(parents=True)
        skill_dir = self._seed_disabled_skill(profile_home)
        command = "python3 scripts/run.py"

        self._assert_would_not_have_matched_pre_fix(command, str(skill_dir))

        with mock.patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
            r = dg.check(command, workdir=str(skill_dir))
        self.assertIsNotNone(
            r, "governed skill under HERMES_HOME/profiles/<name>/skills/... was not "
               "recognized — the named-profile shape of the same production gap")
        self.assertEqual(r["action"], "block")
        self.assertEqual(r["mode"], "blocked")
        self.assertEqual(r["skill"], self.GOVERNED_REL)

    # ── still fails open / no over-matching ─────────────────────────────────
    def test_path_outside_any_known_root_is_still_unmatched(self):
        # A skill-shaped tree that sits under neither REPO, the current
        # HERMES_HOME, nor any named profile must still pass through
        # unaffected — this fix must not turn into "match anything that
        # looks like a governed skill anywhere on disk".
        stray_root = self.tmp / "not_a_hermes_home"
        stray_root.mkdir()
        skill_dir = self._seed_disabled_skill(stray_root)
        # HERMES_HOME points elsewhere entirely, not at stray_root.
        other_home = self.tmp / "actual_home"
        other_home.mkdir()
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(other_home)}):
            r = dg.check("python3 scripts/run.py", workdir=str(skill_dir))
        self.assertIsNone(r)

    def test_inspecting_hermes_home_skill_files_without_executing_is_not_matched(self):
        skill_dir = self._seed_disabled_skill(self.tmp)
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.tmp)}):
            r = dg.check(f"cat {skill_dir}/contract.json", workdir=str(skill_dir))
        self.assertIsNone(r)

    def test_ungoverned_skill_under_hermes_home_is_not_matched(self):
        # A directory under HERMES_HOME/skills that is NOT in
        # GOVERNED_SKILLS.txt must remain pass-through, same as it always
        # has been for the repo-checkout root.
        skill_dir = self._seed_disabled_skill(self.tmp, rel="skills/native/not-governed")
        with mock.patch.dict(os.environ, {"HERMES_HOME": str(self.tmp)}):
            r = dg.check("python3 scripts/run.py", workdir=str(skill_dir))
        self.assertIsNone(r)


if __name__ == "__main__":
    unittest.main()
