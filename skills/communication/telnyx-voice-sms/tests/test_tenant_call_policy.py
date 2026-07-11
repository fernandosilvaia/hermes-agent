"""
Testes PUROS de _tenant_call_policy.py (consumidor telnyx-call tenant-scoped).

Sem rede, sem importar requests. Provam:
  - validate_job_gate reconfirma LOCALMENTE o gate humano (nunca confia
    cegamente no que veio da rede);
  - build_tenant_env nunca vaza a credencial da Axtro nem mistura ledgers
    entre orgs, e o gate sintético usa TENANT_TELNYX_CALLS_ENABLED (nunca
    TELNYX_VOICE_SMS_ENABLED real);
  - interpret_call_result mapeia sent/dry_run/blocked pro vocabulário de
    status do Control Tower sem nunca devolver "done" fora do caminho sent.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _tenant_call_policy as tcp  # noqa: E402

APPROVED_JOB = {
    "id": "job-1",
    "executor": "telnyx-call",
    "requires_human_gate": True,
    "result": {"approved_by": "fernando", "approved_at": 123},
    "tenant_call": {"org_id": "org_tenant_x", "to": "+15005550006", "message": "avisa que chegou"},
}


def approved_job(**overrides):
    job = {**APPROVED_JOB, "tenant_call": dict(APPROVED_JOB["tenant_call"])}
    for key, value in overrides.items():
        if key == "tenant_call":
            job["tenant_call"].update(value)
        else:
            job[key] = value
    return job


class ValidateJobGateTestCase(unittest.TestCase):
    def test_job_aprovado_e_bem_formado_passa_sem_problemas(self):
        self.assertEqual(tcp.validate_job_gate(approved_job()), [])

    def test_executor_errado_bloqueado(self):
        problems = tcp.validate_job_gate(approved_job(executor="shell"))
        self.assertTrue(any("executor" in p for p in problems))

    def test_requires_human_gate_false_bloqueado_mesmo_com_approved_by(self):
        # Defesa em profundidade: mesmo que result.approved_by esteja preenchido
        # (não deveria acontecer server-side, mas este módulo não confia cego).
        problems = tcp.validate_job_gate(approved_job(requires_human_gate=False))
        self.assertTrue(any("requires_human_gate" in p for p in problems))

    def test_sem_approved_by_bloqueado_mesmo_com_requires_human_gate_true(self):
        job = approved_job()
        job["result"] = {}
        problems = tcp.validate_job_gate(job)
        self.assertTrue(any("approved_by" in p for p in problems))

    def test_result_ausente_bloqueado(self):
        job = approved_job()
        del job["result"]
        problems = tcp.validate_job_gate(job)
        self.assertTrue(any("approved_by" in p for p in problems))

    def test_org_id_ausente_bloqueado(self):
        problems = tcp.validate_job_gate(approved_job(tenant_call={"org_id": ""}))
        self.assertTrue(any("org_id" in p for p in problems))

    def test_to_invalido_bloqueado(self):
        problems = tcp.validate_job_gate(approved_job(tenant_call={"to": "15005550006"}))  # sem '+'
        self.assertTrue(any("tenant_call.to" in p for p in problems))

    def test_tenant_call_ausente_bloqueado(self):
        job = approved_job()
        del job["tenant_call"]
        problems = tcp.validate_job_gate(job)
        self.assertTrue(any("org_id" in p for p in problems))
        self.assertTrue(any("tenant_call.to" in p for p in problems))

    def test_job_nao_dict_bloqueado_sem_crashar(self):
        self.assertEqual(tcp.validate_job_gate(None), ["job não é um objeto válido"])
        self.assertEqual(tcp.validate_job_gate("nao é job"), ["job não é um objeto válido"])


class OrgLedgerPathTestCase(unittest.TestCase):
    def test_usa_diretorio_default_e_sanitiza_org_id(self):
        path = tcp.org_ledger_path({}, "org/tenant weird!id")
        self.assertTrue(path.startswith("/opt/data/tenant_telnyx_ledgers/"))
        self.assertNotIn("/", os.path.basename(path).replace(".jsonl", ""))

    def test_respeita_TENANT_TELNYX_LEDGER_DIR(self):
        path = tcp.org_ledger_path({"TENANT_TELNYX_LEDGER_DIR": "/tmp/custom"}, "org_x")
        self.assertEqual(path, "/tmp/custom/org_x.jsonl")

    def test_orgs_diferentes_geram_ledgers_diferentes(self):
        p1 = tcp.org_ledger_path({}, "org_a")
        p2 = tcp.org_ledger_path({}, "org_b")
        self.assertNotEqual(p1, p2)


class BuildTenantEnvTestCase(unittest.TestCase):
    CREDENTIAL = {"apiKey": "sk-tenant-x-fake", "number": "+15005550006", "connectionId": "conn_abc"}

    def test_credencial_do_job_vai_pro_env_por_chamada(self):
        env = tcp.build_tenant_env(approved_job(), self.CREDENTIAL, real_env={})
        self.assertEqual(env["TELNYX_API_KEY"], "sk-tenant-x-fake")
        self.assertEqual(env["TELNYX_CONNECTION_ID"], "conn_abc")
        self.assertEqual(env["TELNYX_NUMBER"], "+15005550006")

    def test_allowlist_e_so_o_destino_deste_job(self):
        env = tcp.build_tenant_env(approved_job(), self.CREDENTIAL, real_env={})
        self.assertEqual(env["TELNYX_ALLOWED_RECIPIENTS"], "+15005550006")

    def test_gate_sintetico_usa_TENANT_TELNYX_CALLS_ENABLED_nunca_o_real(self):
        real_env = {"TENANT_TELNYX_CALLS_ENABLED": "true", "TELNYX_VOICE_SMS_ENABLED": "true"}
        env = tcp.build_tenant_env(approved_job(), self.CREDENTIAL, real_env=real_env)
        # O flag sintético reflete o gate do CONSUMIDOR TENANT, não o real da Axtro.
        self.assertEqual(env["TELNYX_VOICE_SMS_ENABLED"], "true")

    def test_ligar_flag_da_axtro_sozinha_nao_libera_o_gate_sintetico(self):
        real_env = {"TELNYX_VOICE_SMS_ENABLED": "true"}  # SEM TENANT_TELNYX_CALLS_ENABLED
        env = tcp.build_tenant_env(approved_job(), self.CREDENTIAL, real_env=real_env)
        self.assertEqual(env["TELNYX_VOICE_SMS_ENABLED"], "")  # gate sintético continua fechado

    def test_hermes_allow_execute_repassado_do_ambiente_real(self):
        env = tcp.build_tenant_env(approved_job(), self.CREDENTIAL, real_env={"HERMES_ALLOW_EXECUTE": "true"})
        self.assertEqual(env["HERMES_ALLOW_EXECUTE"], "true")

    def test_ledger_e_teto_sao_por_org(self):
        env = tcp.build_tenant_env(approved_job(), self.CREDENTIAL, real_env={})
        self.assertIn("org_tenant_x", env["TELNYX_SEND_LEDGER_PATH"])
        self.assertEqual(env["TELNYX_DAILY_SEND_CAP"], "5")

    def test_teto_diario_configuravel_via_TENANT_TELNYX_DAILY_CALL_CAP(self):
        env = tcp.build_tenant_env(approved_job(), self.CREDENTIAL, real_env={"TENANT_TELNYX_DAILY_CALL_CAP": "2"})
        self.assertEqual(env["TELNYX_DAILY_SEND_CAP"], "2")


class InterpretCallResultTestCase(unittest.TestCase):
    def test_sent_true_vira_done(self):
        outcome = tcp.interpret_call_result({"sent": True, "to": "+15005550006", "call_control_id": "abc"})
        self.assertEqual(outcome["status"], "done")
        self.assertIn("+15005550006", outcome["result"]["message"])

    def test_dry_run_vira_blocked_nunca_done(self):
        outcome = tcp.interpret_call_result({"dry_run": True, "execute": False, "sent": False})
        self.assertEqual(outcome["status"], "blocked")
        self.assertIn("dry-run", outcome["result"]["message"])

    def test_blocked_pela_politica_vira_blocked_com_motivo(self):
        outcome = tcp.interpret_call_result({"blocked": True, "sent": False, "reason": "destino fora da allowlist"})
        self.assertEqual(outcome["status"], "blocked")
        self.assertEqual(outcome["result"]["error"], "destino fora da allowlist")


if __name__ == "__main__":
    unittest.main()
