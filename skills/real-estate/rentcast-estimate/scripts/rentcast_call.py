#!/usr/bin/env python3
"""rentcast_call.py — estimativa de aluguel/valor via Rentcast AVM.

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

BASE_URL = "https://api.rentcast.io/v1"
ENDPOINTS = {"rent": f"{BASE_URL}/avm/rent/long-term", "value": f"{BASE_URL}/avm/value"}
VALUE_FIELDS = {"rent": "rent", "value": "price"}


class RentcastError(RuntimeError):
    pass


def _api_key() -> str:
    key = get_secret("RENTCAST_API_KEY")
    if not key:
        raise RentcastError(
            "RENTCAST_API_KEY não está no ambiente/escopo do perfil. "
            "É a chave própria do cliente (conta Rentcast dele)."
        )
    return key


def estimate(
    kind: str,
    *,
    address: Optional[str] = None,
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    property_type: Optional[str] = None,
    bedrooms: Optional[float] = None,
    bathrooms: Optional[float] = None,
    square_footage: Optional[int] = None,
    session: Optional[requests.Session] = None,
) -> Dict[str, Any]:
    if kind not in ENDPOINTS:
        raise RentcastError(f"kind inválido: {kind!r} (esperado 'rent' ou 'value')")
    if not address and (lat is None or lng is None):
        raise RentcastError("passe address OU (lat e lng)")

    params: Dict[str, Any] = {}
    if address:
        params["address"] = address
    else:
        params["latitude"] = lat
        params["longitude"] = lng
    if property_type:
        params["propertyType"] = property_type
    if bedrooms is not None:
        params["bedrooms"] = bedrooms
    if bathrooms is not None:
        params["bathrooms"] = bathrooms
    if square_footage is not None:
        params["squareFootage"] = square_footage

    resp = (session or requests).get(
        ENDPOINTS[kind], params=params, headers={"X-Api-Key": _api_key()}, timeout=20,
    )
    if not resp.ok:
        return {"ok": False, "kind": kind, "status_code": resp.status_code, "error": _safe_error_body(resp)}
    return _parse_response(kind, resp.json())


def _safe_error_body(resp: requests.Response) -> Any:
    try:
        return resp.json()
    except ValueError:
        return resp.text


def _parse_response(kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
    field = VALUE_FIELDS[kind]
    subject = data.get("subjectProperty") or {}
    return {
        "ok": True,
        "kind": kind,
        field: data.get(field),
        f"{field}_range_low": data.get(f"{field}RangeLow"),
        f"{field}_range_high": data.get(f"{field}RangeHigh"),
        "subject_property": {
            "formatted_address": subject.get("formattedAddress"),
            "bedrooms": subject.get("bedrooms"),
            "bathrooms": subject.get("bathrooms"),
            "square_footage": subject.get("squareFootage"),
        },
        "comparables_count": len(data.get("comparables") or []),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Estimativa de aluguel/valor via Rentcast")
    parser.add_argument("--kind", required=True, choices=["rent", "value"])
    parser.add_argument("--address")
    parser.add_argument("--lat", type=float)
    parser.add_argument("--lng", type=float)
    parser.add_argument("--property-type")
    parser.add_argument("--bedrooms", type=float)
    parser.add_argument("--bathrooms", type=float)
    parser.add_argument("--square-footage", type=int)
    parser.add_argument("--json", action="store_true", default=True)
    parser.add_argument("--text", action="store_true")
    args = parser.parse_args()

    try:
        result = estimate(
            args.kind, address=args.address, lat=args.lat, lng=args.lng,
            property_type=args.property_type, bedrooms=args.bedrooms,
            bathrooms=args.bathrooms, square_footage=args.square_footage,
        )
    except RentcastError as e:
        result = {"ok": False, "kind": args.kind, "error": str(e)}

    if args.text and not args.json:
        if result.get("ok"):
            field = VALUE_FIELDS[args.kind]
            print(f"{field}: {result[field]} (faixa {result[f'{field}_range_low']}-{result[f'{field}_range_high']})")
        else:
            print(f"Erro: {result.get('error')}")
    else:
        print(json.dumps(result, ensure_ascii=False))

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(_main())
