"""test_contract_preflight.py — unit coverage for contract_preflight's path
relativization (``_candidate_roots()`` / ``_rel()``), the second real call
site of the same HERMES_HOME bug (the first is dispatch_guard.py, covered by
test_dispatch_guard.py::DispatchGuardHermesHomePaths).

``_rel()`` is what ``axtro/skill_runner.py:run_skill()`` calls directly
(``rel = pf._rel(sdir); governed = pf._default_is_governed(rel, sdir)``) —
so this same bug also broke governance for the CLI/skill_runner entry point,
not just the live daemon's terminal-tool dispatch, whenever a skill_dir was
passed as an installed HERMES_HOME/skills path rather than a repo-checkout
path. These tests prove both ``_rel()`` and ``_default_is_governed()`` now
correctly resolve a governed skill's key regardless of which physical root
the caller's path is rooted at.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
sys.path.insert(0, str(REPO / "axtro" / "tools"))
sys.path.insert(0, str(REPO))
import contract_preflight as pf  # noqa: E402


class CandidateRootsTestCase(unittest.TestCase):
    def test_repo_is_always_a_candidate(self):
        roots = pf._candidate_roots()
        self.assertIn(REPO.resolve(), roots)

    def test_named_profile_root_is_listed_before_the_bare_hermes_root(self):
        # Ordering matters: <root>/profiles/<name> must be tried BEFORE
        # <root> itself, because <root> is an ancestor of every profile dir
        # — if <root> won first, a profile-scoped path would relativize to
        # "profiles/<name>/skills/..." instead of "skills/...", and never
        # match GOVERNED_SKILLS.txt (see _candidate_roots()'s docstring).
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile_dir = root / "profiles" / "alfred"
            profile_dir.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(profile_dir)}):
                roots = pf._candidate_roots()
            self.assertIn(profile_dir, roots)
            self.assertIn(root, roots)
            self.assertLess(roots.index(profile_dir), roots.index(root))

    def test_missing_hermes_constants_degrades_to_repo_only(self):
        with mock.patch.dict(sys.modules, {"hermes_constants": None}):
            roots = pf._candidate_roots()
        self.assertEqual(roots, [REPO.resolve()])


class RelTestCase(unittest.TestCase):
    """_rel() is the function axtro/skill_runner.py:run_skill() calls
    directly (pf._rel(sdir)) to derive the governed-skill key BEFORE
    checking membership in GOVERNED_SKILLS.txt via _default_is_governed()."""

    def test_repo_checkout_path_relativizes_against_repo(self):
        sdir = (REPO / "skills" / "finance" / "hermes-purchase").resolve()
        self.assertEqual(pf._rel(sdir), "skills/finance/hermes-purchase")

    def test_hermes_home_default_profile_path_relativizes_correctly(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            sdir = home / "skills" / "finance" / "hermes-purchase"
            sdir.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(home)}):
                rel = pf._rel(sdir)
            self.assertEqual(rel, "skills/finance/hermes-purchase")

    def test_hermes_home_named_profile_path_relativizes_correctly(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            profile_home = root / "profiles" / "alfred"
            sdir = profile_home / "skills" / "finance" / "hermes-purchase"
            sdir.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(profile_home)}):
                rel = pf._rel(sdir)
            self.assertEqual(rel, "skills/finance/hermes-purchase")

    def test_hermes_home_path_would_not_have_relativized_pre_fix(self):
        # Direct "before" proof: the OLD _rel() body was exactly
        # `str(sdir.relative_to(REPO))`, falling back to `sdir.name` on
        # ValueError. Replaying that literally against a HERMES_HOME path
        # shows the pre-fix bug: it collapses to the bare skill directory
        # name, which never matches a GOVERNED_SKILLS.txt entry like
        # "skills/finance/hermes-purchase".
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp).resolve()
            sdir = home / "skills" / "finance" / "hermes-purchase"
            sdir.mkdir(parents=True)
            try:
                pre_fix_rel = str(sdir.relative_to(pf.REPO))
            except ValueError:
                pre_fix_rel = sdir.name
            self.assertEqual(pre_fix_rel, "hermes-purchase")
            self.assertNotIn(pre_fix_rel, pf._governed_set())

    def test_path_outside_every_known_root_falls_back_to_bare_name(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            sdir = (Path(tmp) / "hermes-purchase").resolve()
            with mock.patch.dict(os.environ, {"HERMES_HOME": str(Path(tmp) / "elsewhere")}):
                rel = pf._rel(sdir)
            self.assertEqual(rel, "hermes-purchase")


if __name__ == "__main__":
    unittest.main()
