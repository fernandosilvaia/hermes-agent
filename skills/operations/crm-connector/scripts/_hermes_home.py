"""Resolve HERMES_HOME for standalone skill scripts.

Skill scripts may run outside the Hermes process (e.g. system Python,
nix env, CI) where ``hermes_constants`` is not importable. This module
provides the same ``get_hermes_home()`` contract as ``hermes_constants``
without requiring it on ``sys.path``.

When ``hermes_constants`` IS available it is used directly so that any
future enhancements (profile resolution, Docker detection, etc.) are
picked up automatically. The fallback path replicates the core logic
from ``hermes_constants.py`` using only the stdlib.

Same pattern as ``skills/productivity/google-workspace/scripts/_hermes_home.py``
 -  copied rather than imported cross-skill because skills are meant to be
self-contained (each can be installed/synced independently).
"""

from __future__ import annotations

import os
from pathlib import Path

try:
    from hermes_constants import get_hermes_home as get_hermes_home
except Exception:
    # Broad on purpose (not just ModuleNotFoundError/ImportError): under the
    # system Python this repo's pure/no-network tests are meant to run on
    # (3.9.x, see telnyx-voice-sms's test_send_policy.py docstring),
    # hermes_constants.py itself fails to IMPORT with a TypeError (its
    # `ContextVar[str | object]` module-level annotation uses PEP 604 syntax
    # evaluated eagerly, which requires 3.10+) rather than raising
    # ImportError. Falling back to the stdlib-only implementation below on
    # ANY import-time failure keeps this module usable on any Python this
    # skill's own tests need to run under.

    def get_hermes_home() -> Path:
        """Return the Hermes home directory (default: ~/.hermes).

        Mirrors ``hermes_constants.get_hermes_home()``."""
        val = os.environ.get("HERMES_HOME", "").strip()
        return Path(val) if val else Path.home() / ".hermes"
