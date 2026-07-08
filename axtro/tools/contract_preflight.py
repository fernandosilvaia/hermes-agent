#!/usr/bin/env python3
"""contract_preflight.py — O GATE de runtime. O daemon (ou o wrapper de execução
de skill, `axtro/skill_runner.py`) chama isto ANTES de deixar uma skill governada
fazer uma ação real.

É o que transforma contract.json de documentação em CONTROLE: uma decisão que,
pelo exit code, autoriza ou nega a ação real de uma skill.

Uso (o daemon/worker chama assim antes de executar a skill):
    python3 axtro/tools/contract_preflight.py <caminho-da-skill>
    # exit 0  → ação real AUTORIZADA (imprime o modo: production|staging)
    # exit 10 → BLOQUEADA por governança (imprime o motivo)
    # exit 0  → skill NATIVA da Nous (não governada) → pass-through

Sempre fail-CLOSED: qualquer erro inesperado → bloqueia (exit 10).

Este preflight NÃO substitui o gate de dupla-env dentro de cada skill — é uma
camada ADICIONAL, por cima. Ação real efetiva = preflight_ok AND gate_no_script.

API:
  preflight(skill_path, env=None, is_governed=None) -> (exit_code, mensagem)
      compat retro: tupla (code, msg).
  preflight_decision(skill_path, env=None, is_governed=None) -> dict
      decisão estruturada {code, allow, governed, mode, msg}. Usada pelo
      skill_runner para saber o MODO (production/staging/dry_run), não só o allow.
  is_governed: callable(rel:str, sdir:Path) -> bool. Default = pertencer a
      GOVERNED_SKILLS.txt. Injetável para teste (fixtures fora do repo).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
import contract_guard as cg  # noqa: E402

GOVERNED_LIST = REPO / "axtro" / "GOVERNED_SKILLS.txt"
EXIT_ALLOW = 0
EXIT_BLOCK = 10


def _governed_set() -> set:
    if not GOVERNED_LIST.is_file():
        return set()
    out = set()
    for line in GOVERNED_LIST.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return out


def _rel(sdir: Path) -> str:
    try:
        return str(sdir.relative_to(REPO))
    except ValueError:
        return sdir.name


def _default_is_governed(rel: str, sdir: Path) -> bool:
    return rel in _governed_set()


def preflight_decision(skill_path, env=None, is_governed=None) -> dict:
    """Decisão estruturada. Fail-closed em qualquer erro.

    Retorna: {code, allow: bool, governed: bool, mode: str, msg: str}
      mode ∈ {'production','staging','dry_run','blocked','passthrough'}
    """
    check = is_governed or _default_is_governed
    try:
        sdir = Path(skill_path).resolve()
        rel = _rel(sdir)
        if not check(rel, sdir):
            # Skill nativa da Nous — não governada, pass-through (nunca bloqueia).
            return {"code": EXIT_ALLOW, "allow": True, "governed": False,
                    "mode": "passthrough",
                    "msg": "PASSTHROUGH: skill nativa (nao governada pela Axtro): {}".format(rel)}
        decision = cg.authorize(sdir, env)
        if decision.get("allow_real"):
            return {"code": EXIT_ALLOW, "allow": True, "governed": True,
                    "mode": decision.get("max_mode"),
                    "msg": "AUTORIZADA (modo {}): {}".format(decision.get("max_mode"), rel)}
        motivo = (decision.get("reasons") or ["bloqueada"])[0]
        return {"code": EXIT_BLOCK, "allow": False, "governed": True,
                "mode": "blocked",
                "msg": "BLOQUEADA: {} — {}".format(rel, motivo)}
    except Exception as e:  # noqa: BLE001 — fail-closed
        return {"code": EXIT_BLOCK, "allow": False, "governed": True,
                "mode": "blocked",
                "msg": "BLOQUEADA (fail-closed, erro inesperado): {}".format(str(e)[:150])}


def preflight(skill_path, env=None, is_governed=None) -> tuple:
    """Compat retro: retorna (exit_code, mensagem)."""
    d = preflight_decision(skill_path, env=env, is_governed=is_governed)
    return d["code"], d["msg"]


def main():
    if len(sys.argv) < 2:
        print("uso: contract_preflight.py <caminho-da-skill>", file=sys.stderr)
        sys.exit(EXIT_BLOCK)
    code, msg = preflight(sys.argv[1])
    print(msg)
    sys.exit(code)


if __name__ == "__main__":
    main()
