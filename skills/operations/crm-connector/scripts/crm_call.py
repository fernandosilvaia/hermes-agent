#!/usr/bin/env python3
"""
crm_call.py - call a named operation on a named, previously-registered CRM
connection (see ``manage_connection.py``). This is the generic "plumbing"
piece: it never assumes anything about what a CRM looks like - it only
knows how to make the HTTP call a human already mapped, under a name, for a
specific connection.

READ vs WRITE (see ``_crm_policy.infer_kind`` - decided by HTTP method,
never overridable by config):
  - reads (GET/HEAD, e.g. list_leads/get_lead) are freely callable - they
    hit the real API immediately, no gate. --dry-run still works as an
    explicit preview (no network) if you want to check the resolved
    URL/body first.
  - writes (POST/PUT/PATCH/DELETE, e.g. update_stage/move_pipeline) default
    to dry-run. A real write only happens with --execute AND
    HERMES_ALLOW_EXECUTE=true AND CRM_CONNECTOR_ENABLED=true. --dry-run
    explicit always wins, even with both envs set.

Usage:
    # reads - execute immediately by default
    python crm_call.py --connection ecoloop --operation list_leads
    python crm_call.py --connection ecoloop --operation get_lead --param id=123
    python crm_call.py --connection ecoloop --operation get_lead --param id=123 --dry-run   # preview only

    # writes - dry-run by default
    python crm_call.py --connection ecoloop --operation update_stage \\
        --param id=123 --param stage=won
    # -> {"dry_run": true, "would_call": {...}}   (nothing sent)

    # real write - needs BOTH gate envs + --execute
    HERMES_ALLOW_EXECUTE=true CRM_CONNECTOR_ENABLED=true \\
      python crm_call.py --connection ecoloop --operation update_stage \\
        --param id=123 --param stage=won --execute

Env:
    HERMES_ALLOW_EXECUTE     global execution gate - "true" to allow real writes
    CRM_CONNECTOR_ENABLED    this skill's gate - "true" to allow real writes
    CRM_CONNECTOR_STORE_PATH override for the connection store path (see connection_store.py)
    CRM_CONNECTOR_AUDIT_PATH override for the audit log path (default under HERMES_HOME)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import connection_store as store  # noqa: E402
import _crm_policy as policy  # noqa: E402
from _hermes_home import get_hermes_home  # noqa: E402

_REDACTED = "***REDACTED***"


def _audit_path(env=None) -> Path:
    env = env if env is not None else os.environ
    override = (env.get("CRM_CONNECTOR_AUDIT_PATH") or "").strip()
    if override:
        return Path(override)
    return get_hermes_home() / "crm_connector" / "audit.log"


def _audit(env, connection_name, operation_name, kind, *, dry_run, executed, blocked=False) -> None:
    """Best-effort append-only audit trail. NEVER includes api_key, request
    body, or response body - only what happened, not the data involved."""
    rec = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "connection": connection_name,
        "operation": operation_name,
        "kind": kind,
        "dry_run": dry_run,
        "executed": executed,
        "blocked": blocked,
    }
    try:
        p = _audit_path(env)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass  # audit is best-effort; must never break the main flow


def _redact_headers(headers: dict) -> dict:
    return {k: _REDACTED for k in headers}


def _do_request(method: str, url: str, headers: dict, body, timeout: int) -> dict:
    """EFEITO REAL - only ever called once a gate has already allowed it
    (reads: always; writes: only after gate_allows_execute is True). Imports
    ``requests`` lazily so the rest of this module works without it
    installed (mirrors dispatch_job.py/_send_policy.py's lazy-import
    convention)."""
    import requests

    kwargs = {"headers": dict(headers), "timeout": timeout}
    if body is not None:
        kwargs["json"] = body
    resp = requests.request(method, url, **kwargs)
    try:
        parsed_body = resp.json()
    except ValueError:
        parsed_body = resp.text
    return {"status_code": resp.status_code, "body": parsed_body}


def call_operation(
    connection_name: str,
    operation_name: str,
    params: dict | None = None,
    *,
    dry_run: bool | None = None,
    env=None,
    store_path: Path | None = None,
    timeout: int = 20,
) -> dict:
    """Resolve *connection_name*/*operation_name* against the connection
    store and (subject to the read/write gate) make the call.

    ``dry_run``:
      True  -> always preview, never touch the network (explicit, always wins).
      False -> attempt the real call (reads: always succeed in doing so;
               writes: still subject to gate_allows_execute).
      None  -> per-kind default: reads execute, writes preview.

    Never raises on a "normal" bad-input path (unknown connection/operation,
    missing template param) - returns a ``{"blocked": True, "reason": ...}``
    dict instead, same fail-soft-but-informative posture as dispatch_job's
    ``plan_dispatch``. Network/auth failures from ``_do_request`` DO
    propagate (caller/CLI reports them), since a live HTTP error is real
    signal, not a policy decision.
    """
    env = env if env is not None else os.environ
    params = params or {}

    conn = store.get_connection(connection_name, store_path, env)
    if conn is None:
        return {
            "blocked": True,
            "reason": f"unknown connection {connection_name!r}",
            "available_connections": store.list_connections(store_path, env),
        }

    op_def = conn.get("operations", {}).get(operation_name)
    if op_def is None:
        return {
            "blocked": True,
            "reason": f"unknown operation {operation_name!r} on connection {connection_name!r}",
            "available_operations": sorted(conn.get("operations", {}).keys()),
        }

    method = op_def["method"]
    kind = policy.infer_kind(method)

    try:
        url = policy.build_url(conn["base_url"], op_def["path"], params)
        headers = policy.build_auth_headers(conn["auth"], conn["api_key"])
        body = policy.build_body(op_def.get("body_template"), params)
    except (policy.TemplateError, policy.AuthError) as e:
        return {"blocked": True, "reason": str(e)}

    would_call = {
        "method": method, "url": url,
        "headers": _redact_headers(headers), "body": body,
    }

    # Effective "explicit dry-run requested" flag, honoring the per-kind
    # default when the caller passed dry_run=None.
    explicit_dry_run = (kind == "write") if dry_run is None else dry_run

    if kind == "read":
        if explicit_dry_run:
            return {"dry_run": True, "kind": "read", "executed": False, "would_call": would_call}
        result = _do_request(method, url, headers, body, timeout)
        _audit(env, connection_name, operation_name, kind, dry_run=False, executed=True)
        return {"dry_run": False, "kind": "read", "executed": True, "result": result}

    # kind == "write"
    if policy.gate_allows_execute(explicit_dry_run, env):
        result = _do_request(method, url, headers, body, timeout)
        _audit(env, connection_name, operation_name, kind, dry_run=False, executed=True)
        return {"dry_run": False, "kind": "write", "executed": True, "blocked": False, "result": result}

    _audit(env, connection_name, operation_name, kind, dry_run=True, executed=False)
    return {
        "dry_run": True, "kind": "write", "executed": False, "blocked": False,
        "would_call": would_call,
        "note": (
            "DRY-RUN - nothing sent. Real write needs --execute AND "
            "HERMES_ALLOW_EXECUTE=true AND CRM_CONNECTOR_ENABLED=true. "
            "--dry-run explicit always wins."
        ),
    }


def _parse_params(pairs) -> dict:
    out = {}
    for item in pairs:
        if "=" not in item:
            raise SystemExit(f"--param must be key=value: {item!r}")
        k, v = item.split("=", 1)
        out[k] = v
    return out


def _cli(argv=None):
    p = argparse.ArgumentParser(
        description="Call a named operation on a named CRM connection (dry-run by default for writes)"
    )
    p.add_argument("--connection", required=True)
    p.add_argument("--operation", required=True)
    p.add_argument("--param", action="append", default=[], help="key=value, may repeat")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--execute", action="store_true", help="attempt the real call (writes still need both gate envs)")
    mode.add_argument("--dry-run", action="store_true", help="force preview, never touch the network (always wins)")
    p.add_argument("--timeout", type=int, default=20)
    args = p.parse_args(argv)

    if args.dry_run:
        dry_run = True
    elif args.execute:
        dry_run = False
    else:
        dry_run = None

    try:
        result = call_operation(
            args.connection, args.operation, _parse_params(args.param),
            dry_run=dry_run, timeout=args.timeout,
        )
    except store.ConnectionStoreError as e:
        result = {"blocked": True, "reason": str(e)}

    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("blocked"):
        sys.exit(2)


if __name__ == "__main__":
    _cli()
