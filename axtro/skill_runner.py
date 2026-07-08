#!/usr/bin/env python3
"""skill_runner.py — O EXECUTOR OFICIAL do Hermes. O único ponto por onde o
daemon deve rodar o script de uma skill governada.

Fluxo de cada execução:
  1. autonomy_core.decide()  → decisão de autonomia (kill switch, ring, classe de
     risco, aprovação, modo). Se BLOQUEADA/KILLED, o subprocess NUNCA é criado.
  2. aplica o MODO ao ambiente/args (dry-run, staging, production).
  3. spawna o script.
  4. loga a execução (JSONL) e devolve um relatório curto.

A GARANTIA (e seu limite honesto)
---------------------------------
"Qualquer execução de skill governada passa pelo decide() antes de rodar" é
VERDADE para toda execução roteada por `run_skill`. Um bypass (rodar o script
direto) escaparia deste runner — como escaparia de qualquer wrapper. Por isso há
DEFESA EM PROFUNDIDADE: o gate de dupla-env dentro de cada script continua
valendo por baixo e sozinho já bloqueia ação real num bypass.

  ação real efetiva = run_skill autoriza  AND  gate no próprio script

Modos aplicados ao spawnar:
  - blocked/killed → NÃO spawna (fail-closed).
  - dry_run        → spawna forçando `--dry-run`, sem HERMES_ALLOW_EXECUTE (simula).
  - staging        → spawna com HERMES_STAGE=staging, sem HERMES_ALLOW_EXECUTE.
  - production     → spawna com HERMES_STAGE=production (gate no script ainda vale).
  - passthrough    → skill nativa: spawna como veio (não governamos as nativas).

100% stdlib. `subprocess.run` é injetável via `spawn=` para teste (provar que o
processo não é criado quando bloqueado).
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "axtro"))
sys.path.insert(0, str(REPO / "axtro" / "tools"))
import autonomy_core as ac  # noqa: E402
import contract_preflight as pf  # noqa: E402  (reusa _rel/_default_is_governed/EXIT_*)
import exec_log  # noqa: E402

SPAWN_MODES = ("passthrough", "dry_run", "staging", "production")


@dataclass
class RunResult:
    skill: str
    ran: bool               # o script chegou a ser spawned?
    blocked: bool           # barrado antes do spawn (nenhum processo criado)?
    mode: str               # production|staging|dry_run|blocked|killed|passthrough
    real_action: bool       # a execução foi ação REAL (não dry-run)?
    needs_approval: bool
    risk_class: str
    reason: str
    report: str = ""
    returncode: object = None
    log_path: str = ""
    argv: list = field(default_factory=list)


def _resolve_cmd(sdir: Path, argv: list) -> list:
    """Monta o comando concreto a partir de argv relativo à skill."""
    first, rest = argv[0], list(argv[1:])
    target = str((sdir / first))
    if first.endswith(".py"):
        return [sys.executable, target] + rest
    if first.endswith((".sh", ".bash")):
        return ["bash", target] + rest
    return [target] + rest


def run_skill(skill_dir, script_argv, env=None, *, is_governed=None, spawn=None,
              log=True, log_path=None) -> RunResult:
    """Executa o script de uma skill SÓ conforme a decisão de autonomia.

    NUNCA cria o processo do script se a decisão for blocked/killed (fail-closed).
    """
    base_env = dict(os.environ if env is None else env)
    spawn = spawn or subprocess.run
    sdir = Path(skill_dir).resolve()
    label = sdir.name

    # ── CHOKEPOINT: decisão de autonomia ANTES de qualquer spawn ──────────
    rel = pf._rel(sdir)
    governed = (is_governed or pf._default_is_governed)(rel, sdir)
    d = ac.decide(sdir, base_env, native=not governed)

    def _finish(ran, rc, argv):
        record = {
            "skill": label, "skill_rel": rel, "ran": ran,
            "real_action": (ran and d.real_action), "returncode": rc,
            "decision": d.as_dict(), "argv": list(argv),
        }
        lp = exec_log.log_execution(record, log_path) if log else (log_path or "")
        record["log_path"] = lp
        report = exec_log.build_report(record)
        return RunResult(
            skill=label, ran=ran, blocked=(not ran), mode=d.mode,
            real_action=(ran and d.real_action), needs_approval=d.needs_approval,
            risk_class=d.risk_class, reason=(d.reasons or ["-"])[0], report=report,
            returncode=rc, log_path=lp, argv=list(argv))

    # ── hard block: blocked/killed → não spawna ───────────────────────────
    if d.mode not in SPAWN_MODES:
        return _finish(ran=False, rc=None, argv=script_argv)

    # ── aplica a restrição de modo ────────────────────────────────────────
    run_env = dict(base_env)
    argv = list(script_argv)
    if d.mode == "dry_run":
        run_env["HERMES_STAGE"] = "dry_run"
        run_env.pop("HERMES_ALLOW_EXECUTE", None)
        if "--dry-run" not in argv:
            argv = argv + ["--dry-run"]
    elif d.mode == "staging":
        run_env["HERMES_STAGE"] = "staging"
        run_env.pop("HERMES_ALLOW_EXECUTE", None)  # produção nunca liberada aqui
    elif d.mode == "production":
        run_env["HERMES_STAGE"] = "production"
    # passthrough (nativa) → sem restrição.

    cmd = _resolve_cmd(sdir, argv)
    proc = spawn(cmd, cwd=str(sdir), env=run_env)
    rc = getattr(proc, "returncode", 0)
    return _finish(ran=True, rc=rc, argv=argv)


# CLI: o daemon pode chamar via shell. Sai 10 se não fez ação real.
def main():
    if len(sys.argv) < 3:
        print("uso: skill_runner.py <skill_dir> <script.py> [args...]", file=sys.stderr)
        sys.exit(pf.EXIT_BLOCK)
    r = run_skill(sys.argv[1], sys.argv[2:])
    print(r.report)
    sys.exit(pf.EXIT_ALLOW if r.real_action else pf.EXIT_BLOCK)


if __name__ == "__main__":
    main()
