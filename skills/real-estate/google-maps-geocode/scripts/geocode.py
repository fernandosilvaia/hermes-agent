#!/usr/bin/env python3
"""geocode.py — geocodificação direta/reversa via Google Maps Geocoding API.

Leitura pura (anel 0): sem gate, sem efeito colateral. Credencial lida via
agent.secret_scope.get_secret() (nunca os.environ direto — escopado por
perfil sob multiplex_profiles, idêntico a os.environ fora dele).
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

GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"


class GeocodeError(RuntimeError):
    pass


def _api_key() -> str:
    key = get_secret("GOOGLE_MAPS_API_KEY")
    if not key:
        raise GeocodeError(
            "GOOGLE_MAPS_API_KEY não está no ambiente/escopo do perfil. "
            "É a chave própria do cliente (Google Cloud Console dele)."
        )
    return key


def _extract_components(components: list) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {"city": None, "state": None, "postal_code": None, "country": None}
    for c in components:
        types = c.get("types", [])
        if "locality" in types:
            out["city"] = c.get("long_name")
        elif "administrative_area_level_1" in types:
            out["state"] = c.get("short_name")
        elif "postal_code" in types:
            out["postal_code"] = c.get("long_name")
        elif "country" in types:
            out["country"] = c.get("short_name")
    return out


def geocode(address: str, *, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    params = {"address": address, "key": _api_key()}
    resp = (session or requests).get(GEOCODE_URL, params=params, timeout=15)
    resp.raise_for_status()
    return _parse_response(resp.json())


def reverse_geocode(lat: float, lng: float, *, session: Optional[requests.Session] = None) -> Dict[str, Any]:
    params = {"latlng": f"{lat},{lng}", "key": _api_key()}
    resp = (session or requests).get(GEOCODE_URL, params=params, timeout=15)
    resp.raise_for_status()
    return _parse_response(resp.json())


def _parse_response(data: Dict[str, Any]) -> Dict[str, Any]:
    status = data.get("status", "UNKNOWN_ERROR")
    if status != "OK":
        return {"ok": False, "status": status, "error": data.get("error_message")}
    result = data["results"][0]
    location = result["geometry"]["location"]
    return {
        "ok": True,
        "formatted_address": result.get("formatted_address"),
        "lat": location["lat"],
        "lng": location["lng"],
        "place_id": result.get("place_id"),
        "components": _extract_components(result.get("address_components", [])),
    }


def _main() -> int:
    parser = argparse.ArgumentParser(description="Geocodificação Google Maps (direta/reversa)")
    parser.add_argument("--address", help="endereço em texto livre (geocodificação direta)")
    parser.add_argument("--lat", type=float, help="latitude (geocodificação reversa, precisa de --lng)")
    parser.add_argument("--lng", type=float, help="longitude (geocodificação reversa, precisa de --lat)")
    parser.add_argument("--json", action="store_true", default=True, help="saída JSON (default)")
    parser.add_argument("--text", action="store_true", help="resumo humano em texto")
    args = parser.parse_args()

    try:
        if args.address:
            result = geocode(args.address)
        elif args.lat is not None and args.lng is not None:
            result = reverse_geocode(args.lat, args.lng)
        else:
            parser.error("passe --address OU (--lat e --lng)")
            return 2
    except GeocodeError as e:
        result = {"ok": False, "error": str(e)}

    if args.text and not args.json:
        if result.get("ok"):
            print(f"{result['formatted_address']} ({result['lat']}, {result['lng']})")
        else:
            print(f"Erro: {result.get('error') or result.get('status')}")
    else:
        print(json.dumps(result, ensure_ascii=False))

    return 0 if result.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
