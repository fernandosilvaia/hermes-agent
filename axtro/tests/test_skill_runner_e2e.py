"""test_skill_runner_e2e.py — PROVA END-TO-END de que qualquer execução de skill
governada passa pelo contract_preflight ANTES de o script rodar.

Como isto prova de verdade (não é auto-referência):
  - Cada skill-fixture tem um script REAL que, SE rodar, escreve um arquivo-marcador
    em disco (efeito observável). Ausência do marcador = o script nunca rodou.
  - `run_skill` é o chokepoint do daemon. Nos casos que devem bloquear, injetamos
    um `spawn` que LEVANTA se for chamado — ou seja, se o runner tentar criar o
    processo do script, o teste explode. Passar = o processo NUNCA foi criado.
  - Nos casos que devem rodar, usamos o `subprocess.run` real: o script roda de
    verdade, escreve o marcador, e lemos o que ele viu (stage, allow_execute).

`daemon_execute(...)` abaixo é o "daemon do Hermes" simulado: todo caminho de
execução de skill passa por `run_skill`.

Cobre os 5 critérios:
  1. governada enabled=false     → bloqueia ANTES do script rodar
  2. governada sem contract.json → bloqueia
  3. nativa Nous                 → passa sem quebrar
  4. governada enabled=true,
     production_ready=false       → roda só em staging/dry-run (nunca produção)
  5. autonomy_ring >= 2          → exige gate explícito (bloqueia sem; roda com)
+ as skills governadas REAIS (allowlist de produção) bloqueiam pelo mesmo runner.
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

# Script-fixture: efeito observável = escreve um marcador com o que viu no ambiente.
MARKER_SCRIPT = (
    "import json, os, sys\n"
    "m = os.environ['HERMES_TEST_MARKER']\n"
    "open(m, 'w').write(json.dumps({\n"
    "    'ran': True,\n"
    "    'stage': os.environ.get('HERMES_STAGE'),\n"
    "    'allow_execute': 'HERMES_ALLOW_EXECUTE' in os.environ,\n"
    "    'dry_run': '--dry-run' in sys.argv[1:],\n"
    "}))\n"
)


def _governed_by_prefix(rel, sdir):
    """Para fixtures fora do repo: 'governed_*' é governada; o resto é nativa."""
    return sdir.name.startswith("governed_")


def raising_spawn(*a, **k):
    raise AssertionError("REGRESSÃO: o script foi spawned mesmo bloqueado! cmd={}".format(a[0] if a else a))


class _Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        return subprocess.run(cmd, **kw)


class SkillRunnerE2E(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.marker = self.root / "DID_RUN.json"

    def tearDown(self):
        self._tmp.cleanup()

    # ── infra de fixtures ────────────────────────────────────────────────
    def _make_skill(self, name, contract=None, script=MARKER_SCRIPT):
        d = self.root / name
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "run.py").write_text(script, encoding="utf-8")
        if contract is not None:
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

    def daemon_execute(self, skill_dir, env, spawn):
        """O 'daemon' simulado: TODA execução de skill passa por run_skill."""
        return sr.run_skill(skill_dir, ["scripts/run.py"], env=env,
                            is_governed=_governed_by_prefix, spawn=spawn)

    # ── CRITÉRIO 1: governada enabled=false → bloqueia antes do script ───
    def test_governed_disabled_blocks_before_script_runs(self):
        d = self._make_skill("governed_disabled",
                             self._base_contract(enabled=False))
        # spawn que explode se chamado → prova que o processo nunca é criado.
        r = self.daemon_execute(d, env={"HERMES_TEST_MARKER": str(self.marker)},
                                spawn=raising_spawn)
        self.assertTrue(r.blocked)
        self.assertFalse(r.ran)
        self.assertFalse(self.marker.exists(), "o script NÃO podia ter rodado")

    # ── CRITÉRIO 2: governada sem contract.json → bloqueia ───────────────
    def test_governed_without_contract_blocks(self):
        # marcador de sensibilidade no source → legacy sensível (R1).
        d = self._make_skill("governed_legacy", contract=None,
                             script="import subprocess  # sensível\n" + MARKER_SCRIPT)
        r = self.daemon_execute(d, env={"HERMES_TEST_MARKER": str(self.marker)},
                                spawn=raising_spawn)
        self.assertTrue(r.blocked)
        self.assertFalse(self.marker.exists())

    # ── CRITÉRIO 3: nativa Nous → passa sem quebrar ──────────────────────
    def test_native_nous_skill_passthrough_runs(self):
        d = self._make_skill("native_apple_notes",  # não começa com governed_
                             contract=None)
        rec = _Recorder()
        r = self.daemon_execute(d, env={"HERMES_TEST_MARKER": str(self.marker)},
                                spawn=rec)
        self.assertTrue(r.ran)
        self.assertFalse(r.blocked)
        self.assertEqual(r.mode, "passthrough")
        self.assertEqual(len(rec.calls), 1)
        self.assertTrue(self.marker.exists(), "nativa deve rodar normalmente")
        got = json.loads(self.marker.read_text())
        self.assertTrue(got["ran"])

    # ── CRITÉRIO 4: enabled=true, production_ready=false → só staging ────
    def test_enabled_but_not_prod_runs_only_in_staging(self):
        d = self._make_skill("governed_staging",
                             self._base_contract(enabled=True, production_ready=False))
        rec = _Recorder()
        # o caller TENTA liberar execução real; o runner deve rebaixar p/ staging.
        r = self.daemon_execute(d, env={"HERMES_TEST_MARKER": str(self.marker),
                                        "HERMES_ALLOW_EXECUTE": "true"}, spawn=rec)
        self.assertTrue(r.ran)
        self.assertEqual(r.mode, "staging")
        got = json.loads(self.marker.read_text())
        self.assertEqual(got["stage"], "staging", "nunca 'production'")
        self.assertFalse(got["allow_execute"], "HERMES_ALLOW_EXECUTE tem de ser removido")

    # ── CRITÉRIO 5: autonomy_ring >= 2 exige gate explícito ──────────────
    def test_ring2_blocks_without_gate(self):
        d = self._make_skill("governed_ring2",
                             self._base_contract(autonomy_ring=2))
        r = self.daemon_execute(d, env={"HERMES_TEST_MARKER": str(self.marker)},
                                spawn=raising_spawn)
        self.assertTrue(r.blocked)
        self.assertFalse(self.marker.exists())

    def test_ring2_runs_with_explicit_gate(self):
        d = self._make_skill("governed_ring2",
                             self._base_contract(autonomy_ring=2))
        rec = _Recorder()
        r = self.daemon_execute(d, env={"HERMES_TEST_MARKER": str(self.marker),
                                        "HERMES_RING_GATE": "true"}, spawn=rec)
        self.assertTrue(r.ran)
        self.assertIn(r.mode, ("production", "staging"))
        self.assertTrue(self.marker.exists())

    # ── PONTE COM A REALIDADE: skills governadas REAIS pelo mesmo runner ─
    def test_real_governed_skills_are_blocked_via_runner(self):
        # allowlist REAL (is_governed default) + contracts REAIS + env sem creds.
        # Nada é spawned: raising_spawn prova isso.
        reais = [
            REPO / "skills" / "finance" / "hermes-purchase",
            REPO / "skills" / "productivity" / "google-workspace-axtro",
            REPO / "skills" / "productivity" / "ask-vps-hermes",
        ]
        for sdir in reais:
            if not sdir.is_dir():
                continue
            r = sr.run_skill(sdir, ["scripts/noop.py"], env={}, spawn=raising_spawn)
            self.assertTrue(r.blocked, "{} deveria bloquear".format(sdir.name))
            self.assertFalse(r.ran)


if __name__ == "__main__":
    unittest.main()
