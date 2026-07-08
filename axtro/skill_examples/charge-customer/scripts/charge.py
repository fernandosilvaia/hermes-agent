#!/usr/bin/env python3
"""Skill FINANCEIRA (risk_class=financial_sensitive, Ring 3).

NUNCA cobra de verdade sem gate humano. Gate de dupla-env fail-closed +
`--dry-run` sempre vence. Esta é a 2a CAMADA de proteção: mesmo que alguém rode
o script DIRETO (burlando o skill_runner), nenhuma cobrança real acontece sem:

    (sem --dry-run) E HERMES_ALLOW_EXECUTE=true E CHARGE_ENABLED=true
                    E HERMES_HUMAN_APPROVAL=true

Caso contrário: DRY-RUN (simula, nenhuma cobrança)."""
import json
import os
import sys


def _t(v):
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    gate = (_t(os.environ.get("HERMES_ALLOW_EXECUTE"))
            and _t(os.environ.get("CHARGE_ENABLED"))
            and _t(os.environ.get("HERMES_HUMAN_APPROVAL")))
    amount = "R$120,00"

    if dry or not gate:
        print(json.dumps({
            "acao": "charge", "status": "DRY-RUN", "valor": amount,
            "cobranca_real": False,
            "motivo": "dry-run" if dry else "gate humano ausente (fail-closed)",
        }, ensure_ascii=False))
        return 0

    # (Nunca alcançado neste build — nenhum secret/allow é setado.)
    print(json.dumps({"acao": "charge", "status": "EXECUTARIA",
                      "valor": amount, "cobranca_real": True}, ensure_ascii=False))
    m = os.environ.get("HERMES_CHARGED_MARKER")
    if m:
        with open(m, "w", encoding="utf-8") as f:
            f.write("CHARGED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
