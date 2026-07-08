"""test_autonomy_core.py — Provas do Autonomy Core (rings + classes de risco +
kill switch + logs), usando o executor oficial `skill_runner.run_skill`.

Cada prova usa efeito observável real (script escreve marcador) e/ou um `spawn`
que LEVANTA se chamado — para provar que o processo não é criado quando bloqueado.

Prova os 5 critérios pedidos:
  1. skill segura roda
  2. skill sensível sem contrato bloqueia
  3. production_sensitive exige gate
  4. kill switch bloqueia tudo
  5. execução direta de skill sensível não faz ação real
+ logs de execução são gravados e há relatório.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
import skill_runner as sr  # noqa: E402

EX = REPO / "axtro" / "skill_examples"


def raising_spawn(*a, **k):
    raise AssertionError("REGRESSÃO: script spawned indevidamente: {}".format(a[0] if a else a))


class _Rec:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.run(cmd, **kw)


class AutonomyCoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.logf = self.tmp / "exec.jsonl"

    def tearDown(self):
        self._tmp.cleanup()

    # ── 1. skill SEGURA roda sozinha ─────────────────────────────────────
    def test_safe_skill_runs(self):
        marker = self.tmp / "safe.json"
        rec = _Rec()
        r = sr.run_skill(EX / "safe-diagnostic", ["scripts/run.py"],
                         env={"HERMES_TEST_MARKER": str(marker)}, spawn=rec,
                         log_path=str(self.logf))
        self.assertTrue(r.ran)
        self.assertTrue(r.real_action)
        self.assertIn(r.mode, ("production", "staging"))
        self.assertEqual(r.risk_class, "safe")
        self.assertTrue(marker.exists(), "a skill segura deve rodar")
        self.assertEqual(len(rec.calls), 1)

    # ── 2. skill SENSÍVEL sem contrato BLOQUEIA (fail-closed) ────────────
    def test_sensitive_without_contract_blocks(self):
        d = self.tmp / "governed_secret"
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "run.py").write_text(
            "import subprocess, os\nopen(os.environ['X'],'w').write('x')\n", encoding="utf-8")
        gov = lambda rel, sdir: sdir.name.startswith("governed_")  # noqa: E731
        r = sr.run_skill(d, ["scripts/run.py"], env={"X": str(self.tmp / "leak")},
                         is_governed=gov, spawn=raising_spawn, log_path=str(self.logf))
        self.assertTrue(r.blocked)
        self.assertFalse(r.ran)
        self.assertFalse((self.tmp / "leak").exists())

    # ── 3. PRODUCTION_SENSITIVE exige gate explícito ─────────────────────
    def test_production_sensitive_requires_gate(self):
        rec = _Rec()
        # sem aprovação → dry-run, NENHUMA ação real
        r0 = sr.run_skill(EX / "prepare-prod-change", ["scripts/prepare.py"], env={},
                          spawn=rec, log_path=str(self.logf))
        self.assertTrue(r0.ran)                 # roda, mas...
        self.assertFalse(r0.real_action)        # ...só simulação
        self.assertEqual(r0.mode, "dry_run")
        self.assertTrue(r0.needs_approval)
        # com aprovação humana → ação real liberada (staging)
        r1 = sr.run_skill(EX / "prepare-prod-change", ["scripts/prepare.py"],
                          env={"HERMES_HUMAN_APPROVAL": "true"}, spawn=rec,
                          log_path=str(self.logf))
        self.assertTrue(r1.real_action)
        self.assertEqual(r1.mode, "staging")

    # ── 4. KILL SWITCH bloqueia TUDO ─────────────────────────────────────
    def test_kill_switch_blocks_everything(self):
        marker = self.tmp / "k.json"
        r = sr.run_skill(EX / "safe-diagnostic", ["scripts/run.py"],
                         env={"HERMES_KILL_SWITCH": "on", "HERMES_TEST_MARKER": str(marker)},
                         spawn=raising_spawn, log_path=str(self.logf))
        self.assertTrue(r.blocked)
        self.assertEqual(r.mode, "killed")
        self.assertFalse(r.ran)
        self.assertFalse(marker.exists(), "nem a skill segura roda com kill switch")

    # ── 5. execução DIRETA de skill sensível não faz ação real ───────────
    def test_direct_execution_of_sensitive_does_no_real_action(self):
        charged = self.tmp / "charged.marker"
        script = EX / "charge-customer" / "scripts" / "charge.py"
        # BYPASS do runner: roda o script direto, sem nenhum gate no ambiente.
        p = subprocess.run([sys.executable, str(script)],
                           cwd=str(EX / "charge-customer"),
                           env={"HERMES_CHARGED_MARKER": str(charged),
                                "PATH": __import__("os").environ.get("PATH", "")},
                           capture_output=True, text=True)
        out = json.loads(p.stdout)
        self.assertFalse(out["cobranca_real"], "cobrança real jamais sem gate")
        self.assertFalse(charged.exists())

    # ── logs + relatório ─────────────────────────────────────────────────
    def test_execution_is_logged_and_reported(self):
        r = sr.run_skill(EX / "safe-diagnostic", ["scripts/run.py"], env={},
                         spawn=_Rec(), log_path=str(self.logf))
        self.assertTrue(self.logf.exists())
        line = json.loads(self.logf.read_text(encoding="utf-8").splitlines()[-1])
        self.assertEqual(line["skill"], "safe-diagnostic")
        self.assertIn("mode", line["decision"])
        self.assertIn("Hermes", r.report)


if __name__ == "__main__":
    unittest.main()
