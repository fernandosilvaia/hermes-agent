#!/usr/bin/env python3
"""skill_runner.py — O ÚNICO ponto por onde o daemon Hermes deve executar o
script de uma skill governada. Faz o contract_preflight ANTES de criar o
processo do script.

PORQUÊ ISTO EXISTE
------------------
Hoje o runtime da Nous executa skill no modelo (a): o LLM lê o SKILL.md e roda o
script pelas tools genéricas (`terminal`/`execute_code`). Não há um dispatcher
determinístico por skill — logo, sozinho, o preflight seria só uma função que
alguém "lembra" de chamar. Este runner É esse dispatcher: um único chokepoint
que o worker do daemon usa para rodar o script de uma skill governada.

A GARANTIA (e seu limite honesto)
---------------------------------
Se o preflight bloquear, o subprocess do script NUNCA é criado. Portanto:
  "qualquer execução de skill governada passa pelo preflight antes de rodar"
é VERDADE **para toda execução roteada por `run_skill`**. Um bypass (rodar o
script direto no shell) escaparia deste runner — como escaparia de qualquer
wrapper. Por isso há DEFESA EM PROFUNDIDADE: o gate de dupla-env dentro de cada
script (HERMES_ALLOW_EXECUTE + <SKILL>_ENABLED) continua valendo por baixo, e
sozinho já bloqueia ação real mesmo num bypass (provado nos 163 testes da Parte 1).

  ação real efetiva = run_skill autoriza (preflight)  AND  gate no próprio script

Modos aplicados ao spawnar (R4/R6 do contract_guard):
  - blocked      → NÃO spawna (fail-closed).
  - dry_run      → spawna forçando `--dry-run` e sem HERMES_ALLOW_EXECUTE.
  - staging      → spawna com HERMES_STAGE=staging e SEM HERMES_ALLOW_EXECUTE
                   (produção proibida; ação real só no ambiente de staging).
  - production   → spawna com HERMES_STAGE=production (o gate no script ainda vale).
  - passthrough  → skill nativa: spawna como veio (não governamos as nativas).

100% stdlib. O executor real (`subprocess.run`) é injetável via `spawn=` para
teste — para provar que o processo NÃO chega a ser criado quando bloqueado.
"""
from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "axtro" / "tools"))
import contract_preflight as pf  # noqa: E402


@dataclass
class RunResult:
    skill: str
    ran: bool           # o script chegou a ser spawned?
    blocked: bool       # foi barrado pelo preflight (script nunca criado)?
    mode: str           # production|staging|dry_run|blocked|passthrough
    reason: str
    returncode: int | None = None
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


def run_skill(skill_dir, script_argv, env=None, *, is_governed=None, spawn=None) -> RunResult:
    """Executa o script de uma skill SÓ se o contract_preflight autorizar.

    Args:
      skill_dir: diretório da skill.
      script_argv: ex. ["scripts/foo.py", "--x"] (relativo à skill).
      env: ambiente para o preflight E para o subprocess (default os.environ).
      is_governed: callable(rel, sdir)->bool p/ teste; default = allowlist real.
      spawn: injeção do executor (default subprocess.run) — para o teste
             espionar se o processo chegou a ser criado.

    NUNCA cria o processo do script se o preflight bloquear (fail-closed).
    """
    base_env = dict(os.environ if env is None else env)
    spawn = spawn or subprocess.run
    sdir = Path(skill_dir).resolve()
    label = sdir.name

    # ── CHOKEPOINT: preflight ANTES de qualquer spawn ─────────────────────
    d = pf.preflight_decision(str(sdir), env=base_env, is_governed=is_governed)
    if not d["allow"]:
        # BLOQUEADO — o script NÃO é spawned. Nenhum processo é criado.
        return RunResult(skill=label, ran=False, blocked=True,
                         mode="blocked", reason=d["msg"], argv=list(script_argv))

    mode = d["mode"]
    run_env = dict(base_env)
    argv = list(script_argv)

    # ── aplica a restrição de modo ao ambiente/args do subprocess ─────────
    if mode in ("dry_run", "staging"):
        run_env["HERMES_STAGE"] = "staging"
        run_env.pop("HERMES_ALLOW_EXECUTE", None)  # produção nunca liberada aqui
        if mode == "dry_run" and "--dry-run" not in argv:
            argv = argv + ["--dry-run"]
    elif mode == "production":
        run_env["HERMES_STAGE"] = "production"
    # passthrough (nativa) → sem restrição.

    cmd = _resolve_cmd(sdir, argv)
    proc = spawn(cmd, cwd=str(sdir), env=run_env)
    rc = getattr(proc, "returncode", 0)
    return RunResult(skill=label, ran=True, blocked=False, mode=mode,
                     reason=d["msg"], returncode=rc, argv=argv)


# CLI fino: o daemon pode chamar via shell também. Sai 10 se bloqueado.
def main():
    if len(sys.argv) < 3:
        print("uso: skill_runner.py <skill_dir> <script.py> [args...]", file=sys.stderr)
        sys.exit(pf.EXIT_BLOCK)
    r = run_skill(sys.argv[1], sys.argv[2:])
    print("{}: ran={} mode={} — {}".format(r.skill, r.ran, r.mode, r.reason))
    sys.exit(pf.EXIT_ALLOW if r.ran else pf.EXIT_BLOCK)


if __name__ == "__main__":
    main()
