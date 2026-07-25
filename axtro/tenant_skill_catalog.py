"""Fail-closed mapping from an Axtro Agent company's connectors/plan to the
hermes-agent skills a multiplexed CLIENT profile is allowed to see.

Consumed by ``axtro/bridge_sync.py`` (Fase 4) to generate a profile's
``.skills_allowlist`` — a skill not reachable from ``TENANT_BASE_SKILLS`` or
``CONNECTOR_SKILL_MAP`` never lands on a client profile's disk, no matter what
gets added to the bundled ``skills/`` tree later. This is deliberately a
static, hand-maintained file — not derived from the dashboard's own skill
catalog (``agent_skills.skill_key`` is a free-form string with no mapping to
hermes-agent skill folder names today).

IMPORTANT — name format: entries here are the bare ``skill_name`` that
``tools/skills_sync.py::_discover_bundled_skills()`` reads from each skill's
own ``SKILL.md`` frontmatter (``name:``), falling back to the skill
directory's leaf name when absent. This is NOT the same as the skill's
repo-relative path (``skills/<category>/<name>/``) — a category folder like
"research" is not itself a skill (it has no ``SKILL.md``; it contains several
individually-named skills: arxiv, blogwatcher, llm-wiki, polymarket,
research-paper-writing). Confirmed by direct read of each SKILL.md's
``name:`` field before writing this list (2026-07-24) — every entry below
matches its directory's leaf name today, but that's the exception proven by
checking, not an assumption to keep making blind.

``connector_key`` values below match the product's catalog exactly — see
``01_CLIENTES/Meus-Projetos/Axtro Agent/lib/connectors.ts::CONNECTOR_CATALOG``.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Tuple

# Skills with no sensitive credential, safe for every client profile
# regardless of which connectors they've connected. Bare skill_name (see
# module docstring), not the repo-relative path.
TENANT_BASE_SKILLS: Tuple[str, ...] = (
    "arxiv", "blogwatcher", "llm-wiki", "polymarket", "research-paper-writing",  # skills/research/*
    "obsidian",  # skills/note-taking/obsidian
    "nano-pdf", "ocr-and-documents", "powerpoint", "maps",  # skills/productivity/*
)

# connector_key (Axtro Agent catalog) -> hermes-agent skill_name(s) it
# unlocks, ONLY when that connector's status is "connected" for the company.
# The Google/Telnyx variants here are deliberately the GENERIC/BYOK skills,
# never the "-axtro" internal ones (see INTERNAL_ONLY_SKILLS below).
CONNECTOR_SKILL_MAP: Dict[str, Tuple[str, ...]] = {
    "telegram": (),  # platform adapter, not a skill folder
    "google": ("google-workspace",),  # skills/productivity/google-workspace
    "telephony": ("telnyx-voice-sms",),  # skills/communication/telnyx-voice-sms, tenant-scoped via _tenant_call_policy.py
    "workforce_crm": ("crm-connector",),  # skills/operations/crm-connector
    "whatsapp": (),  # platform adapter, not a skill folder
    "discord": (),  # platform adapter, not a skill folder
    "slack": (),  # platform adapter, not a skill folder
    "social": (),
}

# Skills exclusive to the Axtro AI internal/personal agent (Fernando's own
# ~/.hermes) — real Gmail impersonation of axtro@axtroai.com, real VPS SSH,
# real internal Telnyx account. MUST NEVER appear in a client profile's
# .skills_allowlist. Not runtime logic — used only by
# tests/axtro/test_tenant_skill_catalog.py as a hard assertion against the two
# collections above, so an accidental future addition fails CI loudly instead
# of silently reaching a client's disk.
INTERNAL_ONLY_SKILLS: FrozenSet[str] = frozenset({
    "google-workspace-axtro",  # skills/productivity/google-workspace-axtro
    "ask-vps-hermes",  # skills/productivity/ask-vps-hermes
})


def eligible_skills_for_connectors(connected_connector_keys: Tuple[str, ...]) -> Tuple[str, ...]:
    """Return the fail-closed skill list (bare skill_names, ready to write
    one-per-line into a profile's ``.skills_allowlist``) for a client
    profile.

    ``connected_connector_keys`` should list only connectors whose status is
    "connected" for the company (see ``HERMES_BRIDGE.md`` snapshot shape).
    Unknown connector keys are ignored, not an error — a client profile that
    connects something not yet in ``CONNECTOR_SKILL_MAP`` simply gets no
    extra skill for it until this file is updated.
    """
    skills = set(TENANT_BASE_SKILLS)
    for key in connected_connector_keys:
        skills.update(CONNECTOR_SKILL_MAP.get(key, ()))
    return tuple(sorted(skills))
