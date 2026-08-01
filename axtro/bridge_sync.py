#!/usr/bin/env python3
"""axtro/bridge_sync.py — consumidor do contrato HERMES_BRIDGE.md.

Materializa, em disco, um perfil hermes-agent (``profiles/<slug>/``) a partir
do que uma empresa configurou no painel do Axtro Agent (Supabase
``bhrzfttkagglheofjozz``): ``SOUL.md`` (identidade), ``.env`` (credenciais de
conectores conectados, via ``get_connector_credential`` — nunca a anon key),
``skills/.skills_allowlist`` (fail-closed, ``axtro/tenant_skill_catalog.py``)
e ``memories/MEMORY.md`` (goals + memory items).

ESCOPO DESTA VERSÃO (v1, deliberado — ver docs/design do plano):
  - ``google`` (OAuth) e ``workforce_crm``/``telephony`` (fluxos próprios,
    não um token único) NÃO são materializados em ``.env`` ainda — só
    ``telegram`` (o único conector do piloto, Fase 8) é. Uma empresa com
    outros conectores conectados loga um aviso e segue sem eles; não falha.
  - ``watch_realtime()`` é POLLING (re-snapshot periódico), não uma inscrição
    real ao protocolo Phoenix-channel do Supabase Realtime — o venv não tem
    um cliente Realtime instalado e implementar esse protocolo do zero é
    trabalho à parte. Funcionalmente equivalente (o perfil converge pro
    estado do painel), só com latência do intervalo de poll em vez de push
    instantâneo.
  - Upsert em ``usage_snapshots`` (Fase 5) está aqui como função isolada e
    testada, mas ainda NÃO está fiada ao fim de turno real do gateway
    (``gateway/run.py``) — isso é o próximo passo, feito com cuidado porque
    mexe no arquivo de 18k linhas do loop principal.

Nunca toca no perfil "default" (o HERMES_HOME pessoal do Fernando) — só em
perfis nomeados, criados por este próprio módulo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

_AXTRO_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _AXTRO_DIR.parent
for _p in (str(_REPO_ROOT), str(_AXTRO_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from hermes_cli.profiles import create_profile, get_profile_dir, normalize_profile_name, profile_exists, validate_profile_name
from tenant_skill_catalog import eligible_skills_for_connectors

logger = logging.getLogger(__name__)

# Conectores cujo credential único (get_connector_credential) já mapeia pra
# uma linha de .env simples. google/workforce_crm/telephony ficam de fora
# de propósito (ver docstring do módulo) — materialize_profile loga aviso e
# segue sem eles em vez de falhar a empresa inteira.
CONNECTOR_ENV_VAR: Dict[str, str] = {
    "telegram": "TELEGRAM_BOT_TOKEN",
}


class BridgeError(RuntimeError):
    """Erro ao falar com o Axtro Agent (rede, auth, empresa não encontrada)."""


def _bridge_config() -> Dict[str, str]:
    url = os.environ.get("AXTRO_AGENT_URL", "").rstrip("/")
    bridge_key = os.environ.get("AGENT_BRIDGE_API_KEY", "")
    supabase_url = os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "").rstrip("/")
    service_role_key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    missing = [
        name for name, val in (
            ("AXTRO_AGENT_URL", url), ("AGENT_BRIDGE_API_KEY", bridge_key),
            ("NEXT_PUBLIC_SUPABASE_URL", supabase_url), ("SUPABASE_SERVICE_ROLE_KEY", service_role_key),
        ) if not val
    ]
    if missing:
        raise BridgeError(f"variáveis de ambiente ausentes: {', '.join(missing)}")
    return {
        "axtro_agent_url": url, "bridge_key": bridge_key,
        "supabase_url": supabase_url, "service_role_key": service_role_key,
    }


def snapshot_company(company_id: str, *, config: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """GET /api/agent-context/{companyId} — snapshot completo (HERMES_BRIDGE.md §2)."""
    cfg = config or _bridge_config()
    url = f"{cfg['axtro_agent_url']}/api/agent-context/{company_id}"
    resp = httpx.get(url, headers={"Authorization": f"Bearer {cfg['bridge_key']}"}, timeout=20)
    if resp.status_code == 404:
        raise BridgeError(f"empresa {company_id} não encontrada")
    resp.raise_for_status()
    return resp.json()


def get_connector_credential(company_id: str, connector_key: str, *, config: Optional[Dict[str, str]] = None) -> Optional[str]:
    """RPC get_connector_credential — só service-role, nunca a anon key (HERMES_BRIDGE.md §3)."""
    cfg = config or _bridge_config()
    url = f"{cfg['supabase_url']}/rest/v1/rpc/get_connector_credential"
    resp = httpx.post(
        url,
        headers={
            "apikey": cfg["service_role_key"],
            "Authorization": f"Bearer {cfg['service_role_key']}",
            "Content-Type": "application/json",
        },
        json={"p_company_id": company_id, "p_connector_key": connector_key},
        timeout=20,
    )
    resp.raise_for_status()
    value = resp.json()
    return value if value else None


def list_active_companies(*, config: Optional[Dict[str, str]] = None, exclude_company_ids: Optional[set] = None) -> List[str]:
    """Descobre empresas com o conector ``telegram`` CONECTADO — a única
    credencial que esta versão do bridge_sync materializa (ver docstring do
    módulo). Consulta direta em ``agent_connectors`` (service-role), não a
    RPC de leitura de segredo — aqui só precisamos do ``company_id``, nunca
    do valor da credencial.

    Substitui a necessidade de listar ``--company-id`` na mão a cada empresa
    nova que assina o Axtro Agent (Fase 8 do plano) — é o que torna o
    watch-loop de produção (``watch_poll_discover``) capaz de pegar uma
    empresa nova sozinho, sem reiniciar o processo nem editar config.

    ``exclude_company_ids``: defesa em profundidade — nunca materializa um
    ``company_id`` conhecido de cliente com daemon dedicado (Alfred Kings,
    Techmax/Luiza), mesmo que uma linha para ele apareça nesta tabela um dia
    por engano. Em 2026-07-31, nenhum dos dois existe em ``companies`` neste
    Supabase (confirmado por consulta direta) — a exclusão é puramente
    preventiva, não corrige um problema observado.
    """
    cfg = config or _bridge_config()
    url = f"{cfg['supabase_url']}/rest/v1/agent_connectors"
    resp = httpx.get(
        url,
        headers={"apikey": cfg["service_role_key"], "Authorization": f"Bearer {cfg['service_role_key']}"},
        params={"select": "company_id", "connector_key": "eq.telegram", "status": "eq.connected"},
        timeout=20,
    )
    resp.raise_for_status()
    excluded = exclude_company_ids or set()
    seen: List[str] = []
    for row in resp.json():
        cid = row["company_id"]
        if cid in excluded or cid in seen:
            continue
        seen.append(cid)
    return seen


def _read_usage_snapshot(company_id: str, *, config: Dict[str, str]) -> Dict[str, float]:
    """Estado atual de usage_snapshots pra empresa, ou zeros se não existe
    linha ainda (a tabela é criada vazia — 0001_init.sql — ninguém escreve
    até este módulo)."""
    url = f"{config['supabase_url']}/rest/v1/usage_snapshots"
    resp = httpx.get(
        url,
        headers={"apikey": config["service_role_key"], "Authorization": f"Bearer {config['service_role_key']}"},
        params={"company_id": f"eq.{company_id}", "select": "llm_usd_spent,voice_minutes_used,tasks_executed"},
        timeout=20,
    )
    resp.raise_for_status()
    rows = resp.json()
    if not rows:
        return {"llm_usd_spent": 0.0, "voice_minutes_used": 0.0, "tasks_executed": 0}
    return rows[0]


def write_usage_snapshot(
    company_id: str,
    *,
    tasks_executed_delta: int = 0,
    llm_usd_spent_delta: float = 0.0,
    voice_minutes_used_delta: float = 0.0,
    config: Optional[Dict[str, str]] = None,
) -> None:
    """Upsert incremental em usage_snapshots (Fase 5) — soma os deltas ao
    estado atual e escreve o total. Fetch-then-write: seguro porque só um
    processo (o perfil daquela empresa) escreve usage dela por vez; se isso
    mudar (múltiplos writers concorrentes pra mesma empresa), precisa virar
    uma RPC atômica de incremento no lado do Axtro Agent.

    NOTA DE ESCOPO (Fase 5): esta função existe e é testada, mas ainda NÃO
    está fiada ao fim de turno real do gateway — isso é o próximo passo,
    feito com cuidado por mexer em gateway/run.py (18k linhas).
    """
    cfg = config or _bridge_config()
    current = _read_usage_snapshot(company_id, config=cfg)
    payload = {
        "company_id": company_id,
        "llm_usd_spent": round(current.get("llm_usd_spent", 0.0) + llm_usd_spent_delta, 6),
        "voice_minutes_used": round(current.get("voice_minutes_used", 0.0) + voice_minutes_used_delta, 4),
        "tasks_executed": current.get("tasks_executed", 0) + tasks_executed_delta,
        "updated_at": _utcnow_iso(),
    }
    url = f"{cfg['supabase_url']}/rest/v1/usage_snapshots"
    resp = httpx.post(
        url,
        headers={
            "apikey": cfg["service_role_key"],
            "Authorization": f"Bearer {cfg['service_role_key']}",
            "Content-Type": "application/json",
            "Prefer": "resolution=merge-duplicates,return=minimal",
        },
        json=payload,
        timeout=20,
    )
    resp.raise_for_status()


def _utcnow_iso() -> str:
    # Timestamps só são carimbados fora de qualquer caminho de replay/teste
    # determinístico deste módulo — aqui é reporte de uso real, não algo que
    # precise ser reproduzível.
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class UsageBatcher:
    """Acumula deltas de uso em memória por company_id e só bate na rede no
    flush — evita 1 request HTTP por turno (plano, Fase 5: "com batching")."""

    def __init__(self) -> None:
        self._pending: Dict[str, Dict[str, float]] = {}

    def add(self, company_id: str, *, tasks_executed: int = 0, llm_usd_spent: float = 0.0, voice_minutes_used: float = 0.0) -> None:
        entry = self._pending.setdefault(company_id, {"tasks_executed": 0, "llm_usd_spent": 0.0, "voice_minutes_used": 0.0})
        entry["tasks_executed"] += tasks_executed
        entry["llm_usd_spent"] += llm_usd_spent
        entry["voice_minutes_used"] += voice_minutes_used

    def flush(self, *, config: Optional[Dict[str, str]] = None) -> None:
        cfg = config or _bridge_config()
        pending, self._pending = self._pending, {}
        for company_id, deltas in pending.items():
            try:
                write_usage_snapshot(
                    company_id,
                    tasks_executed_delta=deltas["tasks_executed"],
                    llm_usd_spent_delta=deltas["llm_usd_spent"],
                    voice_minutes_used_delta=deltas["voice_minutes_used"],
                    config=cfg,
                )
            except Exception:
                logger.exception("falha ao gravar usage_snapshots pra empresa %s — deltas voltam pro próximo flush", company_id)
                self._pending.setdefault(company_id, {"tasks_executed": 0, "llm_usd_spent": 0.0, "voice_minutes_used": 0.0})
                for k, v in deltas.items():
                    self._pending[company_id][k] += v


def _hash_write_if_changed(path: Path, content: str) -> bool:
    """Escreve só se o conteúdo mudou (idempotente — não pisa em edição manual
    sem necessidade, mesmo espírito do manifest de tools/skills_sync.py)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    new_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    marker = path.with_suffix(path.suffix + ".hash")
    if path.exists() and marker.exists() and marker.read_text().strip() == new_hash:
        return False
    path.write_text(content, encoding="utf-8")
    marker.write_text(new_hash, encoding="utf-8")
    return True


def _render_soul_md(identity: Optional[Dict[str, Any]], company_name: str) -> str:
    identity = identity or {}
    name = identity.get("name") or "Atlas"
    role = identity.get("role") or ""
    soul = identity.get("soul") or ""
    personality = identity.get("personality") or ""
    culture = identity.get("culture") or ""
    voice = identity.get("voice") or ""
    non_negotiables = identity.get("non_negotiables") or "Nunca enviar, publicar, comprar ou excluir nada sem aprovação humana."
    return (
        f"# {name}\n\n"
        f"Agente da empresa **{company_name}**, gerado a partir do painel Axtro Agent "
        f"— não editar à mão, as próximas mudanças no painel sobrescrevem este arquivo.\n\n"
        f"## Papel\n{role}\n\n"
        f"## Alma\n{soul}\n\n"
        f"## Personalidade\n{personality}\n\n"
        f"## Cultura\n{culture}\n\n"
        f"## Voz\n{voice}\n\n"
        f"## Não-negociáveis\n{non_negotiables}\n"
    )


def _render_memory_md(goals: List[Dict[str, Any]], memory_items: List[Dict[str, Any]]) -> str:
    lines = ["# Memória e metas (gerado pelo painel Axtro Agent)\n"]
    lines.append("## Metas\n")
    if goals:
        for g in goals:
            title = g.get("title") or g.get("name") or "(sem título)"
            status = g.get("status") or ""
            lines.append(f"- {title} ({status})".rstrip())
    else:
        lines.append("(nenhuma meta cadastrada)")
    lines.append("\n## Memória\n")
    if memory_items:
        for m in memory_items:
            content = m.get("content") or m.get("text") or ""
            if content:
                lines.append(f"- {content}")
    else:
        lines.append("(nenhum item de memória)")
    return "\n".join(lines) + "\n"


def write_skills_allowlist(profile_dir: Path, connectors: List[Dict[str, Any]]) -> List[str]:
    """Escreve skills/.skills_allowlist a partir dos conectores CONECTADOS
    (Fase 0/4). Retorna a lista de skills liberadas (pra log/teste)."""
    connected_keys = tuple(
        c["connector_key"] for c in connectors if c.get("status") == "connected"
    )
    # tenant_skill_catalog já devolve bare skill_name (mesmo formato que
    # tools/skills_sync.py::_discover_bundled_skills() usa pra comparar) —
    # escreve direto, sem transformação.
    names = sorted(eligible_skills_for_connectors(connected_keys))
    allowlist_path = profile_dir / "skills" / ".skills_allowlist"
    allowlist_path.parent.mkdir(parents=True, exist_ok=True)
    allowlist_path.write_text("\n".join(names) + "\n", encoding="utf-8")
    return names


def sync_profile_skills(profile_dir: Path) -> Dict[str, Any]:
    """Sincroniza as skills bundled elegíveis (por .skills_allowlist) pro
    perfil. Reusa hermes_cli.profiles.seed_profile_skills() — já roda em
    subprocesso pelo mesmo motivo documentado lá: sync_skills() cacheia
    HERMES_HOME como constante de módulo na primeira importação, então
    chamá-la in-process pra dois perfis na mesma vida do processo usaria o
    HOME do primeiro perfil importado pros dois."""
    from hermes_cli.profiles import seed_profile_skills

    result = seed_profile_skills(profile_dir, quiet=True)
    if result is None:
        logger.error("skills_sync falhou pro perfil %s", profile_dir)
        return {"returncode": 1}
    return result


def materialize_profile(snapshot: Dict[str, Any], *, config: Optional[Dict[str, str]] = None) -> Path:
    """Materializa (cria se preciso, atualiza sempre) o perfil de uma empresa
    a partir do snapshot da ponte. Idempotente — chamada de novo a cada
    mudança detectada (Realtime real, ou o poll do v1)."""
    company = snapshot["company"]
    company_id = company["id"]
    slug = normalize_profile_name(company.get("slug") or company["name"])
    if slug == "default":
        raise BridgeError(
            f"empresa {company_id} normalizou pro nome de perfil reservado "
            "'default' — nunca materializar sobre o perfil pessoal."
        )
    # CRÍTICO: valida o FORMATO do slug (regex [a-z0-9][a-z0-9_-]{0,63} +
    # nomes reservados) ANTES de qualquer profile_exists()/get_profile_dir().
    # `company.slug`/`company.name` vêm de uma tabela que uma empresa
    # autenticada escreve direto (a RLS da Supabase não impõe formato —
    # `slugify()` do Next.js é só uma camada de UX, não a fronteira de
    # segurança) — sem esta validação aqui, um slug tipo '/tmp' ou
    # '../profiles/outro-tenant' faz profile_exists() retornar True (o
    # caminho já existe) e PULA create_profile(), o único lugar que hoje
    # rodava validate_profile_name() — resultado: escreve SOUL.md/.env com
    # a credencial da empresa/.skills_allowlist diretamente num diretório
    # real do sistema ou no perfil já materializado de outro tenant.
    # Achado por revisão adversarial (2026-07-31) antes de qualquer deploy.
    try:
        validate_profile_name(slug)
    except ValueError as exc:
        raise BridgeError(
            f"empresa {company_id}: slug/nome inseguro pra virar perfil ({slug!r}) — recusado antes de tocar o filesystem ({exc})"
        ) from exc

    if not profile_exists(slug):
        # NUNCA no_skills=True aqui: essa flag grava um marcador PERMANENTE
        # de opt-out (.no-bundled-skills) que faz seed_profile_skills()
        # pular pra sempre, ignorando .skills_allowlist completamente —
        # o oposto do que queremos (skills bundled elegíveis, filtradas
        # pelo allowlist escrito logo abaixo, não zero skills).
        create_profile(slug)
    profile_dir = get_profile_dir(slug)

    _hash_write_if_changed(
        profile_dir / "SOUL.md",
        _render_soul_md(snapshot.get("identity"), company.get("name", slug)),
    )
    _hash_write_if_changed(
        profile_dir / "memories" / "MEMORY.md",
        _render_memory_md(snapshot.get("goals", []), snapshot.get("memoryItems", [])),
    )

    connectors = snapshot.get("connectors", [])
    env_lines = []
    for connector in connectors:
        if connector.get("status") != "connected":
            continue
        key = connector["connector_key"]
        env_var = CONNECTOR_ENV_VAR.get(key)
        if env_var is None:
            logger.warning(
                "conector '%s' conectado pra empresa %s mas ainda sem materialização de "
                "credencial nesta versão do bridge_sync (v1: só telegram) — pulando",
                key, company_id,
            )
            continue
        value = get_connector_credential(company_id, key, config=config)
        if value:
            env_lines.append(f"{env_var}={value}")
    env_content = "\n".join(env_lines) + ("\n" if env_lines else "")
    env_path = profile_dir / ".env"
    env_path.write_text(env_content, encoding="utf-8")
    os.chmod(env_path, 0o600)

    write_skills_allowlist(profile_dir, connectors)
    sync_profile_skills(profile_dir)

    logger.info("perfil '%s' materializado (empresa %s)", slug, company_id)
    return profile_dir


def materialize_once(company_id: str) -> Path:
    cfg = _bridge_config()
    snapshot = snapshot_company(company_id, config=cfg)
    return materialize_profile(snapshot, config=cfg)


def watch_poll(company_ids: List[str], *, interval_seconds: int = 15, iterations: Optional[int] = None) -> None:
    """v1: polling, não Realtime de verdade (ver docstring do módulo).
    ``iterations=None`` roda pra sempre; um inteiro é usado só em teste."""
    cfg = _bridge_config()
    last_hash: Dict[str, str] = {}
    n = 0
    while iterations is None or n < iterations:
        for company_id in company_ids:
            try:
                snapshot = snapshot_company(company_id, config=cfg)
                digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()
                if last_hash.get(company_id) != digest:
                    materialize_profile(snapshot, config=cfg)
                    last_hash[company_id] = digest
            except Exception:
                logger.exception("falha ao sincronizar empresa %s — tenta de novo no próximo poll", company_id)
        n += 1
        if iterations is None or n < iterations:
            time.sleep(interval_seconds)


def watch_poll_discover(
    *,
    interval_seconds: int = 15,
    iterations: Optional[int] = None,
    exclude_company_ids: Optional[set] = None,
) -> None:
    """Como ``watch_poll``, mas descobre as empresas ativas a cada ciclo via
    ``list_active_companies`` em vez de receber uma lista fixa — o modo usado
    em produção (Fase 8): uma empresa nova que conecta o Telegram dela no
    painel entra no loop sozinha, sem precisar reiniciar o processo nem
    editar nenhuma lista na mão. ``iterations=None`` roda pra sempre; um
    inteiro é usado só em teste."""
    cfg = _bridge_config()
    last_hash: Dict[str, str] = {}
    n = 0
    while iterations is None or n < iterations:
        try:
            company_ids = list_active_companies(config=cfg, exclude_company_ids=exclude_company_ids)
        except Exception:
            logger.exception("falha ao descobrir empresas ativas — tenta de novo no próximo poll")
            company_ids = []
        for company_id in company_ids:
            try:
                snapshot = snapshot_company(company_id, config=cfg)
                digest = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode("utf-8")).hexdigest()
                if last_hash.get(company_id) != digest:
                    materialize_profile(snapshot, config=cfg)
                    last_hash[company_id] = digest
            except Exception:
                logger.exception("falha ao sincronizar empresa %s — tenta de novo no próximo poll", company_id)
        n += 1
        if iterations is None or n < iterations:
            time.sleep(interval_seconds)


def run_forever_in_background(*, interval_seconds: int = 15, exclude_company_ids: Optional[set] = None) -> None:
    """Ponto de entrada pensado pro gateway (chamado via ``asyncio.to_thread``
    dentro de um ``asyncio.create_task``), não pro CLI. ``watch_poll_discover``
    já isola falha por empresa e por ciclo de descoberta internamente; esta
    camada extra garante que mesmo uma exceção totalmente inesperada (fora
    desses try/except internos) nunca mata a sincronização multi-tenant pro
    resto da vida do processo do gateway — loga e tenta de novo com backoff
    fixo em vez de deixar a task morrer silenciosamente."""
    while True:
        try:
            watch_poll_discover(interval_seconds=interval_seconds, exclude_company_ids=exclude_company_ids)
            return  # só retorna se iterations tiver sido passado (nunca é o caso aqui)
        except Exception:
            logger.exception(
                "watch_poll_discover encerrou inesperadamente — reiniciando em %ss", interval_seconds
            )
            time.sleep(interval_seconds)


def _main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description="Materializador da ponte HERMES_BRIDGE.md")
    parser.add_argument("--once", action="store_true", help="materializa uma vez e sai")
    parser.add_argument("--watch", action="store_true", help="poll contínuo de uma lista fixa de --company-id (v1 — não é Realtime)")
    parser.add_argument("--watch-all", action="store_true", help="poll contínuo com descoberta automática de empresas ativas (produção, Fase 8)")
    parser.add_argument("--company-id", action="append", dest="company_ids", default=[])
    parser.add_argument("--exclude-company-id", action="append", dest="exclude_company_ids", default=[])
    parser.add_argument("--interval", type=int, default=15)
    args = parser.parse_args()

    if args.watch_all:
        watch_poll_discover(interval_seconds=args.interval, exclude_company_ids=set(args.exclude_company_ids))
        return 0

    if not args.company_ids:
        parser.error("--company-id é obrigatório (pode repetir pra mais de uma empresa) — ou use --watch-all")

    if args.once:
        for cid in args.company_ids:
            path = materialize_once(cid)
            print(f"empresa {cid} -> {path}")
        return 0
    if args.watch:
        watch_poll(args.company_ids, interval_seconds=args.interval)
        return 0
    parser.error("passe --once, --watch ou --watch-all")
    return 2


if __name__ == "__main__":
    raise SystemExit(_main())
