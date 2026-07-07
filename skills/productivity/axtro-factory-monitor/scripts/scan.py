#!/usr/bin/env python3
"""scan.py — Estado de saúde de cada repo da fábrica Axtro.

Para cada repo com git sob 01_CLIENTES e 02_PRODUTOS coleta: branch atual,
mudanças não-commitadas, commits à frente/atrás do upstream, dias desde o
último commit (detector de projeto parado) e se há suíte de testes.

Uso:
    python scripts/scan.py                # JSON completo
    python scripts/scan.py --stale-days 6 # limiar de "parado" custom

Saída: JSON no stdout. 100% leitura, nunca escreve em repo nenhum.
"""
from __future__ import annotations

import argparse

import common


def scan_repo(repo, stale_days):
    root = common.find_axtro_root()
    try:
        rel = str(repo.relative_to(root))
    except ValueError:
        rel = repo.name

    days = common.days_since_last_commit(repo)
    dirty = common.dirty_count(repo)
    ab = common.ahead_behind(repo)

    flags = []
    if days is not None and days >= stale_days:
        flags.append("parado")
    if dirty > 0:
        flags.append("nao_commitado")
    if ab and ab.get("ahead", 0) > 0:
        flags.append("nao_pushado")
    if ab and ab.get("behind", 0) > 0:
        flags.append("atras_do_remoto")
    if ab is None:
        flags.append("sem_upstream")

    return {
        "name": repo.name,
        "path": rel,
        "branch": common.current_branch(repo),
        "days_since_commit": days,
        "dirty_files": dirty,
        "ahead_behind": ab,
        "has_tests": common.has_tests(repo),
        "flags": flags,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan de saúde dos repos Axtro")
    parser.add_argument("--stale-days", type=int, default=common.STALE_DAYS_DEFAULT)
    args = parser.parse_args()

    repos = common.discover_repos()
    results = [scan_repo(r, args.stale_days) for r in repos]

    # Ordena: quem tem mais flags (mais atenção) primeiro.
    results.sort(key=lambda r: (-len(r["flags"]), r["days_since_commit"] or 0))

    summary = {
        "total_repos": len(results),
        "parados": sum(1 for r in results if "parado" in r["flags"]),
        "nao_pushados": sum(1 for r in results if "nao_pushado" in r["flags"]),
        "com_mudancas_locais": sum(1 for r in results if "nao_commitado" in r["flags"]),
        "sem_upstream": sum(1 for r in results if "sem_upstream" in r["flags"]),
    }
    common.emit({"summary": summary, "repos": results})


if __name__ == "__main__":
    main()
