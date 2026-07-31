#!/usr/bin/env python3
"""attom_call.py — dados de propriedade via ATTOM Data API.

Leitura pura (anel 0): sem gate, sem efeito colateral. Credencial lida via
agent.secret_scope.get_secret() (nunca os.environ direto).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import requests

_REPO_ROOT = Path(__file__).resolve().parents[4]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from agent.secret_scope import get_secret  # noqa: E402

BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"
ENDPOINTS = {
    "detail": f"{BASE_URL}/property/detail",
    "snapshot": f"{BASE_URL}/property/snapshot",
    "avm": f"{BASE_URL}/avm/snapshot",
}
SUCCESS_CODE = 0


class AttomError(RuntimeError):
    pass


def _api_key() -> str:
    key = get_secret("ATTOM_API_KEY")
    if not key:
        raise AttomError(
            "ATTOM_API_KEY não está no ambiente/escopo do perfil. "
            "É a chave própria do cliente (conta ATTOM dele)."
        )
    return key


def lookup(
    kind: str,
    *,
    address1: str,
    address2: str,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    if kind not in ENDPOINTS:
        raise AttomError(f"kind inválido: {kind!r} (esperado {sorted(ENDPOINTS)})")
    if not address1 or not address2:
        raise AttomError("passe --address1 (rua) e --address2 (cidade, estado, cep)")

    resp = (session or requests).get(
        ENDPOINTS[kind],
        params={"address1": address1, "address2": address2},
        headers={"APIKey": _api_key(), "Accept": "application/json"},
        timeout=20,
    )
    if not resp.ok:
        return {"ok": False, "kind": kind, "status_code": resp.status_code, "error": _safe_error_body(resp)}

    body = resp.json()
    status = body.get("status", {})
    if status.get("code") != SUCCESS_CODE:
        return {"ok": False, "kind": kind, "status_code": resp.status_code, "attom_status": status}

    property_data = {k: v for k, v in body.items() if k != "status"}
    return {"ok": True, "kind": kind, "property": property_data}


def _safe_error_body(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _main() -> int:
    parser = argparse.ArgumentParser(description="Dados de propriedade via ATTOM Data")
    parser.add_argument("--kind", required=True, choices=sorted(ENDPOINTS))
    parser.add_argument("--address1", required=True, help="rua (número + nome)")
    parser.add_argument("--address2", required=True, help="cidade, estado, cep")
    parser.add_argument("--json", action="store_true", default=True)
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    try:
        result = lookup(args.kind, address1=args.address1, address2=args.address2)
    except AttomError as e:
        result = {"ok": False, "kind": args.kind, "error": str(e)}

    if args.text and not args.json:
        if result.get("ok"):
            print(f"{args.kind}: {json.dumps(result['property'], ensure_ascii=False)[:500]}")
        else:
            print(f"Erro: {result.get('error') or result.get('attom_status')}")
    else:
        print(json.dumps(result, ensure_ascii=False))

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
