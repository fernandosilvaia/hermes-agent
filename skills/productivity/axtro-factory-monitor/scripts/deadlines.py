#!/usr/bin/env python3
"""deadlines.py — Rastreio de prazos com alerta antecipado.

Varre CLAUDE.md e os .md do topo de cada repo (+ o CLAUDE.md raiz) procurando
datas no formato ISO (YYYY-MM-DD) próximas de palavras-chave de prazo em PT/EN.
Reporta o que vence nos próximos N dias ou já venceu.

Uso:
    python scripts/deadlines.py --window 14

Datas são interpretadas no fuso do Hermes (America/New_York — Flórida).
"""
from __future__ import annotations

import argparse
import re
from datetime import datetime, timedelta
from pathlib import Path

import common

DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
DEADLINE_HINTS = (
    "prazo", "deadline", "vence", "entrega", "entregar", "até ", "ate ",
    "due", "go-live", "go live", "lançamento", "lancamento", "milestone",
)
# Linhas que descrevem algo JÁ FEITO não são prazo em aberto.
RESOLVED_HINTS = (
    "resolvido", "✅", "atualizado", "verificado", "concluíd", "concluid",
    "done", "feito", "backup/imac", "~~",
)
# Quão para trás no passado ainda é "acionável" (mais que isso é ruído histórico).
PAST_FLOOR_DAYS = -30

# America/New_York ~ UTC-4/-5. Sem zoneinfo garantido no 3.9 do sistema,
# usamos a data local do processo como referência (o launchd roda no fuso do Mac).
TODAY = datetime.now().date()


def scan_file(path: Path, window_days: int):
    hits = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return hits
    for i, line in enumerate(text.splitlines(), 1):
        low = line.lower()
        if not any(h in low for h in DEADLINE_HINTS):
            continue
        if any(h in low for h in RESOLVED_HINTS):
            continue  # já resolvido / concluído — não é prazo em aberto
        for m in DATE_RE.finditer(line):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            try:
                when = datetime(y, mo, d).date()
            except ValueError:
                continue
            delta = (when - TODAY).days
            if PAST_FLOOR_DAYS <= delta <= window_days:  # vencido recente ou vence na janela
                hits.append({
                    "date": when.isoformat(),
                    "days_left": delta,
                    "status": "vencido" if delta < 0 else "proximo",
                    "line": line.strip()[:180],
                    "file": str(path.name),
                    "line_no": i,
                })
    return hits


def candidate_files(root: Path):
    files = []
    claude_root = root / "CLAUDE.md"
    if claude_root.exists():
        files.append(claude_root)
    for repo in common.discover_repos():
        for name in ("CLAUDE.md", "STATUS.md", "HANDOFF.md", "ROADMAP.md", "README.md"):
            p = repo / name
            if p.exists():
                files.append(p)
    return files


def main():
    parser = argparse.ArgumentParser(description="Rastreio de prazos")
    parser.add_argument("--window", type=int, default=14, help="janela de dias à frente")
    args = parser.parse_args()

    root = common.find_axtro_root()
    all_hits = []
    for f in candidate_files(root):
        for h in scan_file(f, args.window):
            try:
                h["repo"] = str(f.parent.relative_to(root))
            except ValueError:
                h["repo"] = f.parent.name
            all_hits.append(h)

    # dedup por (date, line) e ordena por urgência
    seen = set()
    unique = []
    for h in sorted(all_hits, key=lambda x: x["days_left"]):
        key = (h["date"], h["line"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(h)

    common.emit({
        "window_days": args.window,
        "today": TODAY.isoformat(),
        "total": len(unique),
        "vencidos": sum(1 for h in unique if h["status"] == "vencido"),
        "prazos": unique,
    })


if __name__ == "__main__":
    main()
