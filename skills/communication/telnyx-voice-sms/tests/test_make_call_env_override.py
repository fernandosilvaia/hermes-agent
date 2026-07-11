"""
Testes de make_call.py — cobrem especificamente o refactor mínimo que
parametriza a credencial via `env` (para consume_tenant_calls.py), provando:

  - uso INTERNO da Axtro (sem passar `env`) continua idêntico: lê
    TELNYX_API_KEY/TELNYX_NUMBER de os.environ real, comportamento
    inalterado (regressão zero);
  - uso tenant-scoped (passando `env={...}`) usa a chave/número DAQUELE
    dict, nunca os.environ real, mesmo que os.environ tenha uma
    TELNYX_API_KEY diferente configurada (isolamento entre contas);
  - dry-run/blocked NUNCA chegam a ler TELNYX_API_KEY nem tocam
    requests.post (mesma garantia de _send_policy, ponta a ponta).

Mocka requests.post (não faz nenhuma chamada de rede real).
"""
import os
import sys
import unittest
from unittest import mock

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import make_call as mc  # noqa: E402

BOTH_GATES_OPEN = {"HERMES_ALLOW_EXECUTE": "true", "TELNYX_VOICE_SMS_ENABLED": "true"}


class ApiKeyEnvOverrideTestCase(unittest.TestCase):
    def test_sem_env_le_os_environ_real(self):
        with mock.patch.dict(os.environ, {"TELNYX_API_KEY": "sk-axtro-real"}, clear=False):
            self.assertEqual(mc._api_key(), "sk-axtro-real")

    def test_com_env_le_do_dict_passado_nunca_do_os_environ(self):
        with mock.patch.dict(os.environ, {"TELNYX_API_KEY": "sk-axtro-real"}, clear=False):
            self.assertEqual(mc._api_key({"TELNYX_API_KEY": "sk-tenant-x"}), "sk-tenant-x")

    def test_sem_a_chave_em_nenhum_dos_dois_lanca(self):
        with self.assertRaises(RuntimeError):
            mc._api_key({})


class MakeCallDryRunTestCase(unittest.TestCase):
    """Caminho dry-run/blocked nunca toca requests.post nem exige TELNYX_API_KEY."""

    @mock.patch("make_call.requests.post")
    def test_dry_run_nao_chama_rede_mesmo_sem_qualquer_credencial_no_env(self, post_mock):
        # Número default (própria allowlist quando `env` não declara TELNYX_NUMBER)
        # + --dry-run explícito: PERMITIDO mas nunca executa (plan["execute"]=False).
        plan = mc.make_call("+16174505166", "teste", dry_run=True, env={})
        self.assertTrue(plan["dry_run"])
        self.assertFalse(plan["execute"])
        self.assertFalse(plan["sent"])
        post_mock.assert_not_called()

    @mock.patch("make_call.requests.post")
    def test_terceiro_fora_da_allowlist_bloqueado_mesmo_com_gate_aberto(self, post_mock):
        env = {**BOTH_GATES_OPEN, "TELNYX_API_KEY": "sk-x", "TELNYX_CONNECTION_ID": "conn-x"}
        plan = mc.make_call("+15559998877", "teste", dry_run=False, env=env)
        self.assertTrue(plan["blocked"])
        self.assertFalse(plan["sent"])
        post_mock.assert_not_called()


class MakeCallTenantCredentialTestCase(unittest.TestCase):
    """Caminho real (gate aberto, destino permitido) usa a credencial do
    `env` passado — nunca a global do processo — provando o isolamento
    multi-tenant ponta a ponta."""

    def _tenant_env(self, **extra):
        env = {
            **BOTH_GATES_OPEN,
            "TELNYX_API_KEY": "sk-tenant-x",
            "TELNYX_CONNECTION_ID": "conn-tenant-x-abc",
            "TELNYX_NUMBER": "+15005550006",
            "TELNYX_ALLOWED_RECIPIENTS": "+15005550006",
        }
        env.update(extra)
        return env

    @mock.patch("make_call.requests.post")
    def test_chamada_real_usa_authorization_da_credencial_do_env_tenant(self, post_mock):
        post_mock.return_value = mock.Mock(
            status_code=200,
            json=lambda: {"data": {"call_control_id": "ccid-1", "call_leg_id": "leg-1"}},
        )
        with mock.patch.dict(os.environ, {"TELNYX_API_KEY": "sk-axtro-real-NUNCA-deve-ser-usada"}, clear=False):
            plan = mc.make_call(
                "+15005550006", "avisa que chegou",
                dry_run=False, env=self._tenant_env(),
            )

        self.assertTrue(plan["sent"])
        self.assertEqual(plan["call_control_id"], "ccid-1")
        _, kwargs = post_mock.call_args
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer sk-tenant-x")
        self.assertEqual(kwargs["json"]["connection_id"], "conn-tenant-x-abc")
        self.assertEqual(kwargs["json"]["from"], "+15005550006")

    @mock.patch("make_call.requests.post")
    def test_sem_connection_id_no_env_tenant_lanca_antes_de_tocar_rede(self, post_mock):
        env = self._tenant_env()
        del env["TELNYX_CONNECTION_ID"]
        with self.assertRaises(RuntimeError):
            mc.make_call("+15005550006", "oi", dry_run=False, env=env)
        post_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
