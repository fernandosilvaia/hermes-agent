"""
project_status_auditor.py — Raio-X read-only dos repositórios da House.

Roda no MacBook (onde os repos vivem), varre cada projeto e reporta, SEM tocar
em nada: branch atual, mudanças não commitadas, commits não pushados, quanto
tempo sem commit, e sinaliza o que precisa de atenção. Anel 0 (leitura pura,
zero credencial — só lê o git local).

Uso como CLI:
    python project_status_auditor.py                 # JSON completo
    python project_status_auditor.py --text          # resumo pro Telegram
    python project_status_auditor.py --attention     # só o que precisa de atenção
    python project_status_auditor.py --root ~/Developer/AxtroAI/01_CLIENTES
    python project_status_auditor.py --stale-days 10

Env (opcionais):
    PROJECTS_ROOTS   (lista separada por ':' de raízes a varrer; senão usa o padrão)
    PROJECTS_STALE_DAYS  (padrão 7 — dias sem commit pra marcar "parado")
    OBSERVABILITY_URL / OBSERVABILITY_TOKEN / OBSERVABILITY_TELEMETRY_PATH  (telemetria)

Sinalizações por repo:
    uncommitted   — working tree sujo (mudança não commitada)
    nao_pushado   — commits locais à frente do remoto (ahead > 0)
    parado        — sem commit há mais de PROJECTS_STALE_DAYS
    sem_upstream  — branch sem remoto configurado
    detached_head — HEAD solto (não está numa branch)
    erro          — git falhou / não é repo
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timezone

DEFAULT_ROOTS = [
    os.path.expanduser("~/Developer/AxtroAI/01_CLIENTES"),
    os.path.expanduser("~/Developer/AxtroAI/02_PRODUTOS"),
    os.path.expanduser("~/Developer/AxtroAI/00_CONTROL_TOWER"),
]


def _git(path: str, *args: str) -> str:
    proc = subprocess.run(
        ["git", "-C", path, *args], capture_output=True, text=True, timeout=20
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "git falhou")
    return proc.stdout.strip()


def find_repos(roots: list) -> list:
    """Acha repos git: cada raiz pode ser um repo, ou conter repos como subpastas."""
    repos = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        if os.path.isdir(os.path.join(root, ".git")):
            repos.append(root)
            continue
        for name in sorted(os.listdir(root)):
            p = os.path.join(root, name)
            if os.path.isdir(os.path.join(p, ".git")):
                repos.append(p)
    return repos


def audit_repo(path: str, stale_days: int = 7) -> dict:
    info = {"name": os.path.basename(path.rstrip("/")), "path": path, "flags": []}

    try:
        branch = _git(path, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception as exc:  # noqa: BLE001
        info["error"] = str(exc)
        info["flags"].append("erro")
        return info

    info["branch"] = branch
    if branch == "HEAD":
        info["flags"].append("detached_head")

    # working tree sujo?
    try:
        info["dirty"] = bool(_git(path, "status", "--porcelain"))
    except Exception:  # noqa: BLE001
        info["dirty"] = None
    if info.get("dirty"):
        info["flags"].append("uncommitted")

    # último commit + idade
    try:
        last = _git(path, "log", "-1", "--format=%cI")
        dt = datetime.fromisoformat(last).astimezone(timezone.utc)
        age = (datetime.now(timezone.utc) - dt).days
        info["last_commit"] = last
        info["age_days"] = age
        if age > stale_days:
            info["flags"].append("parado")
    except Exception:  # noqa: BLE001
        info["last_commit"] = None
        info["age_days"] = None

    # ahead/behind vs upstream
    try:
        counts = _git(path, "rev-list", "--left-right", "--count", "@{u}...HEAD")
        behind, ahead = (int(x) for x in counts.split())
        info["ahead"], info["behind"] = ahead, behind
        if ahead > 0:
            info["flags"].append("nao_pushado")
    except Exception:  # noqa: BLE001
        info["ahead"] = info["behind"] = None
        info["flags"].append("sem_upstream")

    return info


def audit(roots: list = None, stale_days: int = 7) -> dict:
    roots = roots or _roots_from_env()
    repos = find_repos(roots)
    results = [audit_repo(p, stale_days) for p in repos]
    attention = [r for r in results if r["flags"]]
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "roots": roots,
        "total": len(results),
        "needs_attention": len(attention),
        "repos": results,
    }


def _roots_from_env() -> list:
    env = os.environ.get("PROJECTS_ROOTS")
    if env:
        return [os.path.expanduser(p) for p in env.split(":") if p.strip()]
    return DEFAULT_ROOTS


_FLAG_EMOJI = {
    "uncommitted": "✏️", "nao_pushado": "⬆️", "parado": "💤",
    "sem_upstream": "🔌", "detached_head": "⚠️", "erro": "❌",
}


def as_text(data: dict, attention_only: bool = False) -> str:
    lines = ["🗂️ *Status dos projetos*",
             f"_{data['total']} repos · {data['needs_attention']} pedem atenção_"]
    shown = [r for r in data["repos"] if r["flags"]]
    if not attention_only:
        # também lista os OK de forma compacta
        ok = [r["name"] for r in data["repos"] if not r["flags"]]
        if ok:
            lines.append(f"✅ OK: {', '.join(ok)}")
    for r in sorted(shown, key=lambda x: len(x["flags"]), reverse=True):
        tags = " ".join(_FLAG_EMOJI.get(f, f) + f" {f}" for f in r["flags"])
        extra = ""
        if r.get("branch") and r["branch"] not in ("main", "HEAD"):
            extra += f" [{r['branch']}]"
        if r.get("age_days") is not None and "parado" in r["flags"]:
            extra += f" ({r['age_days']}d)"
        if r.get("ahead"):
            extra += f" ↑{r['ahead']}"
        lines.append(f"• *{r['name']}*{extra} — {tags}")
    if not shown:
        lines.append("✅ Tudo limpo — nada pendente.")
    return "\n".join(lines)


def emit_telemetry(data: dict) -> None:
    url = os.environ.get("OBSERVABILITY_URL")
    token = os.environ.get("OBSERVABILITY_TOKEN")
    if not url:
        return
    path = os.environ.get("OBSERVABILITY_TELEMETRY_PATH", "/telemetry")
    try:
        import requests
        requests.post(
            url.rstrip("/") + "/" + path.lstrip("/"),
            headers={"Authorization": f"Bearer {token}"} if token else {},
            json={"event": "project_status_auditor.run",
                  "total": data["total"], "needs_attention": data["needs_attention"],
                  "at": data["at"]},
            timeout=8,
        )
    except Exception:  # noqa: BLE001
        pass


def _cli():
    p = argparse.ArgumentParser(description="Project Status Auditor (Axtro Agent)")
    p.add_argument("--text", action="store_true", help="resumo em texto (Telegram)")
    p.add_argument("--attention", action="store_true", help="só o que pede atenção")
    p.add_argument("--root", action="append", help="raiz a varrer (repetível)")
    p.add_argument("--stale-days", type=int,
                   default=int(os.environ.get("PROJECTS_STALE_DAYS", "7")))
    p.add_argument("--no-telemetry", action="store_true")
    args = p.parse_args()

    roots = [os.path.expanduser(r) for r in args.root] if args.root else None
    data = audit(roots, args.stale_days)
    if not args.no_telemetry:
        emit_telemetry(data)

    if args.text or args.attention:
        print(as_text(data, attention_only=args.attention))
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
