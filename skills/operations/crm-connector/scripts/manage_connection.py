#!/usr/bin/env python3
"""
manage_connection.py - register/inspect/remove named CRM connections and
their operation mappings. Pure local config management: writes only to the
connection store (``connection_store.py``), NEVER touches the network. Not
gated by --execute/HERMES_ALLOW_EXECUTE - same posture as
``skills/productivity/google-workspace/scripts/setup.py --client-secret``
(storing a credential locally is not itself an external action).

Typical flow (see SKILL.md for the full worked "Ecoloop CRM" example):

    # 1. Register the connection (base URL + how to authenticate):
    python manage_connection.py register --name ecoloop \\
        --base-url https://api.ecoloopcrm.com \\
        --auth-style header --header-name apikey \\
        --api-key sk_live_xxx

    # 2. Map the operations this connection understands:
    python manage_connection.py set-operation --name ecoloop \\
        --operation list_leads --method GET --path /leads
    python manage_connection.py set-operation --name ecoloop \\
        --operation update_stage --method PATCH --path /leads/{id} \\
        --body '{"stage": "{stage}"}'

    # 3. Inspect (api_key always masked):
    python manage_connection.py list
    python manage_connection.py show --name ecoloop

    # 4. Remove:
    python manage_connection.py remove-operation --name ecoloop --operation update_stage
    python manage_connection.py remove --name ecoloop

The API key can be supplied three ways (in order of preference for a chat
transcript that might be logged/persisted):
    --api-key-env VAR      read from the named process env var (best - the
                            raw key never appears in argv/history at all)
    --api-key-stdin        read one line from stdin
    --api-key VALUE        raw value as an argument (simplest; ends up in
                            shell history / process listing like any CLI
                            secret argument in this repo, e.g. hermes-purchase's
                            --approval-token)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import connection_store as store  # noqa: E402


def _emit(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _resolve_api_key(args, env) -> str:
    if args.api_key_env:
        val = env.get(args.api_key_env, "")
        if not val:
            raise SystemExit(f"env var {args.api_key_env!r} is empty/unset")
        return val
    if args.api_key_stdin:
        val = sys.stdin.readline().rstrip("\n")
        if not val:
            raise SystemExit("no api key read from stdin")
        return val
    if args.api_key:
        return args.api_key
    raise SystemExit("one of --api-key, --api-key-env, --api-key-stdin is required")


def cmd_register(args, env=None) -> dict:
    env = env if env is not None else os.environ
    api_key = _resolve_api_key(args, env)
    auth = {"style": args.auth_style}
    if args.auth_style == "header":
        auth["header_name"] = args.header_name or ""
    if args.prefix is not None:
        auth["prefix"] = args.prefix
    record = store.upsert_connection(
        args.name, base_url=args.base_url, auth=auth, api_key=api_key,
    )
    return {"registered": True, "name": args.name, "connection": store.masked_view(record)}


def cmd_set_operation(args, env=None) -> dict:
    op_def = {"method": args.method, "path": args.path}
    if args.body is not None:
        try:
            op_def["body_template"] = json.loads(args.body)
        except json.JSONDecodeError as e:
            raise SystemExit(f"--body must be valid JSON: {e}") from e
    normalized = store.set_operation(args.name, args.operation, op_def)
    return {"set": True, "name": args.name, "operation": args.operation, "definition": normalized}


def cmd_remove_operation(args, env=None) -> dict:
    removed = store.remove_operation(args.name, args.operation)
    return {"removed": removed, "name": args.name, "operation": args.operation}


def cmd_list(args, env=None) -> dict:
    return {"connections": store.list_connections()}


def cmd_show(args, env=None) -> dict:
    conn = store.get_connection(args.name)
    if conn is None:
        return {"found": False, "name": args.name}
    return {"found": True, "name": args.name, "connection": store.masked_view(conn)}


def cmd_remove(args, env=None) -> dict:
    removed = store.remove_connection(args.name)
    return {"removed": removed, "name": args.name}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Register/inspect/remove named CRM connections (local config only, no network)"
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register", help="create or update a named connection's credentials")
    reg.add_argument("--name", required=True)
    reg.add_argument("--base-url", required=True)
    reg.add_argument("--auth-style", required=True, choices=list(store.VALID_AUTH_STYLES))
    reg.add_argument("--header-name", default=None, help="required when --auth-style header")
    reg.add_argument("--prefix", default=None, help='value prefix, e.g. "Bearer " (default depends on style)')
    key_group = reg.add_mutually_exclusive_group(required=True)
    key_group.add_argument("--api-key", default=None)
    key_group.add_argument("--api-key-env", default=None)
    key_group.add_argument("--api-key-stdin", action="store_true")

    setop = sub.add_parser("set-operation", help="map a named operation onto a connection")
    setop.add_argument("--name", required=True)
    setop.add_argument("--operation", required=True)
    setop.add_argument("--method", required=True, choices=list(store.VALID_METHODS))
    setop.add_argument("--path", required=True, help="e.g. /leads/{id}")
    setop.add_argument("--body", default=None, help="JSON body template, e.g. '{\"stage\": \"{stage}\"}'")

    rmop = sub.add_parser("remove-operation", help="remove one operation mapping")
    rmop.add_argument("--name", required=True)
    rmop.add_argument("--operation", required=True)

    sub.add_parser("list", help="list registered connection names")

    show = sub.add_parser("show", help="show one connection (api_key masked)")
    show.add_argument("--name", required=True)

    rm = sub.add_parser("remove", help="delete a connection entirely")
    rm.add_argument("--name", required=True)

    return p


_HANDLERS = {
    "register": cmd_register,
    "set-operation": cmd_set_operation,
    "remove-operation": cmd_remove_operation,
    "list": cmd_list,
    "show": cmd_show,
    "remove": cmd_remove,
}


def _cli(argv=None):
    args = _build_parser().parse_args(argv)
    handler = _HANDLERS[args.cmd]
    try:
        result = handler(args)
    except store.ConnectionStoreError as e:
        _emit({"error": str(e)})
        sys.exit(2)
    _emit(result)


if __name__ == "__main__":
    _cli()
