"""
Testes end-to-end de dispatch_job() SEM rede.

Provam que:
  - repo/branch/executor fora da política é bloqueado ANTES de qualquer POST;
  - o dry-run (default) monta o payload mas NUNCA chama o Control Tower;
  - o gate triplo só libera o POST real com as duas envs + sem --dry-run;
  - task de risco alto força requires_human_gate=true no payload enviado,
    mesmo pedindo false — E o dispatch ainda assim é permitido (o job só
    nasce pending_approval no Control Tower, quem bloqueia depois é o
    approve endpoint, não esta skill);
  - a skill nunca decide sozinha "quando" despachar — só reage ao que foi pedido.

`dispatch_job` importa `requests` de forma preguiçosa, então importar o
módulo aqui NÃO importa requests. Ainda assim, substituímos `_do_post` por
uma sentinela que registra chamadas e PROVA que nenhuma rede real é tocada.
"""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import dispatch_job as dj  # noqa: E402

CT_REPO = "/Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower"


class _PostSpy:
    """Substitui dispatch_job._do_post: registra o payload que seria enviado,
    sem tocar rede. Devolve uma resposta no formato de POST /api/hermes/jobs."""

    def __init__(self, status="pending_approval"):
        self.calls = []
        self.status = status

    def __call__(self, payload, timeout):
        self.calls.append({"payload": payload, "timeout": timeout})
        return {
            "ok": True,
            "job": {
                "id": "job-sentinela-0001",
                "branch": payload["branch"],
                "status": self.status,
                "requires_human_gate": payload["requires_human_gate"],
            },
        }


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


class DispatchJobTestCase(unittest.TestCase):
    def setUp(self):
        self._orig_post = dj._do_post
        self._orig_tel = dj._emit_telemetry
        self.spy = _PostSpy()
        dj._do_post = self.spy
        self.telemetry_calls = []
        dj._emit_telemetry = lambda *a, **k: self.telemetry_calls.append((a, k))

    def tearDown(self):
        dj._do_post = self._orig_post
        dj._emit_telemetry = self._orig_tel

    # ---- Bloqueio ANTES de qualquer rede -----------------------------

    def test_branch_fora_do_padrao_bloqueada_mesmo_com_gate_aberto(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        res = dj.dispatch_job(**base_kwargs(branch="main"), dry_run=False, env=env)
        self.assertTrue(res["blocked"])
        self.assertIsNone(res["job"])
        self.assertEqual(self.spy.calls, [], "NENHUM POST pode ocorrer num pedido bloqueado")

    def test_repo_fora_da_allowlist_bloqueado(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        res = dj.dispatch_job(**base_kwargs(repo_path="/tmp/repo-nao-confiavel"), dry_run=False, env=env)
        self.assertTrue(res["blocked"])
        self.assertEqual(self.spy.calls, [])

    # ---- DRY-RUN é o default e nunca chama o Control Tower -----------

    def test_dry_run_default_nao_chama_control_tower(self):
        res = dj.dispatch_job(**base_kwargs(), env={})
        self.assertFalse(res["blocked"])
        self.assertTrue(res["dry_run"])
        self.assertIsNone(res["job"])
        self.assertIsNotNone(res["payload"])
        self.assertEqual(self.spy.calls, [])

    def test_dry_run_explicito_vence_mesmo_com_envs(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        res = dj.dispatch_job(**base_kwargs(), dry_run=True, env=env)
        self.assertTrue(res["dry_run"])
        self.assertEqual(self.spy.calls, [])

    def test_gate_faltando_uma_env_fica_dry_run(self):
        env = {"HERMES_ALLOW_EXECUTE": "true"}  # falta DISPATCH_JOB_ENABLED
        res = dj.dispatch_job(**base_kwargs(), dry_run=False, env=env)
        self.assertTrue(res["dry_run"])
        self.assertEqual(self.spy.calls, [])

    # ---- Caminho feliz real: só com tudo verde ------------------------

    def test_execucao_liberada_envia_payload_com_gate_calculado(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        res = dj.dispatch_job(**base_kwargs(), requires_human_gate=False, dry_run=False, env=env)
        self.assertFalse(res["blocked"])
        self.assertFalse(res["dry_run"])
        self.assertIsNotNone(res["job"])
        self.assertEqual(len(self.spy.calls), 1)
        sent = self.spy.calls[0]["payload"]
        self.assertEqual(sent["branch"], "hermes/fix-null-check")
        self.assertFalse(sent["requires_human_gate"])  # task sem keyword, chamador pediu false -> respeita

    def test_telemetria_emitida_em_toda_decisao(self):
        dj.dispatch_job(**base_kwargs(), env={})
        self.assertTrue(self.telemetry_calls, "telemetria best-effort deve ser chamada")

    # ---- Regra de ouro: risco alto FORÇA o gate, mesmo com tudo liberado ----

    def test_task_risco_alto_forca_gate_true_mesmo_pedindo_false_e_com_execute_liberado(self):
        env = {"HERMES_ALLOW_EXECUTE": "true", "DISPATCH_JOB_ENABLED": "true"}
        res = dj.dispatch_job(
            **base_kwargs(task="aplicar uma migration destrutiva direto no banco de produção"),
            requires_human_gate=False,
            dry_run=False,
            env=env,
        )
        # A skill AINDA cria o job (esse é o comportamento correto: ela não
        # trava a dispatch por risco, ela garante que o job nasça gated) —
        # quem impede execução automática é o Control Tower (pending_approval).
        self.assertFalse(res["blocked"])
        self.assertEqual(len(self.spy.calls), 1)
        sent = self.spy.calls[0]["payload"]
        self.assertTrue(sent["requires_human_gate"], "risco alto tem que forçar o gate no payload enviado")
        self.assertIn("requires_human_gate=true", res["note"])

    def test_sem_declaracao_de_gate_default_seguro_true_no_payload_dry_run(self):
        res = dj.dispatch_job(**base_kwargs(), env={})  # requires_human_gate não declarado
        self.assertTrue(res["payload"]["requires_human_gate"])


class DispatchJobCliTestCase(unittest.TestCase):
    """A CLI nunca chama rede em modo dry-run (default), mesmo passando por argparse."""

    def setUp(self):
        self._orig_post = dj._do_post
        self._orig_tel = dj._emit_telemetry
        self.spy = _PostSpy()
        dj._do_post = self.spy
        dj._emit_telemetry = lambda *a, **k: None

    def tearDown(self):
        dj._do_post = self._orig_post
        dj._emit_telemetry = self._orig_tel

    def test_cli_dry_run_default_sem_flags_de_execucao(self):
        argv = [
            "--project-id", "control-tower",
            "--repo-path", CT_REPO,
            "--branch", "hermes/cli-test",
            "--executor", "claude-code",
            "--skill-id", "pr_builder_interno",
            "--task", "ajustar espaçamento de um botão",
            "--allowed-commands", "npm run test",
            "--expected-outputs", "fix aplicado",
        ]
        # dry-run permitido não chama sys.exit (só bloqueado chama, com exit 2).
        dj._cli(argv)
        self.assertEqual(self.spy.calls, [])

    def test_cli_bloqueado_sai_com_exit_code_2(self):
        argv = [
            "--project-id", "control-tower",
            "--repo-path", CT_REPO,
            "--branch", "main",  # inválida de propósito
            "--executor", "claude-code",
            "--skill-id", "pr_builder_interno",
            "--task", "algo",
            "--allowed-commands", "npm run test",
            "--expected-outputs", "fix aplicado",
        ]
        with self.assertRaises(SystemExit) as ctx:
            dj._cli(argv)
        self.assertEqual(ctx.exception.code, 2)
        self.assertEqual(self.spy.calls, [])


if __name__ == "__main__":
    unittest.main()
