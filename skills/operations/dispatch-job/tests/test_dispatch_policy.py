"""
Testes PUROS da política da skill dispatch-job.

Rodam no python3 do sistema (3.9.6) SEM rede e SEM importar requests.
Provam: allowlist de repo, validação de branch/executor, o veto por keyword
de risco alto (não pode ser burlado passando requires_human_gate=False), o
default seguro (True) quando o chamador não declara nada, e o gate triplo de
execução (dry-run + HERMES_ALLOW_EXECUTE + DISPATCH_JOB_ENABLED).
"""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import _dispatch_policy as policy  # noqa: E402

CT_REPO = "/Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower"
HERMES_REPO = "/Users/fernandosilva/Developer/AxtroAI/02_PRODUTOS/lab/hermes-agent"


def base_kwargs(**overrides):
    kwargs = dict(
        project_id="control-tower",
        repo_path=CT_REPO,
        branch="hermes/fix-null-check",
        executor="claude-code",
        skill_id="pr_builder_interno",
        task="corrigir null-check em src/app/api/leads/route.ts, adicionar teste de regressão",
        allowed_commands=["npm run test", "npm run typecheck"],
        expected_outputs=["teste de regressão", "fix aplicado"],
    )
    kwargs.update(overrides)
    return kwargs


class TestRepoAllowlist(unittest.TestCase):
    def test_repo_no_default_allowlist_permitido(self):
        problems = policy.validate_request(**base_kwargs())
        self.assertEqual(problems, [])

    def test_repo_hermes_agent_tambem_permitido(self):
        problems = policy.validate_request(**base_kwargs(repo_path=HERMES_REPO))
        self.assertEqual(problems, [])

    def test_repo_fora_da_allowlist_bloqueado(self):
        problems = policy.validate_request(**base_kwargs(repo_path="/tmp/repo-qualquer"))
        self.assertTrue(any("allowlist" in p for p in problems))

    def test_repo_allowlist_via_env_sobrescreve_default(self):
        custom = ["/Users/fernandosilva/algum-repo-custom"]
        problems = policy.validate_request(
            **base_kwargs(repo_path="/Users/fernandosilva/algum-repo-custom"),
            repo_allowlist=custom,
        )
        self.assertEqual(problems, [])
        # o repo default NÃO está mais liberado se a allowlist foi sobrescrita
        problems2 = policy.validate_request(**base_kwargs(repo_path=CT_REPO), repo_allowlist=custom)
        self.assertTrue(any("allowlist" in p for p in problems2))

    def test_repo_allowlist_from_env_le_env_var(self):
        env = {"AXTRO_REPO_ALLOWLIST": "/a/b, /c/d"}
        self.assertEqual(policy.repo_allowlist_from_env(env), ["/a/b", "/c/d"])

    def test_repo_allowlist_from_env_vazio_usa_default(self):
        self.assertEqual(policy.repo_allowlist_from_env({}), list(policy.DEFAULT_REPO_ALLOWLIST))


class TestBranchEExecutor(unittest.TestCase):
    def test_branch_fora_do_padrao_hermes_bloqueada(self):
        problems = policy.validate_request(**base_kwargs(branch="main"))
        self.assertTrue(any("hermes/" in p for p in problems))

    def test_branch_hermes_permitida(self):
        problems = policy.validate_request(**base_kwargs(branch="hermes/qualquer-coisa"))
        self.assertEqual(problems, [])

    def test_executor_codex_bloqueado(self):
        problems = policy.validate_request(**base_kwargs(executor="codex"))
        self.assertTrue(any("executor" in p for p in problems))

    def test_executor_shell_permitido(self):
        problems = policy.validate_request(**base_kwargs(executor="shell"))
        self.assertEqual(problems, [])


class TestCamposObrigatorios(unittest.TestCase):
    def test_task_vazia_bloqueada(self):
        problems = policy.validate_request(**base_kwargs(task=""))
        self.assertTrue(any("task" in p for p in problems))

    def test_allowed_commands_vazio_bloqueado(self):
        problems = policy.validate_request(**base_kwargs(allowed_commands=[]))
        self.assertTrue(any("allowed_commands" in p for p in problems))

    def test_expected_outputs_vazio_bloqueado(self):
        problems = policy.validate_request(**base_kwargs(expected_outputs=[]))
        self.assertTrue(any("expected_outputs" in p for p in problems))

    def test_max_runtime_acima_do_teto_bloqueado(self):
        problems = policy.validate_request(**base_kwargs(max_runtime_minutes=999))
        self.assertTrue(any("max_runtime_minutes" in p for p in problems))

    def test_max_cost_acima_do_teto_bloqueado(self):
        problems = policy.validate_request(**base_kwargs(max_cost_usd=999))
        self.assertTrue(any("max_cost_usd" in p for p in problems))


class TestClassifyRisk(unittest.TestCase):
    def test_sem_keyword_e_sem_declaracao_default_seguro_true(self):
        r = policy.classify_risk("corrigir um typo no botão de login da tela")
        self.assertTrue(r["effective_gate"])
        self.assertFalse(r["forced"])

    def test_sem_keyword_chamador_pode_declarar_false(self):
        r = policy.classify_risk("corrigir um typo no botão da tela", requires_human_gate=False)
        self.assertFalse(r["effective_gate"])
        self.assertFalse(r["forced"])

    def test_sem_keyword_chamador_pode_declarar_true(self):
        r = policy.classify_risk("corrigir um typo", requires_human_gate=True)
        self.assertTrue(r["effective_gate"])

    def test_keyword_banco_forca_true_mesmo_pedindo_false(self):
        r = policy.classify_risk("rodar uma migration no banco de dados", requires_human_gate=False)
        self.assertTrue(r["effective_gate"])
        self.assertTrue(r["forced"])
        self.assertIn("migration", " ".join(r["matched_keywords"]))

    def test_keyword_auth_forca_true(self):
        r = policy.classify_risk("mudar a lógica de autenticação do login", requires_human_gate=False)
        self.assertTrue(r["effective_gate"])
        self.assertTrue(r["forced"])

    def test_keyword_pagamento_forca_true(self):
        r = policy.classify_risk("integrar cobrança via Stripe", requires_human_gate=False)
        self.assertTrue(r["effective_gate"])
        self.assertTrue(r["forced"])

    def test_keyword_deploy_producao_forca_true(self):
        r = policy.classify_risk("fazer deploy em produção", requires_human_gate=False)
        self.assertTrue(r["effective_gate"])
        self.assertTrue(r["forced"])

    def test_keyword_secret_env_forca_true(self):
        r = policy.classify_risk("adicionar uma nova SECRET_KEY no .env", requires_human_gate=False)
        self.assertTrue(r["effective_gate"])
        self.assertTrue(r["forced"])

    def test_keyword_delete_forca_true(self):
        r = policy.classify_risk("deletar os registros antigos da tabela de logs", requires_human_gate=False)
        self.assertTrue(r["effective_gate"])
        self.assertTrue(r["forced"])

    def test_find_high_risk_keywords_vazio_quando_nao_bate(self):
        self.assertEqual(policy.find_high_risk_keywords("ajustar o espaçamento do botão"), [])

    def test_find_high_risk_keywords_none_nao_crasha(self):
        self.assertEqual(policy.find_high_risk_keywords(None), [])


class TestBuildPayload(unittest.TestCase):
    def test_payload_inclui_forbidden_commands_default(self):
        payload, risk = policy.build_payload(**base_kwargs(), requires_human_gate=False)
        self.assertIn("git push origin main", payload["forbidden_commands"])
        self.assertIn("rm -rf /", payload["forbidden_commands"])

    def test_payload_uniao_forbidden_customizado_com_default(self):
        payload, risk = policy.build_payload(
            **base_kwargs(), forbidden_commands=["npm publish"], requires_human_gate=False,
        )
        self.assertIn("npm publish", payload["forbidden_commands"])
        self.assertIn("git push origin main", payload["forbidden_commands"])

    def test_payload_requires_human_gate_reflete_risco_calculado(self):
        payload, risk = policy.build_payload(
            **base_kwargs(task="rodar migration no banco"), requires_human_gate=False,
        )
        self.assertTrue(payload["requires_human_gate"])
        self.assertTrue(risk["forced"])

    def test_payload_agent_id_opcional(self):
        payload, _ = policy.build_payload(**base_kwargs(), requires_human_gate=True)
        self.assertNotIn("agent_id", payload)
        payload2, _ = policy.build_payload(**base_kwargs(), requires_human_gate=True, agent_id="hermes-daemon")
        self.assertEqual(payload2["agent_id"], "hermes-daemon")


class TestGateTriplo(unittest.TestCase):
    def test_gate_fechado_por_default(self):
        self.assertFalse(policy.gate_allows_execute(False, env={}))

    def test_dry_run_explicito_sempre_vence(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        self.assertFalse(policy.gate_allows_execute(True, env=env))

    def test_falta_uma_env_fica_fechado(self):
        env = {"HERMES_ALLOW_EXECUTE": "true"}
        self.assertFalse(policy.gate_allows_execute(False, env=env))
        env2 = {"DISPATCH_JOB_ENABLED": "true"}
        self.assertFalse(policy.gate_allows_execute(False, env=env2))

    def test_com_as_duas_envs_e_sem_dry_run_abre(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        self.assertTrue(policy.gate_allows_execute(False, env=env))


class TestPlanDispatch(unittest.TestCase):
    def test_plan_bloqueado_nao_tem_payload(self):
        plan = policy.plan_dispatch(**base_kwargs(branch="main"), dry_run=True, env={})
        self.assertEqual(plan["decision"], "BLOQUEADO")
        self.assertIsNone(plan["payload"])
        self.assertFalse(plan["would_execute"])

    def test_plan_permitido_dry_run_default_nao_executa(self):
        plan = policy.plan_dispatch(**base_kwargs(), dry_run=True, env={})
        self.assertEqual(plan["decision"], "PERMITIDO")
        self.assertIsNotNone(plan["payload"])
        self.assertTrue(plan["dry_run"])
        self.assertFalse(plan["would_execute"])

    def test_plan_permitido_com_gate_aberto_executaria(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        plan = policy.plan_dispatch(
            **base_kwargs(), requires_human_gate=False, dry_run=False, env=env,
        )
        self.assertEqual(plan["decision"], "PERMITIDO")
        self.assertFalse(plan["dry_run"])
        self.assertTrue(plan["would_execute"])

    def test_plan_risco_alto_mesmo_com_gate_aberto_ainda_nasce_gated(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        plan = policy.plan_dispatch(
            **base_kwargs(task="aplicar migration destrutiva no banco de produção"),
            requires_human_gate=False, dry_run=False, env=env,
        )
        # A skill EXECUTA o dispatch (POST liberado), mas o JOB nasce gated —
        # seria pending_approval no Control Tower, não queued.
        self.assertTrue(plan["would_execute"])
        self.assertTrue(plan["payload"]["requires_human_gate"])
        self.assertTrue(plan["risk"]["forced"])


if __name__ == "__main__":
    unittest.main()
