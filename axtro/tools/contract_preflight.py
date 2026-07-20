#!/usr/bin/env python3
"""contract_preflight.py — O GATE de runtime. O daemon (ou o wrapper de execução
de skill, `axtro/skill_runner.py`) chama isto ANTES de deixar uma skill governada
fazer uma ação real.

É o que transforma contract.json de documentação em CONTROLE: uma decisão que,
pelo exit code, autoriza ou nega a ação real de uma skill.

Uso (o daemon/worker chama assim antes de executar a skill):
    python3 axtro/tools/contract_preflight.py <caminho-da-skill>
    # exit 0  → ação real AUTORIZADA (imprime o modo: production|staging)
    # exit 10 → BLOQUEADA por governança (imprime o motivo)
    # exit 0  → skill NATIVA da Nous (não governada) → pass-through

Sempre fail-CLOSED: qualquer erro inesperado → bloqueia (exit 10).

Este preflight NÃO substitui o gate de dupla-env dentro de cada skill — é uma
camada ADICIONAL, por cima. Ação real efetiva = preflight_ok AND gate_no_script.

API:
  preflight(skill_path, env=None, is_governed=None) -> (exit_code, mensagem)
      compat retro: tupla (code, msg).
  preflight_decision(skill_path, env=None, is_governed=None) -> dict
      decisão estruturada {code, allow, governed, mode, msg}. Usada pelo
      skill_runner para saber o MODO (production/staging/dry_run), não só o allow.
  is_governed: callable(rel:str, sdir:Path) -> bool. Default = pertencer a
      GOVERNED_SKILLS.txt. Injetável para teste (fixtures fora do repo).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
import contract_guard as cg  # noqa: E402  (mantido p/ compat de quem importa daqui)
import autonomy_core as ac  # noqa: E402

GOVERNED_LIST = REPO / "axtro" / "GOVERNED_SKILLS.txt"
EXIT_ALLOW = 0
EXIT_BLOCK = 10


def _governed_set() -> set:
    if not GOVERNED_LIST.is_file():
        return set()
    out = set()
    for line in GOVERNED_LIST.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.add(s)
    return out


def _candidate_roots() -> list:
    """Every filesystem root a governed skill's directory may physically be
    anchored under, across dev/CLI (repo checkout) AND Docker/production
    (installed ``HERMES_HOME/skills`` layout, default profile or named).

    ``GOVERNED_SKILLS.txt`` entries are written repo-relative (e.g.
    ``skills/finance/hermes-purchase``) — but at runtime, ``tools/
    skills_sync.py`` physically copies that same tree into
    ``HERMES_HOME/skills`` (``hermes_constants.get_skills_dir()``) at
    container boot (see ``docker/stage2-hook.sh``). For a NAMED profile,
    that copy lands under ``<hermes-root>/profiles/<name>/skills`` instead
    (``hermes_cli/profiles.py:get_profile_dir()``). A governed skill's
    script invoked from ANY of these physical copies must resolve to the
    same governed key so it gets checked against the same contract.json.

    Order matters: named-profile directories are listed BEFORE the bare
    hermes root, because the root is itself an ancestor of ``root/profiles/
    <name>`` — if the root were tried first, a path under a named profile
    would incorrectly relativize to ``profiles/<name>/skills/...`` instead
    of ``skills/...`` and never match ``GOVERNED_SKILLS.txt``. Callers that
    consume this list (``_rel()`` here, ``dispatch_guard._governed_roots()``)
    must try roots in the order returned, first match wins.

    Best-effort: importing ``hermes_constants`` or resolving any one root is
    optional — if it fails, that candidate is silently skipped. This keeps
    detection fail-open (same posture as the rest of this module's callers)
    instead of ever raising out of a path-shape computation.
    """
    roots = [REPO]
    try:
        import hermes_constants as hc
    except Exception:
        return roots

    default_root = None
    try:
        default_root = hc.get_default_hermes_root()
        profiles_dir = default_root / "profiles"
        if profiles_dir.is_dir():
            for entry in sorted(profiles_dir.iterdir()):
                if entry.is_dir():
                    roots.append(entry)
    except Exception:
        pass
    try:
        roots.append(hc.get_hermes_home())
    except Exception:
        pass
    if default_root is not None:
        roots.append(default_root)

    seen = set()
    out = []
    for r in roots:
        try:
            resolved = Path(r).resolve()
        except Exception:
            continue
        if resolved not in seen:
            seen.add(resolved)
            out.append(resolved)
    return out


def _rel(sdir: Path) -> str:
    for root in _candidate_roots():
        try:
            return str(sdir.relative_to(root))
        except ValueError:
            continue
    return sdir.name


def _default_is_governed(rel: str, sdir: Path) -> bool:
    return rel in _governed_set()


def preflight_decision(skill_path, env=None, is_governed=None) -> dict:
    """Decisão estruturada. Fail-closed em qualquer erro. Delega ao autonomy_core
    (cérebro único: kill switch, anel, classe de risco, aprovação).

    Retorna: {code, allow: bool, governed: bool, mode: str, msg: str}
      mode ∈ {'production','staging','dry_run','blocked','killed','passthrough'}
      allow = ação REAL autorizada (dry-run NÃO conta como allow).
    """
    check = is_governed or _default_is_governed
    try:
        sdir = Path(skill_path).resolve()
        rel = _rel(sdir)
        governed = check(rel, sdir)
        d = ac.decide(sdir, env, native=not governed)
        motivo = (d.reasons or ["-"])[0]

        if d.mode == "passthrough":
            return {"code": EXIT_ALLOW, "allow": True, "governed": False,
                    "mode": "passthrough",
                    "msg": "PASSTHROUGH: skill nativa (nao governada pela Axtro): {}".format(rel)}
        if d.allow_real:
            return {"code": EXIT_ALLOW, "allow": True, "governed": True, "mode": d.mode,
                    "msg": "AUTORIZADA (modo {}): {}".format(d.mode, rel)}
        if d.mode == "dry_run":
            # dry-run permitido, mas AÇÃO REAL bloqueada → exit 10 (o gate é sobre ação real).
            return {"code": EXIT_BLOCK, "allow": False, "governed": True, "mode": "dry_run",
                    "msg": "BLOQUEADA (acao real) — DRY-RUN permitido: {} — {}".format(rel, motivo)}
        # blocked / killed
        return {"code": EXIT_BLOCK, "allow": False, "governed": True, "mode": d.mode,
                "msg": "BLOQUEADA: {} — {}".format(rel, motivo)}
    except Exception as e:  # noqa: BLE001 — fail-closed
        return {"code": EXIT_BLOCK, "allow": False, "governed": True,
                "mode": "blocked",
                "msg": "BLOQUEADA (fail-closed, erro inesperado): {}".format(str(e)[:150])}


def preflight(skill_path, env=None, is_governed=None) -> tuple:
    """Compat retro: retorna (exit_code, mensagem)."""
    d = preflight_decision(skill_path, env=env, is_governed=is_governed)
    return d["code"], d["msg"]


def main():
    if len(sys.argv) < 2:
        print("uso: contract_preflight.py <caminho-da-skill>", file=sys.stderr)
        sys.exit(EXIT_BLOCK)
    code, msg = preflight(sys.argv[1])
    print(msg)
    sys.exit(code)


if __name__ == "__main__":
    main()
