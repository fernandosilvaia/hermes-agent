#!/usr/bin/env python3
"""exec_log.py — Log estruturado (JSONL) + relatório simples de cada execução.

Todo comando importante do Hermes gera uma linha no log e um relatório curto em
português. Sem isso, autonomia vira caixa-preta.

- log_execution(record, path=None) → grava 1 linha JSON no log e devolve o caminho.
- build_report(record) → string curta e legível para o Fernando.

Timestamp em America/New_York (fuso do Hermes = Flórida), com fallback p/ UTC.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_LOG = REPO / "axtro" / "logs" / "executions.jsonl"

try:  # fuso do Hermes = Flórida
    from zoneinfo import ZoneInfo
    _TZ = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001
    _TZ = timezone.utc


def now_iso() -> str:
    try:
        return datetime.now(_TZ).isoformat(timespec="seconds")
    except Exception:  # noqa: BLE001
        return datetime.now(timezone.utc).isoformat(timespec="seconds")


def default_log_path() -> str:
    return os.environ.get("HERMES_EXEC_LOG") or str(DEFAULT_LOG)


def log_execution(record: dict, path=None) -> str:
    """Anexa `record` (com ts) ao log JSONL. Cria o diretório se preciso."""
    p = Path(path or default_log_path())
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = dict(record)
    rec.setdefault("ts", now_iso())
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return str(p)


def build_report(record: dict) -> str:
    """Relatório curto e humano de uma execução."""
    d = record.get("decision", {})
    skill = record.get("skill", "?")
    ran = record.get("ran")
    real = record.get("real_action")
    mode = d.get("mode", "?")
    risk = d.get("risk_class", "?")
    ring = d.get("ring")
    reason = (d.get("reasons") or ["-"])[-1]  # a última regra aplicada é a que amarra

    if d.get("kill_switched"):
        head = "🛑 KILL SWITCH — nada executado"
    elif not ran:
        head = "🔴 BLOQUEADA — script não executado"
    elif real:
        head = "🟢 EXECUTADA (ação real, modo {})".format(mode)
    else:
        head = "🟡 DRY-RUN (simulado, nenhuma ação real)"

    lines = [
        "[Hermes] skill={} · risco={} · ring={}".format(skill, risk, ring),
        "  {}".format(head),
        "  motivo: {}".format(reason),
    ]
    if d.get("needs_approval") and not real:
        lines.append("  ⚠️  precisa de aprovação humana (HERMES_HUMAN_APPROVAL) para ação real")
    if record.get("returncode") is not None:
        lines.append("  returncode: {}".format(record["returncode"]))
    lines.append("  log: {}".format(record.get("log_path", default_log_path())))
    return "\n".join(lines)
