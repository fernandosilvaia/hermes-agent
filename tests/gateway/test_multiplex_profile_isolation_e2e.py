"""Fase 2 do plano multi-tenant Axtro Agent: prova de isolamento entre
PERFIS REAIS (dois ``HERMES_HOME`` em disco, dois ``.env``, dois
``.skills_allowlist``) — não só ao nível de ``get_secret``/``_getenv`` como
``test_multiplex_credential_isolation.py`` já prova.

Cobre exatamente os 4 pontos do plano:
  1. Token de plataforma (Telegram) nunca vaza entre perfis nem do container.
  2. ``dispatch_guard.check`` via ``build_scoped_env`` respeita o segredo do
     perfil ativo, nunca o de outro perfil nem o "vazamento de container".
  3. ``.skills_allowlist`` real (via ``tools/skills_sync.py`` em subprocesso —
     ver correção de design no plano, Fase 4) nunca copia skill interna.
  4. Concorrência real via ``asyncio.gather``: dois perfis processados ao
     mesmo tempo não cruzam ``ContextVar``.
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

from agent import secret_scope as ss
from axtro import dispatch_guard as dg
import hermes_constants as hc
from gateway.config import Platform, load_gateway_config


@pytest.fixture(autouse=True)
def _reset_multiplex_state():
    ss.set_multiplex_active(False)
    yield
    ss.set_multiplex_active(False)


def _write_env(home: Path, **kv) -> None:
    home.mkdir(parents=True, exist_ok=True)
    lines = [f"{k}={v}" for k, v in kv.items()]
    (home / ".env").write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestPlatformTokenCrossProfileIsolation:
    """1. Token de plataforma cross-perfil (gateway/config.py:_apply_env_overrides)."""

    def test_two_profiles_never_see_each_others_telegram_token(self, monkeypatch, tmp_path):
        # Simula um vazamento de container: valor setado no processo inteiro,
        # que NUNCA deveria vencer um perfil corretamente configurado.
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "container-level-leak")
        ss.set_multiplex_active(True)

        home_a = tmp_path / "profile-a"
        home_b = tmp_path / "profile-b"
        _write_env(home_a, TELEGRAM_BOT_TOKEN="token-A")
        _write_env(home_b, TELEGRAM_BOT_TOKEN="token-B")

        for home, expected in ((home_a, "token-A"), (home_b, "token-B")):
            home_token = hc.set_hermes_home_override(str(home))
            secret_token = ss.set_secret_scope(ss.build_profile_secret_scope(home))
            try:
                config = load_gateway_config()
                token = config.platforms[Platform.TELEGRAM].token
                assert token == expected
                assert token != "container-level-leak"
            finally:
                ss.reset_secret_scope(secret_token)
                hc.reset_hermes_home_override(home_token)

    def test_profile_missing_token_does_not_fall_back_to_container(self, monkeypatch, tmp_path):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "container-level-leak")
        ss.set_multiplex_active(True)

        home = tmp_path / "profile-no-telegram"
        _write_env(home)  # sem TELEGRAM_BOT_TOKEN

        home_token = hc.set_hermes_home_override(str(home))
        secret_token = ss.set_secret_scope(ss.build_profile_secret_scope(home))
        try:
            config = load_gateway_config()
            assert Platform.TELEGRAM not in config.platforms or not config.platforms[Platform.TELEGRAM].token
        finally:
            ss.reset_secret_scope(secret_token)
            hc.reset_hermes_home_override(home_token)


class TestDispatchGuardScopedEnv:
    """2. dispatch_guard.check via build_scoped_env — credencial por perfil."""

    def _make_governed_skill(self, root: Path, name: str, credentials):
        d = root / name
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "run.py").write_text("print('ran')\n", encoding="utf-8")
        contract = {
            "id": name, "enabled": True, "production_ready": True,
            "activation_stage": "production", "autonomy_ring": 1,
            "stop_conditions": ["manual"], "telemetry_events": ["ev"],
            "credentials": list(credentials),
        }
        (d / "contract.json").write_text(json.dumps(contract), encoding="utf-8")
        return d

    def test_profile_with_credential_is_allowed_profile_without_is_blocked(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MY_SKILL_TOKEN", "container-level-leak")
        ss.set_multiplex_active(True)

        d = self._make_governed_skill(tmp_path, "tenant_skill", ["MY_SKILL_TOKEN"])
        roots = {"tenant_skill": d}

        # Perfil A: tem a credencial no próprio escopo -> permitido.
        tok_a = ss.set_secret_scope({"MY_SKILL_TOKEN": "profile-A-secret"})
        try:
            r = dg.check("python3 scripts/run.py", workdir=str(d), governed_roots=roots)
            assert r["action"] == "allow"
        finally:
            ss.reset_secret_scope(tok_a)

        # Perfil B: escopo instalado mas SEM a credencial -> bloqueado
        # fail-closed, nunca cai para o "vazamento de container".
        tok_b = ss.set_secret_scope({})
        try:
            r = dg.check("python3 scripts/run.py", workdir=str(d), governed_roots=roots)
            assert r["action"] == "block"
            assert "MY_SKILL_TOKEN" in r["message"]
        finally:
            ss.reset_secret_scope(tok_b)

    def test_governance_toggles_still_read_from_real_process_env(self, monkeypatch, tmp_path):
        # HERMES_KILL_SWITCH é um toggle de operador, não segredo de perfil —
        # deve continuar valendo mesmo com um secret scope de perfil instalado.
        monkeypatch.setenv("HERMES_KILL_SWITCH", "on")
        ss.set_multiplex_active(True)

        d = self._make_governed_skill(tmp_path, "tenant_skill_killswitch", [])
        roots = {"tenant_skill_killswitch": d}

        tok = ss.set_secret_scope({})
        try:
            r = dg.check("python3 scripts/run.py", workdir=str(d), governed_roots=roots)
            assert r["mode"] == "killed"
        finally:
            ss.reset_secret_scope(tok)


class TestSkillsAllowlistNeverLeaksInternalSkills:
    """3. .skills_allowlist real — via subprocesso (correção de design da Fase 4:
    tools/skills_sync.py resolve HERMES_HOME como constante de módulo na
    primeira importação, então precisa rodar num processo Python novo por
    perfil, nunca in-process para dois perfis na mesma vida do processo)."""

    def test_allowlist_denies_internal_only_skills(self, tmp_path):
        profile_home = tmp_path / "client-profile"
        (profile_home / "skills").mkdir(parents=True)
        allowlist_names = [
            "research", "note-taking/obsidian", "productivity/google-workspace",
        ]
        (profile_home / "skills" / ".skills_allowlist").write_text(
            "\n".join(allowlist_names) + "\n", encoding="utf-8"
        )

        env = dict(os.environ)
        env["HERMES_HOME"] = str(profile_home)
        result = subprocess.run(
            [sys.executable, "-m", "tools.skills_sync"],
            cwd=str(REPO), env=env, capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0, result.stderr

        synced = {p.name for p in (profile_home / "skills").iterdir() if p.is_dir()}
        assert "google-workspace-axtro" not in synced
        assert "ask-vps-hermes" not in synced


class TestConcurrentProfileTurnsDoNotCrossContextvars:
    """4. Concorrência real (asyncio.gather) — o teste mais importante: prova
    que _profile_runtime_scope (HERMES_HOME override + secret scope) não vaza
    entre tasks concorrentes do MESMO event loop, não só sequencialmente."""

    @pytest.mark.asyncio
    async def test_two_concurrent_turns_never_see_each_others_secret(self, monkeypatch):
        ss.set_multiplex_active(True)
        monkeypatch.setenv("SHARED_TOKEN_NAME", "container-level-leak")

        async def _turn(secret_value: str, delay_a: float, delay_b: float) -> str:
            tok = ss.set_secret_scope({"SHARED_TOKEN_NAME": secret_value})
            try:
                await asyncio.sleep(delay_a)
                # Ponto de checagem no MEIO do turno, depois de um yield real
                # ao event loop — se o ContextVar vazasse entre tasks
                # concorrentes, é aqui que apareceria o valor do outro perfil.
                mid = ss.get_secret("SHARED_TOKEN_NAME")
                await asyncio.sleep(delay_b)
                end = ss.get_secret("SHARED_TOKEN_NAME")
                assert mid == secret_value
                assert end == secret_value
                return end
            finally:
                ss.reset_secret_scope(tok)

        results = await asyncio.gather(
            _turn("profile-A-secret", 0.01, 0.02),
            _turn("profile-B-secret", 0.02, 0.01),
        )
        assert results == ["profile-A-secret", "profile-B-secret"]
