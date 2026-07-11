"""test_terminal_axtro_governance.py — proves the axtro/dispatch_guard.py hook
wired into ``tools/terminal_tool.terminal_tool()`` actually gates the LIVE
daemon execution path, not just the axtro/skill_runner.py CLI wrapper.

Before this hook existed, a governed skill's script invoked via the generic
``terminal`` tool (exactly what the gateway's own tool-use loop does when the
LLM decides to run a skill) went straight to a backend and spawned a real
subprocess — contract.json was never consulted. These tests exercise the
REAL ``terminal_tool()`` entry point (not axtro/dispatch_guard.py in
isolation — that is covered by axtro/tests/test_dispatch_guard.py) and prove:

  1. A governed-and-disabled skill (the real
     skills/communication/telnyx-voice-sms, which ships with
     ``"enabled": false``) is blocked BEFORE any backend/subprocess exists —
     proven by making ``_get_env_config`` (the first thing terminal_tool()
     calls once past validation) explode if it is ever reached.
  2. An ordinary, ungoverned command is completely unaffected: it runs for
     real, through the real local backend, with the real output.
  3. HERMES_KILL_SWITCH=on stops a governed skill that would otherwise be
     allowed, via this same live path.
  4. A governed skill capped at dry-run by its contract still runs (it is
     not blocked) but with --dry-run forced onto the command — proven by
     letting the real script execute and inspecting its own stdout.
"""
import json
from pathlib import Path
from unittest.mock import patch

from tools.terminal_tool import terminal_tool

REPO = Path(__file__).resolve().parents[2]
TELNYX_SKILL = REPO / "skills" / "communication" / "telnyx-voice-sms"
SAFE_DIAGNOSTIC = REPO / "axtro" / "skill_examples" / "safe-diagnostic"
CHARGE_CUSTOMER = REPO / "axtro" / "skill_examples" / "charge-customer"


def _assert_never_called(*_a, **_kw):
    raise AssertionError(
        "REGRESSION: _get_env_config() was reached — a backend was about to "
        "be selected for a command that Axtro governance should have "
        "blocked before any subprocess could exist."
    )


class TestGovernedSkillBlockedBeforeSpawn:
    """skills/communication/telnyx-voice-sms ships with enabled=false today
    — a real, concrete 'governed-and-disabled skill' with no mocking needed
    for the contract itself."""

    def test_disabled_skill_blocked_before_any_backend_selected(self, monkeypatch):
        assert TELNYX_SKILL.is_dir(), "fixture skill missing from repo"
        # Supply fake creds so the block is unambiguously about enabled=false
        # (R3), not the credentials gate (R7) — both are real blocks, but the
        # task asks specifically to prove the enabled=false case.
        for var in ("TELNYX_API_KEY", "TELNYX_CONNECTION_ID", "TELNYX_INBOX_API_KEY",
                    "TELNYX_PUBLIC_KEY", "TELNYX_NUMBER"):
            monkeypatch.setenv(var, "fake-for-test")

        with patch("tools.terminal_tool._get_env_config", side_effect=_assert_never_called):
            result = json.loads(terminal_tool(
                command="python3 skills/communication/telnyx-voice-sms/scripts/send_sms.py "
                        "--to +16174505166 --text hi --execute",
                workdir=str(REPO),
            ))

        assert result["status"] == "error"
        assert result["exit_code"] == -1
        assert "Axtro governance" in result["error"]
        assert "enabled=false" in result["error"]

    def test_before_this_hook_the_same_command_would_have_reached_the_backend(self):
        """Sanity check on the premise: with the guard disabled (patched to a
        no-op, simulating "before this change"), the exact same command DOES
        reach _get_env_config() — i.e. it would have gone on to spawn a real
        subprocess. This is the concrete "before" half of the before/after
        proof; the test above is the "after" half."""
        with patch("axtro.dispatch_guard.check", return_value=None), \
             patch("tools.terminal_tool._get_env_config", side_effect=_assert_never_called) as mocked:
            # terminal_tool() wraps its whole body in a broad try/except, so
            # the AssertionError from _get_env_config doesn't propagate — it
            # comes back as an error result instead. What matters for this
            # sanity check is simply that _get_env_config *was* reached,
            # which it would not have been had the guard still been active.
            result = json.loads(terminal_tool(
                command="python3 skills/communication/telnyx-voice-sms/scripts/send_sms.py "
                        "--to +16174505166 --text hi --execute",
                workdir=str(REPO),
            ))
            assert mocked.called, (
                "expected _get_env_config to be reached once the guard is disabled "
                "(this is what happened before this fix existed)"
            )
            assert "REGRESSION" in result["error"]


class TestKillSwitch:
    def test_kill_switch_blocks_an_otherwise_allowed_governed_skill(self, monkeypatch):
        assert SAFE_DIAGNOSTIC.is_dir(), "fixture skill missing from repo"
        monkeypatch.setenv("HERMES_KILL_SWITCH", "on")

        with patch("tools.terminal_tool._get_env_config", side_effect=_assert_never_called):
            result = json.loads(terminal_tool(
                command="python3 axtro/skill_examples/safe-diagnostic/scripts/run.py",
                workdir=str(REPO),
            ))

        assert result["status"] == "error"
        assert "KILL SWITCH" in result["error"]

    def test_without_kill_switch_the_same_safe_skill_runs_for_real(self, monkeypatch):
        monkeypatch.delenv("HERMES_KILL_SWITCH", raising=False)
        result = json.loads(terminal_tool(
            command="python3 axtro/skill_examples/safe-diagnostic/scripts/run.py",
            workdir=str(REPO),
        ))
        assert result["exit_code"] == 0
        assert "Axtro governance" not in (result.get("error") or "")


class TestUngovernedCommandsUnaffected:
    def test_ordinary_command_runs_exactly_as_before(self):
        result = json.loads(terminal_tool(
            command="echo axtro-governance-does-not-touch-this",
            workdir=str(REPO),
        ))
        assert result["exit_code"] == 0
        assert "axtro-governance-does-not-touch-this" in result["output"]

    def test_inspecting_a_disabled_governed_skills_files_is_not_blocked(self, monkeypatch):
        # Reading/inspecting the contract or SKILL.md of a disabled skill
        # (cat, ls, grep) must behave identically to any other file read —
        # only directly *executing* the skill's own script is governed.
        for var in ("TELNYX_API_KEY", "TELNYX_CONNECTION_ID", "TELNYX_INBOX_API_KEY",
                    "TELNYX_PUBLIC_KEY", "TELNYX_NUMBER"):
            monkeypatch.setenv(var, "fake-for-test")
        result = json.loads(terminal_tool(
            command="cat skills/communication/telnyx-voice-sms/contract.json",
            workdir=str(REPO),
        ))
        assert result["exit_code"] == 0
        assert "enabled" in result["output"]


class TestDryRunModeForced:
    def test_contract_capped_skill_runs_but_forced_into_dry_run(self):
        """charge-customer is risk_class=financial_sensitive with no
        HERMES_HUMAN_APPROVAL set -> autonomy_core caps it at dry_run. The
        command is NOT blocked (it runs for real, through the real local
        backend) but --dry-run is forced onto it before the subprocess is
        spawned, so the script itself reports DRY-RUN, never a real charge."""
        assert CHARGE_CUSTOMER.is_dir(), "fixture skill missing from repo"
        result = json.loads(terminal_tool(
            command="python3 axtro/skill_examples/charge-customer/scripts/charge.py --execute",
            workdir=str(REPO),
        ))
        assert result["exit_code"] == 0
        payload = json.loads(result["output"])
        assert payload["status"] == "DRY-RUN"
        assert payload["cobranca_real"] is False
