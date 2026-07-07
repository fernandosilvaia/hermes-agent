#!/usr/bin/env python3
"""Utilidades compartilhadas do axtro-factory-monitor.

Tudo em stdlib (Python 3.9+). Sem dependências externas, roda hoje no MacBook
onde os repos-cliente vivem, e também na VPS se um dia os repos forem espelhados.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Descoberta de raiz e configuração
# ---------------------------------------------------------------------------

# Pastas (relativas à raiz AxtroAI) que contêm repos a monitorar.
REPO_ROOTS = ["01_CLIENTES", "02_PRODUTOS"]

# Sob 02_PRODUTOS/lab há repos aninhados (o próprio hermes-agent) — inclui os
# imediatamente abaixo destas pastas também.
NESTED_ROOTS = ["02_PRODUTOS/lab"]

STALE_DAYS_DEFAULT = int(os.environ.get("AXTRO_STALE_DAYS", "6"))


def find_axtro_root() -> Path:
    """Sobe a árvore a partir deste arquivo até achar a raiz AxtroAI.

    A skill vive em .../AxtroAI/02_PRODUTOS/lab/hermes-agent/skills/productivity/
    axtro-factory-monitor/scripts/common.py — a raiz é o ancestral que contém
    CLAUDE.md + 01_CLIENTES. Permite override por AXTRO_ROOT.
    """
    override = os.environ.get("AXTRO_ROOT")
    if override:
        return Path(override).expanduser().resolve()
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "CLAUDE.md").exists() and (parent / "01_CLIENTES").is_dir():
            return parent
    # Fallback: caminho canônico conhecido.
    return Path.home() / "Developer" / "AxtroAI"


def load_env(env_path: Optional[Path] = None) -> Dict[str, str]:
    """Lê um arquivo .env simples (KEY=VALUE) sem depender de python-dotenv.

    Valores do ambiente do processo têm precedência sobre o arquivo.
    """
    values: Dict[str, str] = {}
    if env_path is None:
        root = find_axtro_root()
        env_path = root / "02_PRODUTOS" / "lab" / "hermes-agent" / ".env"
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key:
                values[key] = val
    # Ambiente do processo vence.
    for key in list(values.keys()):
        if key in os.environ:
            values[key] = os.environ[key]
    return values


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def _git(repo: Path, *args: str, timeout: int = 20) -> str:
    """Roda um comando git no repo e devolve stdout (string, pode ser vazia)."""
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return out.stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def discover_repos() -> List[Path]:
    """Lista todos os diretórios com .git sob as raízes configuradas."""
    root = find_axtro_root()
    repos: List[Path] = []
    seen = set()

    def add_if_repo(p: Path) -> None:
        if (p / ".git").exists() and p.resolve() not in seen:
            seen.add(p.resolve())
            repos.append(p)

    for rel in REPO_ROOTS:
        base = root / rel
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir():
                add_if_repo(child)

    for rel in NESTED_ROOTS:
        base = root / rel
        if not base.is_dir():
            continue
        for child in sorted(base.iterdir()):
            if child.is_dir():
                add_if_repo(child)

    return repos


def days_since_last_commit(repo: Path) -> Optional[float]:
    ts = _git(repo, "log", "-1", "--format=%ct")
    if not ts.isdigit():
        return None
    last = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    delta = datetime.now(tz=timezone.utc) - last
    return round(delta.total_seconds() / 86400.0, 1)


def current_branch(repo: Path) -> str:
    return _git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "?"


def dirty_count(repo: Path) -> int:
    out = _git(repo, "status", "--porcelain")
    return len([ln for ln in out.splitlines() if ln.strip()])


def ahead_behind(repo: Path) -> Optional[Dict[str, int]]:
    """Commits à frente/atrás do upstream configurado. None se sem upstream."""
    upstream = _git(repo, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if not upstream:
        return None
    counts = _git(repo, "rev-list", "--left-right", "--count", "@{u}...HEAD")
    parts = counts.split()
    if len(parts) != 2 or not all(p.lstrip("-").isdigit() for p in parts):
        return None
    return {"behind": int(parts[0]), "ahead": int(parts[1])}


def has_tests(repo: Path) -> bool:
    """Heurística: o projeto tem suíte de testes declarada?"""
    pkg = repo / "package.json"
    if pkg.exists():
        try:
            data = json.loads(pkg.read_text(encoding="utf-8", errors="replace"))
            scripts = data.get("scripts", {})
            if any("test" in k for k in scripts):
                if scripts.get("test", "").strip() and "no test specified" not in scripts.get("test", ""):
                    return True
        except (json.JSONDecodeError, OSError):
            pass
    for marker in ("pytest.ini", "tox.ini", "pyproject.toml"):
        if (repo / marker).exists():
            txt = _read_head(repo / marker)
            if "pytest" in txt or "[tool.pytest" in txt:
                return True
    if (repo / "vitest.config.ts").exists() or (repo / "vitest.config.js").exists():
        return True
    return False


def _read_head(path: Path, limit: int = 8000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Saída
# ---------------------------------------------------------------------------

def emit(obj) -> None:
    """Imprime JSON no stdout (contrato de todos os scripts CLI da skill)."""
    print(json.dumps(obj, ensure_ascii=False, indent=2))
