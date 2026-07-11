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
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
sys.path.insert(0, str(REPO))
import dispatch_guard as dg  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
