#!/usr/bin/env python3
"""dispatch_guard.py — the missing hook: wires the LIVE daemon execution path
into the existing, already-tested governance engine (autonomy_core, via
axtro/tools/contract_preflight.py).

THE GAP THIS CLOSES
--------------------
``axtro/skill_runner.py`` is the intended single chokepoint for governed-skill
execution ("run_skill() ... CHOKEPOINT: decisão de autonomia ANTES de
qualquer spawn"). In practice nothing in the live daemon ever calls it: when
the gateway's own tool-use loop decides to run a skill's script, it does so
via the generic ``terminal`` tool (``tools/terminal_tool.terminal_tool``),
which never imported skill_runner / autonomy_core / contract_guard at all —
confirmed by a repo-wide grep across gateway/, agent/, hermes_cli/,
toolsets.py, cron/. The only thing stopping a disabled/killed governed skill
from actually running was the hand-written env-var double-check duplicated
inside each governed script's own ``scripts/*.py`` — real defense-in-depth,
but not a substitute for the centralized contract.json enforcement that
already existed and was already fully tested, just never wired in.

This module is called from exactly ONE place: the top of
``tools/terminal_tool.terminal_tool()``, before any backend
(local/docker/ssh/modal/...) is even selected — i.e. before any subprocess of
any kind could be created for that call. It does nothing (``check()`` returns
``None``) unless the command can be confidently tied to a governed skill's
own script (one listed in ``axtro/GOVERNED_SKILLS.txt``, invoked directly
under ``<skill_dir>/scripts/``). Every other terminal command — the
overwhelming majority — is completely unaffected: same behavior, same
performance, exactly as before this module existed.

DETECTION IS DELIBERATELY CONSERVATIVE
---------------------------------------
It only matches a command that runs the script directly via a known
interpreter (python/python3/bash/sh/zsh/node) or direct execution
(``./scripts/x.py``). A command that merely *mentions* a governed skill's
path — ``cat contract.json``, ``ls skills/...``, editing SKILL.md, grep,
etc. — does NOT match, so normal inspection/dev workflows (including a human
running the CLI directly) are untouched.

If the detection heuristic itself throws (malformed shell quoting, an
unexpected path shape, ...) it treats the command as unmatched rather than
blocking a command it failed to parse — a bug in this module must never turn
into "the daemon can no longer run any terminal command." That is a
deliberate fail-OPEN at the *detection* step only. Once a command IS matched
to a governed skill, the actual allow/block/dry-run decision is delegated to
``axtro/tools/contract_preflight.preflight_decision()`` — the same
fail-CLOSED decision function already used by the CLI preflight and by
``skill_runner.py``. Any error past that point still blocks (fail-closed),
exactly like every other governed-skill code path in this repo.

Scope note: this recognizes a governed skill invoked from *any* of the
roots ``contract_preflight._candidate_roots()`` knows about — the repo
checkout (``REPO``, dev/CLI usage), the live ``HERMES_HOME/skills`` (default
profile, the actual Docker production layout), or a named profile's
``HERMES_HOME/profiles/<name>/skills``. See ``_governed_roots()`` below.
"""
from __future__ import annotations

import os
import re
import shlex
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_AXTRO_DIR = Path(__file__).resolve().parent
_TOOLS_DIR = _AXTRO_DIR / "tools"
for _p in (str(_AXTRO_DIR), str(_TOOLS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import contract_preflight as pf  # noqa: E402  (fail-closed decision + governed set)

# Interpreters we recognize as "this segment directly runs the following
# path". Deliberately small and explicit — anything else (a wrapper script,
# a Makefile target, a Docker CLI invocation, ...) is NOT matched, which
# means it passes through unaffected (fail-open on detection, see module
# docstring).
_INTERPRETERS = {
    "python", "python3", "python3.10", "python3.11", "python3.12", "python3.13",
    "bash", "sh", "zsh", "node",
}
# Splits a compound shell command into individual segments while keeping the
# operators, so a match can be spliced back in without disturbing the rest of
# the command (used to inject --dry-run into only the matched segment).
_OPERATOR_RE = re.compile(r"(&&|\|\||[;|\n])")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _governed_roots() -> dict:
    """{repo-relative governed-skill path: [resolved absolute Path, ...]}.

    Each governed skill can be physically present under more than one root
    at once: the repo checkout (dev/CLI), the live ``HERMES_HOME/skills``
    (Docker production, default profile), and/or a named profile's
    ``HERMES_HOME/profiles/<name>/skills`` — see
    ``contract_preflight._candidate_roots()`` for the authoritative list and
    why order matters. A command invoking ANY of these physical copies must
    resolve to the same governed key and get checked against the same
    contract.json.

    Not cached — ``axtro/GOVERNED_SKILLS.txt`` is a handful of lines and
    ``contract_preflight`` itself re-reads on every call; a human editing the
    allowlist should take effect immediately, same as everywhere else.
    """
    bases = pf._candidate_roots()
    roots: dict = {}
    for rel in pf._governed_set():
        candidates = []
        seen = set()
        for base in bases:
            try:
                resolved = (base / rel).resolve()
            except Exception:
                continue
            if resolved not in seen:
                seen.add(resolved)
                candidates.append(resolved)
        roots[rel] = candidates
    return roots


def _script_token(segment: str):
    """Return (path_token, rest_args) this shell segment directly executes,
    honoring a leading interpreter (python/bash/.../node) or direct exec.

    Returns (None, []) for anything that isn't confidently a single direct
    invocation (empty segment, unmatched quoting, env-assignment-only, ...).
    """
    segment = segment.strip()
    if not segment:
        return None, []
    try:
        tokens = shlex.split(segment, posix=True)
    except ValueError:
        return None, []
    i = 0
    while i < len(tokens) and _ENV_ASSIGN_RE.match(tokens[i]):
        i += 1
    if i < len(tokens) and tokens[i] in ("sudo", "exec"):
        i += 1
    tokens = tokens[i:]
    if not tokens:
        return None, []
    head = tokens[0]
    head_name = Path(head).name
    if head_name in _INTERPRETERS:
        if len(tokens) < 2:
            return None, []
        return tokens[1], tokens[2:]
    return head, tokens[1:]


def _resolve(path_str: str, base: str | None) -> Path | None:
    try:
        p = Path(os.path.expanduser(path_str))
        if not p.is_absolute():
            p = (Path(base) if base else Path.cwd()) / p
        return p.resolve()
    except Exception:
        return None


def _match_governed_skill(command: str, workdir: str | None, governed_roots=None):
    """Best-effort scan of *command* for a direct invocation of a governed
    skill's own script (under ``<skill_dir>/scripts/``).

    Returns a dict {"rel", "skill_dir", "script_argv", "parts", "segment_index"}
    or ``None``. Never raises — any unexpected error is treated as "no match"
    (see module docstring: detection fails open).
    """
    try:
        roots = (governed_roots() if callable(governed_roots)
                 else governed_roots) if governed_roots is not None else _governed_roots()
        if not roots:
            return None
        parts = _OPERATOR_RE.split(command)
        for idx in range(0, len(parts), 2):
            token, rest = _script_token(parts[idx])
            if not token:
                continue
            resolved = _resolve(token, workdir)
            if resolved is None:
                continue
            for rel, root_or_roots in roots.items():
                # A governed skill may resolve to more than one root (repo
                # checkout + HERMES_HOME + named profiles — see
                # _governed_roots()). Callers (including tests, and the
                # `governed_roots` override) may instead pass a single Path
                # per rel — accept both shapes.
                candidate_roots = (
                    root_or_roots if isinstance(root_or_roots, (list, tuple))
                    else [root_or_roots]
                )
                for root in candidate_roots:
                    # Normalize defensively — callers (including tests) may
                    # pass an unresolved path (e.g. a macOS /var/folders/...
                    # tempdir that is itself a symlink to /private/var/...),
                    # which would otherwise silently fail to match against
                    # `resolved`.
                    try:
                        root = Path(root).resolve()
                    except Exception:
                        continue
                    try:
                        rel_to_root = resolved.relative_to(root)
                    except ValueError:
                        continue
                    if rel_to_root.parts and rel_to_root.parts[0] == "scripts":
                        return {
                            "rel": rel,
                            "skill_dir": root,
                            "script_argv": [str(rel_to_root)] + rest,
                            "parts": parts,
                            "segment_index": idx,
                        }
        return None
    except Exception:
        return None


def _with_dry_run(parts: list, segment_index: int) -> str:
    """Return the full command with ``--dry-run`` appended to the matched
    segment only (leaving the rest of a compound command untouched)."""
    segment = parts[segment_index]
    try:
        already = "--dry-run" in shlex.split(segment, posix=True)
    except ValueError:
        already = "--dry-run" in segment
    if already:
        return "".join(parts)
    # Preserve trailing whitespace between the segment and the next operator
    # (the split regex keeps operators as separate elements, so naively
    # rstripping the segment would swallow the space before e.g. " && ").
    stripped = segment.rstrip()
    trailing_ws = segment[len(stripped):]
    new_parts = list(parts)
    new_parts[segment_index] = stripped + " --dry-run" + trailing_ws
    return "".join(new_parts)


def check(command: str, workdir: str | None = None, env=None, *, governed_roots=None) -> dict | None:
    """Called once, at the top of ``terminal_tool()``, before any backend is
    selected.

    Returns ``None`` for anything that isn't a direct invocation of a
    governed skill's own script — the normal case, meaning zero behavior
    change for the caller.

    Otherwise returns a dict:
      ``{"action": "block", "mode": "blocked"|"killed", "message": str, "skill": str}``
      ``{"action": "dry_run", "mode": "dry_run", "message": str, "skill": str,
         "command": <rewritten command str, --dry-run injected>}``
      ``{"action": "allow", "mode": "staging"|"production", "message": str, "skill": str}``

    ``governed_roots`` overrides the default (real ``GOVERNED_SKILLS.txt``)
    lookup — used by tests to point at fixtures without touching the repo's
    real allowlist.
    """
    match = _match_governed_skill(command, workdir, governed_roots=governed_roots)
    if match is None:
        return None

    # Governance was already established by _match_governed_skill (against
    # either the real GOVERNED_SKILLS.txt or an injected `governed_roots` for
    # tests) — tell preflight_decision to trust that instead of re-deriving
    # it from the real allowlist file, which would wrongly say "native
    # pass-through" for any test fixture that isn't in the real file.
    decision = pf.preflight_decision(
        match["skill_dir"],
        env=env if env is not None else os.environ,
        is_governed=lambda _rel, _sdir: True,
    )
    mode = decision["mode"]
    result = {
        "mode": mode,
        "message": decision["msg"],
        "skill": match["rel"],
    }
    if mode in ("blocked", "killed"):
        result["action"] = "block"
    elif mode == "dry_run":
        result["action"] = "dry_run"
        result["command"] = _with_dry_run(match["parts"], match["segment_index"])
    else:  # staging / production
        result["action"] = "allow"
    return result
