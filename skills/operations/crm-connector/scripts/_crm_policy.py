"""
_crm_policy.py - PURE decision logic for the crm-connector skill (no
network, no ``requests`` import - testable on the system python with zero
dependencies, same posture as
``skills/communication/telnyx-voice-sms/scripts/_send_policy.py`` and
``skills/operations/dispatch-job/scripts/_dispatch_policy.py``).

Covers three things:

  1. READ vs WRITE classification (``infer_kind``) - fail-closed: the HTTP
     method on the operation mapping is the ONLY thing that decides whether
     a call is a read or a write. A connection's config cannot mark a
     mutating verb (POST/PUT/PATCH/DELETE) as a "read" to skip the gate  - 
     GET/HEAD are the only methods ever classified as reads.

  2. The GATE PADRÃO (standard dry-run gate) for writes - same triple-gate
     idiom as dispatch-job's ``gate_allows_execute``: real network effect
     only with (a) --dry-run NOT passed, (b) HERMES_ALLOW_EXECUTE=="true",
     (c) CRM_CONNECTOR_ENABLED=="true". Missing any of the three -> dry-run.
     An explicit --dry-run always wins, even with both envs set.

  3. Safe URL/body templating - ``build_url``/``build_body`` substitute
     ``{placeholder}`` tokens from the caller-supplied params dict. Path
     placeholders are URL-encoded (``urllib.parse.quote``) before being
     spliced into the path, so a param value can never inject extra path
     segments or query parameters.
"""
from __future__ import annotations

import os
from urllib.parse import quote

SKILL_ENABLED_ENV = "CRM_CONNECTOR_ENABLED"
ALLOW_EXECUTE_ENV = "HERMES_ALLOW_EXECUTE"

READ_METHODS = ("GET", "HEAD")


def infer_kind(method: str) -> str:
    """"read" for GET/HEAD, "write" for everything else. Fail-closed: an
    unrecognized/malformed method is treated as "write" (never assume
    something unknown is safe)."""
    m = (method or "").strip().upper()
    return "read" if m in READ_METHODS else "write"


def gate_allows_execute(dry_run_flag: bool, env=None) -> bool:
    """GATE PADRÃO for writes. Real network effect only if all three:
      (a) --dry-run NOT passed (dry_run_flag is False),
      (b) HERMES_ALLOW_EXECUTE == "true",
      (c) CRM_CONNECTOR_ENABLED == "true".
    Missing any -> dry-run. --dry-run explicit ALWAYS wins."""
    if dry_run_flag:
        return False
    env = env if env is not None else os.environ
    allow = (env.get(ALLOW_EXECUTE_ENV, "") or "").strip().lower() == "true"
    enabled = (env.get(SKILL_ENABLED_ENV, "") or "").strip().lower() == "true"
    return allow and enabled


class TemplateError(ValueError):
    """A required {placeholder} was missing from the supplied params."""


def _placeholders(template: str) -> list:
    out = []
    i = 0
    while i < len(template):
        if template[i] == "{":
            j = template.find("}", i)
            if j == -1:
                break
            out.append(template[i + 1 : j])
            i = j + 1
        else:
            i += 1
    return out


def build_url(base_url: str, path_template: str, params: dict) -> str:
    """Substitute ``{name}`` placeholders in *path_template* from *params*,
    URL-encoding each substituted value, then join onto *base_url*.

    Raises TemplateError if a placeholder in the path has no matching
    param - fails closed rather than silently sending a malformed URL
    (e.g. ``/leads/{id}`` with no ``id`` given)."""
    missing = [p for p in _placeholders(path_template) if p not in (params or {})]
    if missing:
        raise TemplateError(
            "missing required path param(s) {}: for path template {!r}".format(
                ", ".join(missing), path_template
            )
        )

    def _sub(name: str) -> str:
        return quote(str(params[name]), safe="")

    path = path_template
    for name in _placeholders(path_template):
        path = path.replace("{" + name + "}", _sub(name), 1)
    return base_url.rstrip("/") + path


def _substitute_value(value, params: dict):
    """Body-template substitution: a string that is EXACTLY ``{name}``
    becomes the raw param value (type preserved - e.g. an int stays an
    int); a string that merely CONTAINS ``{name}`` gets str-interpolated.
    Dicts/lists recurse. Anything else passes through unchanged."""
    if isinstance(value, str):
        placeholders = _placeholders(value)
        if not placeholders:
            return value
        if len(placeholders) == 1 and value == "{" + placeholders[0] + "}":
            name = placeholders[0]
            if name not in params:
                raise TemplateError(f"missing required body param: {name!r}")
            return params[name]
        out = value
        for name in placeholders:
            if name not in params:
                raise TemplateError(f"missing required body param: {name!r}")
            out = out.replace("{" + name + "}", str(params[name]))
        return out
    if isinstance(value, dict):
        return {k: _substitute_value(v, params) for k, v in value.items()}
    if isinstance(value, list):
        return [_substitute_value(v, params) for v in value]
    return value


def build_body(body_template, params: dict):
    """Render a body_template against params. None template -> None body."""
    if body_template is None:
        return None
    return _substitute_value(body_template, params or {})


class AuthError(ValueError):
    pass


def build_auth_headers(auth: dict, api_key: str) -> dict:
    """Build the auth header(s) for a request from a connection's ``auth``
    config + its api_key.

      style == "bearer" -> {"Authorization": "<prefix><api_key>"} with
                            prefix defaulting to "Bearer ".
      style == "header"  -> {"<header_name>": "<prefix><api_key>"} with
                            prefix defaulting to "" (raw key value) - matches
                            Aurora Solar's own auth style (see
                            aurora-read.ts: Bearer token) and the generic
                            "apikey" header some CRMs use instead.
    """
    style = (auth or {}).get("style")
    if style == "bearer":
        prefix = auth.get("prefix", "Bearer ")
        return {"Authorization": f"{prefix}{api_key}"}
    if style == "header":
        header_name = (auth.get("header_name") or "").strip()
        if not header_name:
            raise AuthError("auth.style=='header' requires auth.header_name")
        prefix = auth.get("prefix", "")
        return {header_name: f"{prefix}{api_key}"}
    raise AuthError(f"unknown auth.style: {style!r}")
