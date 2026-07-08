#!/usr/bin/env python3
"""Skill SEGURA (risk_class=safe, Ring 0): diagnóstico read-only.
Não escreve nada real, não chama rede, não gasta. Roda sozinha."""
import json
import os
import sys


def main():
    report = {
        "skill": "safe-diagnostic",
        "stage": os.environ.get("HERMES_STAGE", "?"),
        "checou": ["disco", "git", "testes"],
        "achados": 0,
        "acao_real": False,
    }
    print(json.dumps(report, ensure_ascii=False))
    # efeito observável opcional (para teste): prova que o script rodou.
    m = os.environ.get("HERMES_TEST_MARKER")
    if m:
        with open(m, "w", encoding="utf-8") as f:
            f.write(json.dumps({"ran": True, "stage": report["stage"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
