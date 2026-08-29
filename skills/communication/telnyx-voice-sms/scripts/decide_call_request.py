"""
decide_call_request.py - grava a decisao (approve|reject) de um pedido de
ligacao. E o que o gateway roda quando o dono toca um botao inline
Aprovar/Rejeitar no Telegram (callback_data "callreq:a:<id>" / "callreq:r:<id>",
ver plugins/platforms/telegram/adapter.py::_handle_call_request_callback).

IMPORTANTE: este script NUNCA disca. Ele so registra a decisao humana de
forma atomica e idempotente no store ($HERMES_HOME/telnyx_voice_sms/
call_approvals.json) e no audit log. Quem disca e o processo da skill que
criou o pedido (request_call_approval.py), ao ver o status approved, pelo
caminho unico _call_approval_flow.execute_approved_call() -> make_call().
Assim o token do Telegram fica no gateway e a credencial Telnyx fica no
processo da skill, cada um no seu lugar.

So stdlib (roda em qualquer Python >= 3.9, inclusive o do gateway).

USO:
  python decide_call_request.py <request_id> approve --decided-by 123456
  python decide_call_request.py <request_id> reject --decided-by 123456 \
      --decided-by-name "Fernando"

SAIDA: JSON em stdout com {ok, status, reason, request}.
EXIT CODES: 0 = decisao gravada agora; 3 = pedido ja resolvido/expirado/
inexistente (idempotente, nada mudou); 2 = uso invalido.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _call_approval_store as store  # noqa: E402


def _cli():
    p = argparse.ArgumentParser(
        description="Grava a decisao de um pedido de ligacao (nunca disca)"
    )
    p.add_argument("request_id", help="id do pedido (ex.: cr1a2b3c4d)")
    p.add_argument("decision", choices=["approve", "reject"])
    p.add_argument("--decided-by", default=None,
                   help="user id do Telegram de quem tocou o botao")
    p.add_argument("--decided-by-name", default=None,
                   help="nome de exibicao de quem tocou o botao")
    p.add_argument("--dry-run", action="store_true",
                   help="mostra o estado atual sem gravar nada")
    args = p.parse_args()

    if args.dry_run:
        request = store.get_request(args.request_id)
        out = {"ok": False, "dry_run": True,
               "status": (request or {}).get("status"),
               "reason": "nada gravado (--dry-run)",
               "request": request}
        print(json.dumps(out, ensure_ascii=False))
        sys.exit(0)

    result = store.decide_request(
        args.request_id, args.decision,
        decided_by=args.decided_by, decided_by_name=args.decided_by_name,
    )
    print(json.dumps(result, ensure_ascii=False))
    sys.exit(0 if result.get("ok") else 3)


if __name__ == "__main__":
    _cli()
