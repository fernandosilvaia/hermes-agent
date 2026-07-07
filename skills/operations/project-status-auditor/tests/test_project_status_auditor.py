"""
Testes do project_status_auditor. Sem rede; git mockado na maioria dos casos.

    python -m unittest discover -s tests
    # ou: pytest tests/
"""

import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import project_status_auditor as psa  # noqa: E402


def fake_git(dirty=False, ahead=0, has_upstream=True,
             branch="main", last="2026-07-05T10:00:00+00:00"):
    def _f(path, *args):
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return branch
        if args[0] == "status":
            return "M x.txt" if dirty else ""
        if args[0] == "log":
            if last is None:
                raise RuntimeError("sem commits")
            return last
        if args[0] == "rev-list":
            if not has_upstream:
                raise RuntimeError("no upstream configured")
            return f"0\t{ahead}"  # behind<TAB>ahead
        raise RuntimeError(f"git inesperado: {args}")
    return _f


class TestAuditRepo(unittest.TestCase):
    @mock.patch("project_status_auditor._git")
    def test_repo_limpo_sem_flags(self, mg):
        mg.side_effect = fake_git(dirty=False, ahead=0, has_upstream=True)
        info = psa.audit_repo("/x/projeto")
        self.assertEqual(info["flags"], [])
        self.assertFalse(info["dirty"])

    @mock.patch("project_status_auditor._git")
    def test_uncommitted(self, mg):
        mg.side_effect = fake_git(dirty=True)
        info = psa.audit_repo("/x/projeto")
        self.assertIn("uncommitted", info["flags"])

    @mock.patch("project_status_auditor._git")
    def test_nao_pushado(self, mg):
        mg.side_effect = fake_git(ahead=3)
        info = psa.audit_repo("/x/projeto")
        self.assertIn("nao_pushado", info["flags"])
        self.assertEqual(info["ahead"], 3)

    @mock.patch("project_status_auditor._git")
    def test_sem_upstream(self, mg):
        mg.side_effect = fake_git(has_upstream=False)
        info = psa.audit_repo("/x/projeto")
        self.assertIn("sem_upstream", info["flags"])
        self.assertIsNone(info["ahead"])

    @mock.patch("project_status_auditor._git")
    def test_parado(self, mg):
        mg.side_effect = fake_git(last="2026-01-01T10:00:00+00:00")
        info = psa.audit_repo("/x/projeto", stale_days=7)
        self.assertIn("parado", info["flags"])
        self.assertGreater(info["age_days"], 7)

    @mock.patch("project_status_auditor._git")
    def test_detached_head(self, mg):
        mg.side_effect = fake_git(branch="HEAD")
        info = psa.audit_repo("/x/projeto")
        self.assertIn("detached_head", info["flags"])

    @mock.patch("project_status_auditor._git", side_effect=RuntimeError("not a repo"))
    def test_erro_git(self, _mg):
        info = psa.audit_repo("/x/naorepo")
        self.assertIn("erro", info["flags"])
        self.assertIn("error", info)


class TestFindRepos(unittest.TestCase):
    def test_encontra_repos_por_subpasta(self):
        with tempfile.TemporaryDirectory() as root:
            for name in ("a", "b"):
                os.makedirs(os.path.join(root, name, ".git"))
            os.makedirs(os.path.join(root, "nao-repo"))  # sem .git
            repos = psa.find_repos([root])
            nomes = sorted(os.path.basename(p) for p in repos)
            self.assertEqual(nomes, ["a", "b"])

    def test_raiz_que_e_o_proprio_repo(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, ".git"))
            repos = psa.find_repos([root])
            self.assertEqual(repos, [root])

    def test_raiz_inexistente_ignorada(self):
        self.assertEqual(psa.find_repos(["/caminho/que/nao/existe"]), [])


class TestAsText(unittest.TestCase):
    def test_texto_lista_atencao_e_ok(self):
        data = {
            "total": 2, "needs_attention": 1,
            "repos": [
                {"name": "ok-repo", "flags": []},
                {"name": "sujo", "flags": ["uncommitted"], "branch": "main"},
            ],
        }
        txt = psa.as_text(data)
        self.assertIn("ok-repo", txt)
        self.assertIn("sujo", txt)
        self.assertIn("uncommitted", txt)


if __name__ == "__main__":
    unittest.main()
