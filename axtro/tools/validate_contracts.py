#!/usr/bin/env python3
"""validate_contracts.py — Validador do registry de skills Axtro.

Varre skills/**/contract.json e valida cada um contra o CONTRACT_SCHEMA.json
(validação hand-rolled em stdlib — sem dependência de jsonschema, roda em
qualquer Python 3.9+). Também aplica invariantes de segurança que um schema
sozinho não expressa:

  I1. enabled=true exige activation_stage="production" E production_ready=true.
  I2. production_ready=true exige tests/ não-vazio na skill.
  I3. autonomy_ring >= 2 exige human_gates não-vazio.
  I4. credentials são NOMES (padrão ENV_VAR); qualquer valor suspeito
      (contém '=', espaço, ou >64 chars) é erro.
  I5. ids únicos no registry inteiro.
  I6. default_model != "none" exige max_daily_cost_usd > 0.

Uso:
    python3 axtro/tools/validate_contracts.py            # texto humano
    python3 axtro/tools/validate_contracts.py --json     # JSON p/ máquina
    python3 axtro/tools/validate_contracts.py --dry-run  # alias de leitura (a
                                                          # ferramenta já é 100% read-only)

Exit code: 0 = tudo válido; 1 = pelo menos um erro.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "axtro" / "CONTRACT_SCHEMA.json"
SKILLS_DIR = REPO / "skills"

RING_MAX = 3
COST_MAX = 50.0
MODEL_ENUM = {"none", "haiku", "sonnet", "opus", "claude-code", "codex"}
LOCATION_ENUM = {"macbook", "vps", "both"}
STAGE_ENUM = {"scaffold", "staging", "production"}

REQUIRED = [
    "id", "name", "owner_agent", "execution_location", "default_model",
    "autonomy_ring", "tools", "credentials", "max_daily_cost_usd",
    "inputs", "outputs", "stop_conditions", "telemetry_events",
    "enabled", "production_ready", "activation_stage",
]


def _err(errors, path, msg):
    errors.append({"contract": str(path.relative_to(REPO)), "error": msg})


def validate_contract(path: Path, errors: list) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        _err(errors, path, f"JSON inválido: {e}")
        return None

    for field in REQUIRED:
        if field not in data:
            _err(errors, path, f"campo obrigatório ausente: {field}")

    # Tipos e enums (só valida o que existe; ausência já foi reportada)
    if "id" in data and (not isinstance(data["id"], str) or not data["id"].replace("_", "").isalnum() or data["id"] != data["id"].lower()):
        _err(errors, path, f"id deve ser snake_case minúsculo: {data.get('id')!r}")
    if "execution_location" in data and data["execution_location"] not in LOCATION_ENUM:
        _err(errors, path, f"execution_location inválido: {data['execution_location']!r} (aceitos: {sorted(LOCATION_ENUM)})")
    if "default_model" in data and data["default_model"] not in MODEL_ENUM:
        _err(errors, path, f"default_model inválido: {data['default_model']!r} (aceitos: {sorted(MODEL_ENUM)})")
    if "autonomy_ring" in data:
        ring = data["autonomy_ring"]
        if not isinstance(ring, int) or not (0 <= ring <= RING_MAX):
            _err(errors, path, f"autonomy_ring deve ser inteiro 0..{RING_MAX} (anel 4 é proibido, não contratável): {ring!r}")
    if "activation_stage" in data and data["activation_stage"] not in STAGE_ENUM:
        _err(errors, path, f"activation_stage inválido: {data['activation_stage']!r}")
    if "max_daily_cost_usd" in data:
        cost = data["max_daily_cost_usd"]
        if not isinstance(cost, (int, float)) or cost < 0 or cost > COST_MAX:
            _err(errors, path, f"max_daily_cost_usd deve ser 0..{COST_MAX}: {cost!r}")
    for list_field in ("tools", "credentials", "inputs", "outputs", "stop_conditions", "telemetry_events"):
        if list_field in data and not isinstance(data[list_field], list):
            _err(errors, path, f"{list_field} deve ser lista")
    if isinstance(data.get("stop_conditions"), list) and len(data["stop_conditions"]) == 0:
        _err(errors, path, "stop_conditions vazio — toda skill precisa de pelo menos uma condição de parada")
    if isinstance(data.get("telemetry_events"), list) and len(data["telemetry_events"]) == 0:
        _err(errors, path, "telemetry_events vazio — toda skill precisa emitir pelo menos um evento")

    # ── Invariantes de segurança ──────────────────────────────────────────
    if data.get("enabled") is True:
        if data.get("activation_stage") != "production" or data.get("production_ready") is not True:
            _err(errors, path, "I1: enabled=true exige activation_stage='production' E production_ready=true")

    if data.get("production_ready") is True:
        tests_dir = path.parent / "tests"
        has_tests = tests_dir.is_dir() and any(tests_dir.glob("test_*.py"))
        if not has_tests:
            _err(errors, path, "I2: production_ready=true exige tests/test_*.py na skill")

    if isinstance(data.get("autonomy_ring"), int) and data["autonomy_ring"] >= 2:
        if not data.get("human_gates"):
            _err(errors, path, "I3: autonomy_ring >= 2 exige human_gates não-vazio")

    for cred in data.get("credentials", []) or []:
        if not isinstance(cred, str) or "=" in cred or " " in cred or len(cred) > 64 or cred != cred.upper():
            _err(errors, path, f"I4: credencial deve ser NOME de env var (MAIÚSCULA, sem valor): {str(cred)[:40]!r}")

    if data.get("default_model") not in (None, "none") and data.get("max_daily_cost_usd") == 0:
        _err(errors, path, "I6: skill que usa LLM (default_model != none) precisa de max_daily_cost_usd > 0")

    return data


def main():
    parser = argparse.ArgumentParser(description="Valida todos os contract.json das skills Axtro")
    parser.add_argument("--json", action="store_true", help="saída JSON")
    parser.add_argument("--text", action="store_true", help="saída texto (padrão)")
    parser.add_argument("--dry-run", action="store_true", help="no-op: a ferramenta já é somente leitura")
    args = parser.parse_args()

    contracts = sorted(SKILLS_DIR.rglob("contract.json"))
    errors: list = []
    seen_ids: dict = {}
    validated = []

    for path in contracts:
        data = validate_contract(path, errors)
        if data and "id" in data:
            if data["id"] in seen_ids:
                _err(errors, path, f"I5: id duplicado '{data['id']}' (também em {seen_ids[data['id']]})")
            else:
                seen_ids[data["id"]] = str(path.relative_to(REPO))
            validated.append({
                "id": data.get("id"),
                "path": str(path.relative_to(REPO)),
                "ring": data.get("autonomy_ring"),
                "stage": data.get("activation_stage"),
                "enabled": data.get("enabled"),
                "production_ready": data.get("production_ready"),
            })

    result = {
        "total_contracts": len(contracts),
        "valid": len(contracts) - len({e["contract"] for e in errors}),
        "errors": errors,
        "skills": validated,
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"📋 Registry Axtro — {result['total_contracts']} contrato(s), {len(errors)} erro(s)")
        for s in validated:
            flag = "🟢" if not any(e["contract"] == s["path"] for e in errors) else "🔴"
            print(f"  {flag} {s['id']} · anel {s['ring']} · {s['stage']} · enabled={s['enabled']}")
        for e in errors:
            print(f"  ❌ {e['contract']}: {e['error']}")

    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
