#!/usr/bin/env python3
"""Skill PRODUCTION_SENSITIVE (Ring 3): prepara uma mudança de produção.

Sem aprovação humana, só monta o PLANO (dry-run) — NÃO aplica nada. Aplicar de
verdade exige HERMES_HUMAN_APPROVAL + HERMES_ALLOW_EXECUTE + PROD_CHANGE_ENABLED
e ausência de --dry-run. Fail-closed."""
import json
import os
import sys


def _t(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    gate = (_t(os.environ.get("HERMES_ALLOW_EXECUTE"))
            and _t(os.environ.get("PROD_CHANGE_ENABLED"))
            and _t(os.environ.get("HERMES_HUMAN_APPROVAL")))
    plano = ["backup do banco", "aplicar migration 0007", "smoke test"]

    if dry or not gate:
        print(json.dumps({
            "acao": "prepare-prod-change", "status": "PLANO (dry-run)",
            "plano": plano, "aplicou": False,
            "motivo": "dry-run" if dry else "aprovação humana ausente (fail-closed)",
        }, ensure_ascii=False))
        return 0

    print(json.dumps({"acao": "prepare-prod-change", "status": "APLICARIA",
                      "plano": plano, "aplicou": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
