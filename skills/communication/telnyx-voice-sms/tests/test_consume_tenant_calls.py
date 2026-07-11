"""
Testes de consume_tenant_calls.py SEM rede real.

`consume_tenant_calls` importa `requests` de forma preguiçosa (dentro de
_do_get_next/_do_post_credential/_do_post_status), então importar o módulo
aqui NÃO importa requests de verdade — substituímos essas três funções por
espiões (mesmo padrão de test_dispatch_job_dryrun.py com dispatch_job._do_post)
e make_call_fn por um dublê controlado, provando:

  - job reprovado por validate_job_gate NUNCA gera chamada de rede pra
    resolver credencial (falha ANTES);
  - falha ao resolver credencial nunca derruba o processo, vira "blocked" e
    é reportada;
  - make_call_fn é chamado com o `env` construído por build_tenant_env (a
    credencial certa, allowlist do destino certo) — nunca com os.environ real;
  - exceção de make_call_fn (ex.: TELNYX_CONNECTION_ID ausente, erro da API)
    vira "blocked" reportado, nunca uma exceção que escapa;
  - sent=True vira status "done"; dry_run/blocked viram "blocked";
  - fila vazia (poll devolve None) não tenta reportar status de nada.
"""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import consume_tenant_calls as ctc  # noqa: E402

APPROVED_JOB = {
    "id": "job-1",
    "task": "Ligar para +15005550006",
    "executor": "telnyx-call",
    "requires_human_gate": True,
    "result": {"approved_by": "fernando"},
    "tenant_call": {"org_id": "org_tenant_x", "to": "+15005550006", "message": "avisa que chegou"},
}

CREDENTIAL = {"apiKey": "sk-tenant-x-fake", "number": "+15005550006", "connectionId": "conn_abc"}


class _FakeResponse:
    def __init__(self, status_code=200, json_body=None, text=""):
        self.status_code = status_code
        self._json = json_body or {}
        self.text = text

    def json(self):
        return self._json


class ProcessJobTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_resolve = ctc.resolve_credential
        self.resolve_calls = []

    def tearDown(self):
        ctc.resolve_credential = self._orig_resolve

    def _stub_resolve(self, credential=CREDENTIAL, err=None):
        def _resolve(job_id, timeout=20):
            self.resolve_calls.append(job_id)
            return credential, err

        ctc.resolve_credential = _resolve

    def test_job_reprovado_por_validate_job_gate_nunca_toca_rede(self):
        self._stub_resolve()
        bad_job = {**APPROVED_JOB, "requires_human_gate": False}
        outcome = ctc.process_job(bad_job, make_call_fn=lambda **kw: self.fail("não deveria chamar make_call"))
        self.assertEqual(outcome["status"], "blocked")
        self.assertIn("requires_human_gate", outcome["result"]["error"])
        self.assertEqual(self.resolve_calls, [], "credencial nunca deve ser resolvida pra job reprovado")

    def test_falha_ao_resolver_credencial_vira_blocked_sem_crashar(self):
        self._stub_resolve(credential=None, err="Control Tower recusou (409)")
        outcome = ctc.process_job(APPROVED_JOB, make_call_fn=lambda **kw: self.fail("não deveria chamar make_call"))
        self.assertEqual(outcome["status"], "blocked")
        self.assertIn("409", outcome["result"]["error"])

    def test_make_call_chamado_com_env_por_tenant_nunca_os_environ_real(self):
        self._stub_resolve()
        captured = {}

        def fake_make_call(to, message, from_number=None, dry_run=True, env=None):
            captured.update(dict(to=to, message=message, from_number=from_number, dry_run=dry_run, env=env))
            return {"sent": False, "dry_run": True, "execute": False}

        ctc.process_job(APPROVED_JOB, dry_run=False, make_call_fn=fake_make_call, real_env={})
        self.assertEqual(captured["to"], "+15005550006")
        self.assertEqual(captured["from_number"], "+15005550006")
        self.assertIsNot(captured["env"], os.environ)
        self.assertEqual(captured["env"]["TELNYX_API_KEY"], "sk-tenant-x-fake")
        self.assertEqual(captured["env"]["TELNYX_ALLOWED_RECIPIENTS"], "+15005550006")

    def test_excecao_de_make_call_vira_blocked_sem_escapar(self):
        self._stub_resolve()

        def boom(**kwargs):
            raise RuntimeError("TELNYX_CONNECTION_ID não está no ambiente.")

        outcome = ctc.process_job(APPROVED_JOB, make_call_fn=boom)
        self.assertEqual(outcome["status"], "blocked")
        self.assertIn("TELNYX_CONNECTION_ID", outcome["result"]["error"])

    def test_sent_true_vira_done(self):
        self._stub_resolve()
        outcome = ctc.process_job(
            APPROVED_JOB,
            make_call_fn=lambda **kw: {"sent": True, "to": "+15005550006", "call_control_id": "ccid-1"},
        )
        self.assertEqual(outcome["status"], "done")

    def test_bloqueado_pela_politica_local_vira_blocked(self):
        self._stub_resolve()
        outcome = ctc.process_job(
            APPROVED_JOB,
            make_call_fn=lambda **kw: {"sent": False, "blocked": True, "reason": "destino fora da allowlist"},
        )
        self.assertEqual(outcome["status"], "blocked")
        self.assertEqual(outcome["result"]["error"], "destino fora da allowlist")


class RunOnceTestCase(unittest.TestCase):
    """Cobre poll_next_job/report_status via espiões nas fronteiras de rede
    (_do_get_next/_do_post_credential/_do_post_status) — mesmo padrão de
    dispatch_job._do_post em test_dispatch_job_dryrun.py."""

    def setUp(self):
        self._orig_get_next = ctc._do_get_next
        self._orig_post_cred = ctc._do_post_credential
        self._orig_post_status = ctc._do_post_status
        os.environ["HOUSE_INGEST_TOKEN"] = "fake-token-for-tests"
        self.status_calls = []

    def tearDown(self):
        ctc._do_get_next = self._orig_get_next
        ctc._do_post_credential = self._orig_post_cred
        ctc._do_post_status = self._orig_post_status
        os.environ.pop("HOUSE_INGEST_TOKEN", None)

    def _stub_status_spy(self):
        def _spy(url, headers, payload, timeout):
            self.status_calls.append({"url": url, "payload": payload})
            return _FakeResponse(200, {"ok": True})

        ctc._do_post_status = _spy

    def test_fila_vazia_nao_reporta_status_de_nada(self):
        ctc._do_get_next = lambda url, headers, timeout: _FakeResponse(204)
        self._stub_status_spy()
        summary = ctc.run_once()
        self.assertEqual(summary, {"polled": False})
        self.assertEqual(self.status_calls, [])

    def test_erro_ao_pedir_proximo_job_propaga(self):
        ctc._do_get_next = lambda url, headers, timeout: _FakeResponse(500, text="erro interno")
        with self.assertRaises(RuntimeError):
            ctc.run_once()

    def test_ciclo_completo_feliz_reporta_done(self):
        ctc._do_get_next = lambda url, headers, timeout: _FakeResponse(200, {"job": APPROVED_JOB})
        ctc._do_post_credential = lambda url, headers, timeout: _FakeResponse(200, {"credential": CREDENTIAL})
        self._stub_status_spy()

        summary = ctc.run_once(
            dry_run=False,
            make_call_fn=lambda **kw: {"sent": True, "to": "+15005550006", "call_control_id": "ccid-1"},
            real_env={"HERMES_ALLOW_EXECUTE": "true", "TENANT_TELNYX_CALLS_ENABLED": "true"},
        )
        self.assertEqual(summary["outcome"]["status"], "done")
        self.assertEqual(len(self.status_calls), 1)
        self.assertEqual(self.status_calls[0]["payload"]["status"], "done")

    def test_credencial_recusada_reporta_blocked_via_status(self):
        ctc._do_get_next = lambda url, headers, timeout: _FakeResponse(200, {"job": APPROVED_JOB})
        ctc._do_post_credential = lambda url, headers, timeout: _FakeResponse(409, text="uso único já consumido")
        self._stub_status_spy()

        summary = ctc.run_once(make_call_fn=lambda **kw: self.fail("não deveria chamar make_call"))
        self.assertEqual(summary["outcome"]["status"], "blocked")
        self.assertEqual(self.status_calls[0]["payload"]["status"], "blocked")

    def test_falha_ao_reportar_status_nunca_derruba_o_processo(self):
        ctc._do_get_next = lambda url, headers, timeout: _FakeResponse(200, {"job": APPROVED_JOB})
        ctc._do_post_credential = lambda url, headers, timeout: _FakeResponse(200, {"credential": CREDENTIAL})
        ctc._do_post_status = lambda url, headers, payload, timeout: _FakeResponse(500, text="fora do ar")

        # Não deve lançar mesmo com o report falhando.
        summary = ctc.run_once(make_call_fn=lambda **kw: {"sent": True, "to": "+1", "call_control_id": "x"})
        self.assertEqual(summary["outcome"]["status"], "done")


class TokenAndWorkerIdTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_token = os.environ.pop("HOUSE_INGEST_TOKEN", None)
        self._orig_ingest = os.environ.pop("INGEST_TOKEN", None)
        self._orig_worker = os.environ.pop("WORKER_ID", None)

    def tearDown(self):
        for key, value in (
            ("HOUSE_INGEST_TOKEN", self._orig_token),
            ("INGEST_TOKEN", self._orig_ingest),
            ("WORKER_ID", self._orig_worker),
        ):
            if value is not None:
                os.environ[key] = value
            else:
                os.environ.pop(key, None)

    def test_sem_token_lanca_erro_claro(self):
        with self.assertRaises(RuntimeError):
            ctc._token()

    def test_worker_id_explicito_via_env(self):
        os.environ["WORKER_ID"] = "vps-teste-1"
        self.assertEqual(ctc._worker_id(), "vps-teste-1")

    def test_worker_id_default_tem_prefixo_tenant_telnyx(self):
        self.assertTrue(ctc._worker_id().startswith("tenant-telnyx-"))


if __name__ == "__main__":
    unittest.main()
