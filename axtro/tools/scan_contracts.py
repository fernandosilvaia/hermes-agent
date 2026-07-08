#!/usr/bin/env python3
"""scan_contracts.py — Aplica o contract_guard em TODAS as skills e reporta o
estado de enforcement. Torna o contract.json controle VISÍVEL e acionável.

Distingue:
  - GOVERNADA (em axtro/GOVERNED_SKILLS.txt): aplica as regras do guard.
      · com contract válido → allow_real conforme enabled/ring/creds/... + modo.
      · sem contract        → legacy Axtro sensível → BLOQUEADA.
  - NATIVA (não listada): pass-through — nunca bloqueada (não governamos as Nous).

Uso:
    python3 axtro/tools/scan_contracts.py            # texto
    python3 axtro/tools/scan_contracts.py --json     # máquina
    python3 axtro/tools/scan_contracts.py --dry-run  # no-op (já é read-only)

Exit code: 0 sempre (relatório; não falha o build). Use --strict para exit 1
se alguma skill GOVERNADA estiver em estado inválido (contract quebrado).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
import contract_guard as cg  # noqa: E402

GOVERNED_LIST = REPO / "axtro" / "GOVERNED_SKILLS.txt"


def load_governed() -> list:
    if not GOVERNED_LIST.is_file():
        return []
    out = []
    for line in GOVERNED_LIST.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out


def scan(env: dict | None = None) -> dict:
    governed = load_governed()
    governed_set = set(governed)
    results = []

    # 1. Skills governadas: aplica o guard.
    for rel in governed:
        sdir = REPO / rel
        exists = sdir.is_dir()
        contract, errs = cg.load_contract(sdir) if exists else (None, ["diretorio ausente"])
        decision = cg.authorize(sdir, env) if exists else {
            "allow_real": False, "max_mode": "blocked", "reasons": ["diretorio ausente"]}
        results.append({
            "skill": rel,
            "class": "governada",
            "has_contract": contract is not None,
            "allow_real": decision["allow_real"],
            "max_mode": decision["max_mode"],
            "reasons": decision["reasons"],
        })

    # 2. Demais skills: nativas Nous → pass-through (reporta, não governa).
    native = []
    for skill_md in REPO.glob("skills/**/SKILL.md"):
        sdir = skill_md.parent
        rel = str(sdir.relative_to(REPO))
        if rel in governed_set:
            continue
        native.append(rel)

    summary = {
        "governadas": len(governed),
        "governadas_com_acao_real_liberada": sum(1 for r in results if r["allow_real"]),
        "governadas_bloqueadas": sum(1 for r in results if not r["allow_real"]),
        "governadas_sem_contract": sum(1 for r in results if not r["has_contract"]),
        "nativas_passthrough": len(native),
    }
    return {"summary": summary, "governed": results, "native_count": len(native),
            "native_sample": sorted(native)[:10]}


def main():
    parser = argparse.ArgumentParser(description="Scan de enforcement de contract.json")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="no-op (já é read-only)")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 se alguma governada tiver contract quebrado/ausente")
    args = parser.parse_args()

    result = scan()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        s = result["summary"]
        print("🔒 Contract enforcement — {} governadas · {} nativas (pass-through)".format(
            s["governadas"], s["nativas_passthrough"]))
        print("   ação real liberada: {} · bloqueadas: {} · sem contract: {}".format(
            s["governadas_com_acao_real_liberada"], s["governadas_bloqueadas"],
            s["governadas_sem_contract"]))
        print()
        for r in result["governed"]:
            flag = "🟢 REAL" if r["allow_real"] else "🔴 BLOQ"
            ctr = "" if r["has_contract"] else " (SEM CONTRACT — legacy sensível)"
            print("  {} [{}] {}{}".format(flag, r["max_mode"], r["skill"], ctr))
            if not r["allow_real"]:
                print("        motivo: {}".format(r["reasons"][0] if r["reasons"] else "?"))

    broken = [r for r in result["governed"]
              if not r["has_contract"] or "R2" in " ".join(r["reasons"])]
    sys.exit(1 if (args.strict and broken) else 0)


if __name__ == "__main__":
    main()
