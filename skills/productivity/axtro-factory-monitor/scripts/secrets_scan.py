#!/usr/bin/env python3
"""secrets_scan.py — Vigia de segredo vazado em commits.

Usa `git grep` (só arquivos RASTREADOS — o que de fato importa: segredo que
entrou no histórico/HEAD) em cada repo, procurando padrões de chave. Ignora
exemplos (.env.example, *.sample) e diretórios de dependência.

Uso:
    python scripts/secrets_scan.py

Saída: JSON no stdout. Nunca imprime o segredo inteiro — mascara o miolo.
"""
from __future__ import annotations

import re
import subprocess

import common

# (rótulo, regex). Regex propositalmente conservadoras para reduzir falso positivo.
PATTERNS = [
    ("OpenAI/gen key (sk-)", r"sk-[A-Za-z0-9]{20,}"),
    ("Anthropic key", r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    ("AWS access key", r"AKIA[0-9A-Z]{16}"),
    ("Google API key", r"AIza[0-9A-Za-z_\-]{35}"),
    ("Slack token", r"xox[baprs]-[0-9A-Za-z\-]{10,}"),
    ("GitHub token", r"gh[pousr]_[0-9A-Za-z]{30,}"),
    ("Stripe live key", r"sk_live_[0-9A-Za-z]{20,}"),
    ("Private key block", r"-----BEGIN (RSA |EC |OPENSSH |PGP )?PRIVATE KEY-----"),
    ("Generic bearer/secret assign", r"(?i)(secret|token|api[_-]?key|password)\s*[:=]\s*['\"][0-9A-Za-z_\-]{16,}['\"]"),
]

# Não é vazamento: exemplos, placeholders, lockfiles, deps, documentação.
IGNORE_PATH_HINTS = (
    ".env.example", ".env.sample", ".env.scoped.example", "env.scoped.example",
    "node_modules/", "package-lock.json", "pnpm-lock.yaml", "yarn.lock",
    ".sample", ".example", "test", "spec", "mock", "fixture",
    "website/", "i18n/", "/docs/", "docs/", "readme", "changelog",
)
# Palavras que denunciam placeholder na LINHA…
PLACEHOLDER_HINTS = ("example", "placeholder", "your_", "xxxx", "changeme", "dummy", "<", "redacted")
# …e no PRÓPRIO valor casado (segredo real é aleatório, não tem palavra de dicionário).
VALUE_PLACEHOLDER_WORDS = (
    "your", "here", "token", "example", "placeholder", "xxxx", "workspace",
    "team", "channel", "dummy", "sample", "changeme", "redacted", "abc", "1234",
)


def mask(secret: str) -> str:
    s = secret.strip()
    if len(s) <= 10:
        return s[:2] + "***"
    return s[:6] + "…" + s[-4:]


def looks_like_placeholder(line: str) -> bool:
    low = line.lower()
    return any(h in low for h in PLACEHOLDER_HINTS)


def scan_repo(repo):
    findings = []
    for label, pat in PATTERNS:
        try:
            out = subprocess.run(
                ["git", "-C", str(repo), "grep", "-n", "-I", "-E", pat],
                capture_output=True, text=True, timeout=40,
            )
        except (subprocess.SubprocessError, OSError):
            continue
        if out.returncode not in (0, 1):  # 1 = nada encontrado, ok
            continue
        for ln in out.stdout.splitlines():
            # formato: caminho:linha:conteudo
            parts = ln.split(":", 2)
            if len(parts) < 3:
                continue
            path, lineno, content = parts
            low_path = path.lower()
            if any(h in low_path for h in IGNORE_PATH_HINTS):
                continue
            if looks_like_placeholder(content):
                continue
            m = re.search(pat, content)
            snippet = m.group(0) if m else content.strip()[:40]
            # segredo de verdade é aleatório; se o valor tem palavra de dicionário, é exemplo
            low_val = snippet.lower()
            if any(w in low_val for w in VALUE_PLACEHOLDER_WORDS):
                continue
            findings.append({
                "type": label,
                "file": path,
                "line": lineno,
                "masked": mask(snippet),
            })
    return findings


def main():
    root = common.find_axtro_root()
    repos = common.discover_repos()
    results = []
    for repo in repos:
        f = scan_repo(repo)
        if f:
            try:
                rel = str(repo.relative_to(root))
            except ValueError:
                rel = repo.name
            results.append({"repo": repo.name, "path": rel, "findings": f})

    common.emit({
        "repos_com_alerta": len(results),
        "total_alertas": sum(len(r["findings"]) for r in results),
        "detalhes": results,
    })


if __name__ == "__main__":
    main()
