#!/usr/bin/env python3
"""contract_preflight.py — O GATE de runtime. O daemon (ou o wrapper de execução
de skill) chama isto ANTES de deixar uma skill governada fazer uma ação real.

É o que transforma contract.json de documentação em CONTROLE: um processo que,
pelo exit code, autoriza ou nega a ação real de uma skill.

Uso (o daemon/worker chama assim antes de executar a skill):
    python3 axtro/tools/contract_preflight.py <caminho-da-skill>
    # exit 0  → ação real AUTORIZADA (imprime o modo: production|staging)
    # exit 10 → BLOQUEADA por governança (imprime o motivo)
    # exit 0  → skill NATIVA da Nous (não governada) → pass-through

Sempre fail-CLOSED: qualquer erro inesperado → bloqueia (exit 10).

Este preflight NÃO substitui o gate de dupla-env dentro de cada skill — é uma
camada ADICIONAL, por cima. Ação real efetiva = preflight_ok AND gate_no_script.
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


def preflight(skill_path: str, env=None) -> tuple:
    """Retorna (exit_code, mensagem). Fail-closed em qualquer erro."""
    try:
        sdir = Path(skill_path).resolve()
        try:
            rel = str(sdir.relative_to(REPO))
        except ValueError:
            rel = sdir.name
        governed = _governed_set()

        if rel not in governed:
            # Skill nativa da Nous — não governada, pass-through (nunca bloqueia).
            return EXIT_ALLOW, "PASSTHROUGH: skill nativa (nao governada pela Axtro): {}".format(rel)

        decision = cg.authorize(sdir, env)
        if decision.get("allow_real"):
            return EXIT_ALLOW, "AUTORIZADA (modo {}): {}".format(decision.get("max_mode"), rel)
        motivo = (decision.get("reasons") or ["bloqueada"])[0]
        return EXIT_BLOCK, "BLOQUEADA: {} — {}".format(rel, motivo)
    except Exception as e:  # noqa: BLE001 — fail-closed
        return EXIT_BLOCK, "BLOQUEADA (fail-closed, erro inesperado): {}".format(str(e)[:150])


def main():
    if len(sys.argv) < 2:
        print("uso: contract_preflight.py <caminho-da-skill>", file=sys.stderr)
        sys.exit(EXIT_BLOCK)
    code, msg = preflight(sys.argv[1])
    print(msg)
    sys.exit(code)


if __name__ == "__main__":
    main()
