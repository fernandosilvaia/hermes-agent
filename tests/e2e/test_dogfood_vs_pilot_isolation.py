"""Fase 6 do plano multi-tenant Axtro Agent — roteiro adversarial automatizado.

Prova, com CANÁRIOS (valores falsos, nunca credenciais reais) nas variáveis
hoje tratadas como "globais" do processo, que um perfil-cliente nunca
consegue enxergar as credenciais internas da Axtro (VPS, Google Workspace)
mesmo sob concorrência real — sem depender de bots de Telegram ao vivo, que
é a parte que só o Fernando pode rodar/observar (ver docs do plano).

Isto NÃO substitui o roteiro manual com Telegram real (esse continua exigindo
o Fernando observando os logs ao vivo) — é a camada que PODE ser automatizada
e repetida a qualquer momento, incluindo em CI.
"""
import asyncio
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "axtro"))
sys.path.insert(0, str(REPO))

from agent import secret_scope as ss
import dispatch_guard as dg


CANARY_VPS_KEY = "CANARY-VPS-KEY-nunca-deve-aparecer-8f3a2b"
CANARY_GOOGLE_JSON = '{"canary": "CANARY-GOOGLE-nunca-deve-aparecer-1c9d4e"}'


@pytest.fixture(autouse=True)
def _reset_multiplex_state():
    ss.set_multiplex_active(False)
    yield
    ss.set_multiplex_active(False)


class TestCanaryNeverLeaksToClientProfile:
    """Item 2 do roteiro da Fase 6: canário em env "global" nunca aparece
    numa leitura feita como se fosse o turno de um perfil-cliente.

    Duas variantes de "turno de cliente", propositalmente distintas:
    - escopo INSTALADO mas vazio (o caso real: _profile_runtime_scope sempre
      instala um escopo, mesmo que o .env do perfil não tenha a chave) ->
      get_secret() devolve None, nunca o canário. Isso é o comportamento
      correto e documentado do módulo, não uma falha.
    - NENHUM escopo instalado (bug hipotético: o wrapper de profile-scope
      foi pulado inteiro) -> get_secret() tem que falhar alto
      (UnscopedSecretError), nunca cair pro os.environ do container.
    """

    def test_vps_key_canary_never_returned_with_empty_client_scope(self, monkeypatch):
        # Simula o pior caso plausível: um valor real acabou setado no nível
        # do container (erro de operador) — exatamente o cenário que a
        # revisão de segurança pediu pra testar.
        monkeypatch.setenv("HERMES_VPS_API_SERVER_KEY", CANARY_VPS_KEY)
        ss.set_multiplex_active(True)

        # Escopo de um perfil-cliente correto: .env dele não tem (e nunca
        # deveria ter) essa chave, porque ask-vps-hermes é internal-only e
        # nunca chega no disco dele (Fase 0/4) — mas _profile_runtime_scope
        # SEMPRE instala um escopo (mesmo vazio) pra qualquer turno real.
        client_scope_token = ss.set_secret_scope({})
        try:
            assert ss.get_secret("HERMES_VPS_API_SERVER_KEY") is None
        finally:
            ss.reset_secret_scope(client_scope_token)

    def test_google_service_account_canary_never_returned_with_empty_client_scope(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_SERVICE_ACCOUNT_KEY_JSON", CANARY_GOOGLE_JSON)
        ss.set_multiplex_active(True)

        client_scope_token = ss.set_secret_scope({})
        try:
            assert ss.get_secret("GOOGLE_SERVICE_ACCOUNT_KEY_JSON") is None
        finally:
            ss.reset_secret_scope(client_scope_token)

    def test_vps_key_fails_loud_when_no_scope_installed_at_all(self, monkeypatch):
        """Cenário hipotético mais grave que o de cima: um bug pula
        _profile_runtime_scope inteiro (nenhum set_secret_scope chamado pra
        esse turno) — aí sim tem que falhar alto, nunca vazar o canário."""
        monkeypatch.setenv("HERMES_VPS_API_SERVER_KEY", CANARY_VPS_KEY)
        ss.set_multiplex_active(True)

        with pytest.raises(ss.UnscopedSecretError):
            ss.get_secret("HERMES_VPS_API_SERVER_KEY")

    def test_governed_dispatch_never_resolves_canary_for_client_profile(self, monkeypatch, tmp_path):
        """Mesmo teste, mas passando pelo caminho de dispatch real
        (dispatch_guard.check -> build_scoped_env -> preflight_decision) que
        efetivamente roda antes de qualquer skill executar de verdade."""
        monkeypatch.setenv("HERMES_VPS_API_SERVER_KEY", CANARY_VPS_KEY)
        ss.set_multiplex_active(True)

        d = tmp_path / "ask_vps_hermes"
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "ask_vps.py").write_text("print('ran')\n", encoding="utf-8")
        import json
        (d / "contract.json").write_text(json.dumps({
            "id": "ask_vps_hermes", "enabled": True, "production_ready": True,
            "activation_stage": "production", "autonomy_ring": 1,
            "stop_conditions": ["manual"], "telemetry_events": ["ev"],
            "credentials": ["HERMES_VPS_API_SERVER_KEY"],
        }), encoding="utf-8")
        roots = {"ask_vps_hermes": d}

        # Perfil-cliente: escopo instalado, mas SEM a credencial (ela nunca
        # deveria estar no .env dele) -> bloqueado fail-closed, nunca cai
        # pro valor do container.
        client_scope_token = ss.set_secret_scope({})
        try:
            result = dg.check("python3 scripts/ask_vps.py", workdir=str(d), governed_roots=roots)
            assert result["action"] == "block"
            assert CANARY_VPS_KEY not in result["message"]
        finally:
            ss.reset_secret_scope(client_scope_token)


class TestConcurrentDogfoodAndPilotProfilesNeverCross:
    """Item 3 do roteiro: turnos concorrentes de dois perfis não cruzam —
    o "perfil dogfood" aqui simula ter a credencial real (canário), o
    "perfil piloto" simula não ter nenhuma. Ambos rodando ao mesmo tempo no
    mesmo event loop, provando isolamento sob concorrência real, não só
    sequencial."""

    @pytest.mark.asyncio
    async def test_dogfood_and_pilot_turns_concurrent_never_cross(self, monkeypatch, tmp_path):
        monkeypatch.setenv("HERMES_VPS_API_SERVER_KEY", "container-level-leak-should-never-be-used")
        ss.set_multiplex_active(True)

        d = tmp_path / "ask_vps_hermes"
        (d / "scripts").mkdir(parents=True)
        (d / "scripts" / "ask_vps.py").write_text("print('ran')\n", encoding="utf-8")
        import json
        (d / "contract.json").write_text(json.dumps({
            "id": "ask_vps_hermes", "enabled": True, "production_ready": True,
            "activation_stage": "production", "autonomy_ring": 1,
            "stop_conditions": ["manual"], "telemetry_events": ["ev"],
            "credentials": ["HERMES_VPS_API_SERVER_KEY"],
        }), encoding="utf-8")
        roots = {"ask_vps_hermes": d}

        async def _dogfood_turn():
            # "Dogfood" aqui = um perfil que LEGITIMAMENTE tem a credencial
            # (nunca é o perfil default real do Fernando — ver decisão de
            # arquitetura #3 do plano; é só pra provar que quem TEM a
            # credencial continua funcionando enquanto o outro não vê nada).
            tok = ss.set_secret_scope({"HERMES_VPS_API_SERVER_KEY": "dogfood-real-key"})
            try:
                await asyncio.sleep(0.01)
                result = dg.check("python3 scripts/ask_vps.py", workdir=str(d), governed_roots=roots)
                await asyncio.sleep(0.01)
                return result["action"]
            finally:
                ss.reset_secret_scope(tok)

        async def _pilot_turn():
            tok = ss.set_secret_scope({})
            try:
                await asyncio.sleep(0.015)
                result = dg.check("python3 scripts/ask_vps.py", workdir=str(d), governed_roots=roots)
                await asyncio.sleep(0.005)
                return result["action"], result["message"]
            finally:
                ss.reset_secret_scope(tok)

        dogfood_action, (pilot_action, pilot_message) = await asyncio.gather(_dogfood_turn(), _pilot_turn())

        assert dogfood_action == "allow"
        assert pilot_action == "block"
        assert "dogfood-real-key" not in pilot_message
        assert "container-level-leak" not in pilot_message
