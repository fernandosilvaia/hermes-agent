#!/usr/bin/env python3
"""lint_check.py — Lint/typecheck/test agendado dos projetos INTERNOS (Anel 0).

Escopo deliberadamente restrito a `02_PRODUTOS/lab/*` e `02_PRODUTOS/llm-router`
(produtos internos da Axtro) — NUNCA projetos de cliente em `01_CLIENTES/`, que têm
suas próprias pipelines e não devem ser tocados por um monitor genérico.

Roda `npm run lint/typecheck/test` (workspaces npm) e, quando disponível no venv,
`ruff check` + `pytest` (Python). Se as dependências de um projeto não estiverem
instaladas, REPORTA isso em vez de instalar silenciosamente ou fingir que passou.

Uso:
    python scripts/lint_check.py                # roda tudo, imprime JSON
    python scripts/lint_check.py --notify        # entrega no Telegram (só se houver falha)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import common
import telegram_send

# path relativo à raiz AxtroAI, tipo de projeto, comandos npm a checar.
NPM_PROJECTS = [
    {"name": "hermes-agent/web", "path": "02_PRODUTOS/lab/hermes-agent/web",
     "npm_prefix": "02_PRODUTOS/lab/hermes-agent/web", "checks": ["lint", "typecheck"]},
    {"name": "hermes-agent/ui-tui", "path": "02_PRODUTOS/lab/hermes-agent/ui-tui",
     "npm_prefix": "02_PRODUTOS/lab/hermes-agent/ui-tui", "checks": ["lint", "typecheck"]},
    {"name": "llm-router", "path": "02_PRODUTOS/llm-router",
     "npm_prefix": "02_PRODUTOS/llm-router", "checks": ["typecheck", "test"]},
]

PYTHON_PROJECTS = [
    {"name": "hermes-agent (python)", "path": "02_PRODUTOS/lab/hermes-agent",
     "venv": "02_PRODUTOS/lab/hermes-agent/.venv"},
]

TIMEOUT_SECONDS = 180


def npm_has_deps(root: Path, rel_prefix: str) -> bool:
    prefix = root / rel_prefix
    if (prefix / "node_modules").is_dir():
        return True
    # workspaces npm hospedam bin/deps na raiz do monorepo (ex: hermes-agent/node_modules)
    monorepo_root = prefix
    for parent in [prefix] + list(prefix.parents):
        if (parent / "package.json").exists() and (parent / "node_modules" / ".bin").is_dir():
            return True
        if parent.name == "hermes-agent":  # não sobe além do repo
            break
    return False


def run_npm_check(root: Path, rel_prefix: str, script: str) -> dict:
    prefix = root / rel_prefix
    try:
        out = subprocess.run(
            ["npm", "run", script, "--prefix", str(prefix)],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
        return {
            "script": script,
            "passed": out.returncode == 0,
            "tail": "\n".join((out.stdout + out.stderr).splitlines()[-15:]),
        }
    except subprocess.TimeoutExpired:
        return {"script": script, "passed": False, "tail": "timeout ({}s)".format(TIMEOUT_SECONDS)}
    except (subprocess.SubprocessError, OSError) as e:
        return {"script": script, "passed": False, "tail": str(e)[:300]}


def check_npm_project(root: Path, proj: dict) -> dict:
    if not (root / proj["path"]).is_dir():
        return {"name": proj["name"], "status": "ausente", "checks": []}
    if not npm_has_deps(root, proj["npm_prefix"]):
        return {"name": proj["name"], "status": "dependencias_ausentes", "checks": [],
                "hint": "rode `npm install` em {}".format(proj["path"])}
    results = [run_npm_check(root, proj["npm_prefix"], c) for c in proj["checks"]]
    all_ok = all(r["passed"] for r in results)
    return {"name": proj["name"], "status": "ok" if all_ok else "falhou", "checks": results}


def python_has_deps(venv: Path, tool: str) -> bool:
    return (venv / "bin" / tool).exists()


def run_python_check(root: Path, proj: dict) -> dict:
    venv = root / proj["venv"]
    project_root = root / proj["path"]
    checks = []
    if not venv.is_dir():
        return {"name": proj["name"], "status": "sem_venv", "checks": [],
                "hint": "recriar .venv em {}".format(proj["path"])}

    for tool, args in (("ruff", ["check", "."]), ("pytest", ["-q"])):
        if not python_has_deps(venv, tool):
            checks.append({"script": tool, "passed": None,
                            "tail": "{} não instalado no .venv — pip install pendente".format(tool)})
            continue
        try:
            out = subprocess.run(
                [str(venv / "bin" / tool), *args],
                capture_output=True, text=True, timeout=TIMEOUT_SECONDS, cwd=str(project_root),
            )
            checks.append({
                "script": tool,
                "passed": out.returncode == 0,
                "tail": "\n".join((out.stdout + out.stderr).splitlines()[-15:]),
            })
        except subprocess.TimeoutExpired:
            checks.append({"script": tool, "passed": False, "tail": "timeout"})
        except (subprocess.SubprocessError, OSError) as e:
            checks.append({"script": tool, "passed": False, "tail": str(e)[:300]})

    ran = [c for c in checks if c["passed"] is not None]
    status = "ok" if ran and all(c["passed"] for c in ran) else (
        "falhou" if any(c["passed"] is False for c in ran) else "dependencias_ausentes")
    return {"name": proj["name"], "status": status, "checks": checks}


def compose_message(results: list) -> str:
    problemas = [r for r in results if r["status"] not in ("ok",)]
    if not problemas:
        return "✅ Lint/typecheck/test dos projetos internos: tudo verde ({} projetos).".format(len(results))

    lines = ["🔧 *Lint/TS check — projetos internos*", ""]
    for r in results:
        if r["status"] == "ok":
            continue
        marker = {"falhou": "❌", "dependencias_ausentes": "⚠️", "sem_venv": "⚠️", "ausente": "❔"}.get(r["status"], "❔")
        lines.append("{} {} — {}".format(marker, r["name"], r["status"]))
        if r.get("hint"):
            lines.append("   → {}".format(r["hint"]))
        for c in r.get("checks", []):
            if c["passed"] is False:
                lines.append("   {}: {}".format(c["script"], c["tail"].splitlines()[-1][:150] if c["tail"] else ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Lint/TS check dos projetos internos")
    parser.add_argument("--notify", action="store_true", help="entrega no Telegram só se houver falha/dependência ausente")
    args = parser.parse_args()

    root = common.find_axtro_root()
    results = [check_npm_project(root, p) for p in NPM_PROJECTS]
    results += [run_python_check(root, p) for p in PYTHON_PROJECTS]

    payload = {"total": len(results), "resultados": results}
    common.emit(payload)

    if args.notify:
        problemas = [r for r in results if r["status"] != "ok"]
        if problemas:
            telegram_send.send(compose_message(results))
        # filosofia [SILENT]: tudo verde não gera notificação, evita spam diário


if __name__ == "__main__":
    main()
