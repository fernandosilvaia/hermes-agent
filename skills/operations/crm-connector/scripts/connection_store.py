"""
connection_store.py - local, file-based store for named CRM connections
(base_url + auth config + api_key + a small map of named operations).

Same storage convention as the bundled ``google-workspace`` skill's
``google_token.json``/``google_client_secret.json`` (a JSON file persisted
under ``HERMES_HOME``, never hardcoded, never committed to the repo) - see
``skills/productivity/google-workspace/scripts/setup.py``. This module is
the multi-connection generalization of that same idea: instead of one fixed
token file, it keeps a dict of named connections in one JSON file.

Path: ``$HERMES_HOME/crm_connector/connections.json``
(overridable via ``CRM_CONNECTOR_STORE_PATH``). Written with permissions
``0600`` (owner read/write only) because it holds raw API keys - nothing
else in this repo's credentialed skills chmods their token files, but
storing secret material for an arbitrary, growing list of third-party CRMs
warrants the extra hardening.

Store shape (see SKILL.md for the full worked example):

    {
      "connections": {
        "<name>": {
          "base_url": "https://api.example.com",
          "auth": {"style": "header"|"bearer", "header_name": "apikey", "prefix": ""},
          "api_key": "...",
          "operations": {
            "<op_name>": {
              "method": "GET"|"POST"|"PUT"|"PATCH"|"DELETE",
              "path": "/leads/{id}",
              "body_template": {...} | null
            },
            ...
          },
          "created_at": "...",
          "updated_at": "..."
        }
      }
    }

Only stdlib. No network. No dependency on ``requests`` (that lives in
``crm_call.py``, imported lazily, so this module - and everything that only
needs to read/write connection config - never needs it installed).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _hermes_home import get_hermes_home  # noqa: E402

VALID_AUTH_STYLES = ("header", "bearer")
VALID_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE")
# Methods that always mean "this operation mutates the remote CRM" - see
# _crm_policy.infer_kind() for the fail-closed rule that a connection's
# config can never override (a "kind" field on the operation, if present,
# is documentation only; the method is what actually gates execution).
_NAME_RE_ALLOWED = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"


class ConnectionStoreError(RuntimeError):
    """Raised for corrupt/unreadable store files or invalid connection data.

    Fail-loud by design (same posture as WorkspaceAuthError in
    google-workspace-axtro/scripts/auth.py) - a silently-empty store would
    let a caller believe a connection doesn't exist when really the file is
    just corrupt.
    """


def default_store_path(env=None) -> Path:
    env = env if env is not None else os.environ
    override = (env.get("CRM_CONNECTOR_STORE_PATH") or "").strip()
    if override:
        return Path(override)
    return get_hermes_home() / "crm_connector" / "connections.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_store(path: Path | None = None, env=None) -> dict:
    """Load the whole store. Missing file -> empty store. Corrupt file ->
    ConnectionStoreError (fail-loud; never silently discards data)."""
    path = path if path is not None else default_store_path(env)
    if not path.is_file():
        return {"connections": {}}
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ConnectionStoreError(f"could not read connection store at {path}: {e}") from e
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ConnectionStoreError(f"connection store at {path} is not valid JSON: {e}") from e
    if not isinstance(data, dict) or not isinstance(data.get("connections"), dict):
        raise ConnectionStoreError(
            f"connection store at {path} has an unexpected shape (expected "
            "{'connections': {...}})"
        )
    return data


def save_store(store: dict, path: Path | None = None, env=None) -> Path:
    """Write the store atomically-ish (write-then-replace) with 0600
    permissions. Creates the parent directory if missing."""
    path = path if path is not None else default_store_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        # Best-effort - some filesystems (FAT, some CI sandboxes) don't
        # support unix perms; the file still only lives under HERMES_HOME.
        pass
    tmp.replace(path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path


def _valid_name(name: str) -> bool:
    return bool(name) and all(c in _NAME_RE_ALLOWED for c in name)


def validate_auth(auth: dict) -> list:
    errors = []
    if not isinstance(auth, dict):
        return ["auth must be an object"]
    style = auth.get("style")
    if style not in VALID_AUTH_STYLES:
        errors.append(f"auth.style must be one of {VALID_AUTH_STYLES}: {style!r}")
    if style == "header" and not (auth.get("header_name") or "").strip():
        errors.append("auth.style=='header' requires a non-empty auth.header_name")
    if "prefix" in auth and not isinstance(auth.get("prefix"), str):
        errors.append("auth.prefix must be a string when present")
    return errors


def validate_operation_def(op_def: dict) -> list:
    """Validate one operation mapping. Returns a list of error strings
    (empty = valid). Pure - no store/network access."""
    errors = []
    if not isinstance(op_def, dict):
        return ["operation definition must be an object"]
    method = op_def.get("method")
    if not isinstance(method, str) or method.upper() not in VALID_METHODS:
        errors.append(f"method must be one of {VALID_METHODS}: {method!r}")
    path = op_def.get("path")
    if not isinstance(path, str) or not path.startswith("/"):
        errors.append(f"path must be a string starting with '/': {path!r}")
    body_template = op_def.get("body_template")
    if body_template is not None and not isinstance(body_template, dict):
        errors.append("body_template must be an object (or omitted/null)")
    return errors


def _mask_key(api_key: str) -> str:
    s = api_key or ""
    if len(s) <= 4:
        return "*" * len(s) if s else ""
    return "*" * (len(s) - 4) + s[-4:]


def masked_view(connection: dict) -> dict:
    """Same connection dict with api_key redacted - safe to print/log."""
    view = dict(connection)
    view["api_key"] = _mask_key(connection.get("api_key", ""))
    return view


def list_connections(path: Path | None = None, env=None) -> list:
    store = load_store(path, env)
    return sorted(store["connections"].keys())


def get_connection(name: str, path: Path | None = None, env=None) -> dict | None:
    store = load_store(path, env)
    return store["connections"].get(name)


def upsert_connection(
    name: str,
    *,
    base_url: str,
    auth: dict,
    api_key: str,
    path: Path | None = None,
    env=None,
) -> dict:
    """Create or update a connection's credentials/base_url/auth. Preserves
    any operations already mapped for that name (register does not wipe
    them). Returns the stored (unmasked) connection dict."""
    if not _valid_name(name):
        raise ConnectionStoreError(
            f"invalid connection name {name!r} - use letters, digits, '_' or '-'"
        )
    if not base_url or not base_url.startswith(("http://", "https://")):
        raise ConnectionStoreError(f"base_url must start with http:// or https://: {base_url!r}")
    auth_errors = validate_auth(auth)
    if auth_errors:
        raise ConnectionStoreError("invalid auth config: " + "; ".join(auth_errors))
    if not api_key:
        raise ConnectionStoreError("api_key must not be empty")

    store = load_store(path, env)
    existing = store["connections"].get(name, {})
    now = _now()
    record = {
        "base_url": base_url.rstrip("/"),
        "auth": auth,
        "api_key": api_key,
        "operations": existing.get("operations", {}),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    store["connections"][name] = record
    save_store(store, path, env)
    return record


def remove_connection(name: str, path: Path | None = None, env=None) -> bool:
    store = load_store(path, env)
    if name not in store["connections"]:
        return False
    del store["connections"][name]
    save_store(store, path, env)
    return True


def set_operation(
    name: str,
    op_name: str,
    op_def: dict,
    path: Path | None = None,
    env=None,
) -> dict:
    """Add/replace one named operation mapping on an existing connection."""
    if not _valid_name(op_name):
        raise ConnectionStoreError(
            f"invalid operation name {op_name!r} - use letters, digits, '_' or '-'"
        )
    errors = validate_operation_def(op_def)
    if errors:
        raise ConnectionStoreError("invalid operation definition: " + "; ".join(errors))

    store = load_store(path, env)
    if name not in store["connections"]:
        raise ConnectionStoreError(
            f"unknown connection {name!r} - register it first (see manage_connection.py register)"
        )
    normalized = dict(op_def)
    normalized["method"] = normalized["method"].upper()
    store["connections"][name]["operations"][op_name] = normalized
    store["connections"][name]["updated_at"] = _now()
    save_store(store, path, env)
    return normalized


def remove_operation(name: str, op_name: str, path: Path | None = None, env=None) -> bool:
    store = load_store(path, env)
    conn = store["connections"].get(name)
    if not conn or op_name not in conn.get("operations", {}):
        return False
    del conn["operations"][op_name]
    conn["updated_at"] = _now()
    save_store(store, path, env)
    return True
