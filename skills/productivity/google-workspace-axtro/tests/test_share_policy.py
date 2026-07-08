"""
Testes da guarda-corpo PURA de compartilhamento do Drive (_share_policy.py).

Sem rede, sem credenciais, sem googleapiclient — importa SÓ _share_policy, que é
stdlib-puro (os, re). Roda no python3 do sistema (3.9.6):

    python3 -m unittest discover -s tests -v

Prova o P0 fechado (canal de exfiltração): um destinatário externo — o vetor de
um prompt-injection num daemon 24/7 — é BLOQUEADO antes de qualquer chamada de API,
com destaque para role=writer.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _share_policy  # noqa: E402


class EvaluateShareTestCase(unittest.TestCase):
    # Ambiente controlado: força a allowlist default (só axtroai.com) por teste,
    # sem depender do ambiente real.
    ENV_DEFAULT = {}  # sem GOOGLE_WORKSPACE_SHARE_ALLOWED_DOMAINS → default axtroai.com

    def test_internal_reader_is_allowed(self):
        v = _share_policy.evaluate_share(
            "colega@axtroai.com", "reader", approve_external=False, env=self.ENV_DEFAULT)
        self.assertEqual(v["decision"], "PERMITIDO")
        self.assertFalse(v["is_external"])
        self.assertEqual(v["reasons"], [])

    def test_internal_writer_is_allowed(self):
        # writer para o PRÓPRIO domínio é uso legítimo — não pode ser bloqueado.
        v = _share_policy.evaluate_share(
            "colega@axtroai.com", "writer", approve_external=False, env=self.ENV_DEFAULT)
        self.assertEqual(v["decision"], "PERMITIDO")
        self.assertFalse(v["is_external"])

    def test_external_reader_without_approval_is_blocked(self):
        v = _share_policy.evaluate_share(
            "estranho@gmail.com", "reader", approve_external=False, env=self.ENV_DEFAULT)
        self.assertEqual(v["decision"], "BLOQUEADO")
        self.assertTrue(v["is_external"])
        self.assertTrue(any("externo" in r for r in v["reasons"]))

    def test_external_writer_is_blocked_the_exfiltration_attack(self):
        # P0: prompt-injection manda compartilhar arquivo corporativo como writer
        # com um email de fora. TEM que ser bloqueado sem approve_external.
        v = _share_policy.evaluate_share(
            "attacker@evil-corp.com", "writer", approve_external=False, env=self.ENV_DEFAULT)
        self.assertEqual(v["decision"], "BLOQUEADO")
        self.assertTrue(v["is_external"])
        self.assertTrue(any("writer" in r for r in v["reasons"]))

    # Domínio de parceiro pré-aprovado FORA DE BANDA (env) — só assim o externo passa.
    ENV_PARTNER = {"GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS": "gmail.com"}

    def test_external_with_explicit_approval_is_allowed(self):
        # approve_external + domínio na allowlist de parceiros (env) → passa.
        v = _share_policy.evaluate_share(
            "parceiro@gmail.com", "reader", approve_external=True, env=self.ENV_PARTNER)
        self.assertEqual(v["decision"], "PERMITIDO")
        self.assertTrue(v["is_external"])

    def test_external_writer_with_explicit_approval_is_allowed(self):
        v = _share_policy.evaluate_share(
            "parceiro@gmail.com", "writer", approve_external=True, env=self.ENV_PARTNER)
        self.assertEqual(v["decision"], "PERMITIDO")

    def test_external_approve_but_domain_not_in_partner_allowlist_is_blocked(self):
        # REGRESSÃO (bypass A): approve_external é setável pelo agente. Sozinha ela
        # NÃO pode liberar um domínio arbitrário — o destino tem que estar na env de
        # parceiros. Sem isso, um prompt-injection auto-aprova e exfiltra.
        v = _share_policy.evaluate_share(
            "attacker@evil-corp.com", "reader", approve_external=True, env=self.ENV_DEFAULT)
        self.assertEqual(v["decision"], "BLOQUEADO")
        self.assertTrue(any("allowlist de parceiros" in r for r in v["reasons"]))

    def test_external_approve_and_in_partner_allowlist_is_allowed(self):
        env = {"GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS": "parceiro.com"}
        v = _share_policy.evaluate_share(
            "gente@parceiro.com", "reader", approve_external=True, env=env)
        self.assertEqual(v["decision"], "PERMITIDO")
        self.assertTrue(v["is_external"])

    def test_malformed_email_is_blocked(self):
        for bad in ["not-an-email", "sem-arroba.com", "vazio@", "@semlocal.com",
                    "dois@@arrobas.com", "espaco @axtroai.com", "", None]:
            v = _share_policy.evaluate_share(bad, "reader", env=self.ENV_DEFAULT)
            self.assertEqual(v["decision"], "BLOQUEADO", "deveria bloquear: {!r}".format(bad))
            self.assertIn("email invalido", v["reasons"])

    def test_domain_without_dot_is_invalid(self):
        v = _share_policy.evaluate_share("foo@bar", "reader", env=self.ENV_DEFAULT)
        self.assertEqual(v["decision"], "BLOQUEADO")
        self.assertIn("email invalido", v["reasons"])

    def test_custom_allowlist_env_is_respected(self):
        env = {"GOOGLE_WORKSPACE_SHARE_ALLOWED_DOMAINS": "axtroai.com, parceiro.com"}
        # domínio adicionado à allowlist deixa de ser externo
        v = _share_policy.evaluate_share("gente@parceiro.com", "reader",
                                         approve_external=False, env=env)
        self.assertEqual(v["decision"], "PERMITIDO")
        self.assertFalse(v["is_external"])
        # gmail continua externo mesmo com a allowlist custom
        v2 = _share_policy.evaluate_share("x@gmail.com", "reader",
                                          approve_external=False, env=env)
        self.assertEqual(v2["decision"], "BLOQUEADO")

    def test_domain_match_is_case_insensitive(self):
        v = _share_policy.evaluate_share("Colega@AxtroAI.COM", "reader", env=self.ENV_DEFAULT)
        self.assertEqual(v["decision"], "PERMITIDO")
        self.assertEqual(v["domain"], "axtroai.com")

    def test_empty_allowlist_env_falls_back_to_company_domain(self):
        env = {"GOOGLE_WORKSPACE_SHARE_ALLOWED_DOMAINS": "  , ,"}
        self.assertEqual(_share_policy._load_share_allowlist(env), ["axtroai.com"])


class ResolveExecutionTestCase(unittest.TestCase):
    """GATE PADRÃO de dry-run — funções puras, env injetável."""

    BOTH_ON = {"HERMES_ALLOW_EXECUTE": "true", "GOOGLE_WORKSPACE_AXTRO_ENABLED": "true"}

    def test_default_is_dry_run_with_no_envs(self):
        # dry_run_flag=True (default sem --execute) → sempre dry-run.
        m = _share_policy.resolve_execution(dry_run_flag=True, env={})
        self.assertFalse(m["execute"])
        self.assertTrue(m["dry_run"])

    def test_execute_intent_without_envs_stays_dry_run(self):
        # --execute (dry_run_flag=False) mas sem as envs → continua dry-run.
        m = _share_policy.resolve_execution(dry_run_flag=False, env={})
        self.assertFalse(m["execute"])
        self.assertTrue(m["dry_run"])

    def test_execute_with_only_one_env_stays_dry_run(self):
        m = _share_policy.resolve_execution(
            dry_run_flag=False, env={"HERMES_ALLOW_EXECUTE": "true"})
        self.assertFalse(m["execute"])

    def test_all_conditions_true_allows_execution(self):
        m = _share_policy.resolve_execution(dry_run_flag=False, env=self.BOTH_ON)
        self.assertTrue(m["execute"])
        self.assertFalse(m["dry_run"])

    def test_explicit_dry_run_always_wins_even_with_envs(self):
        # Humano forçou --dry-run: mesmo com as duas envs true, tem que ser dry-run.
        m = _share_policy.resolve_execution(dry_run_flag=True, env=self.BOTH_ON)
        self.assertFalse(m["execute"])
        self.assertTrue(m["dry_run"])

    def test_envs_must_be_exactly_true(self):
        for junk in ["1", "yes", "TRUE ", "True", "false", ""]:
            env = {"HERMES_ALLOW_EXECUTE": junk, "GOOGLE_WORKSPACE_AXTRO_ENABLED": junk}
            m = _share_policy.resolve_execution(dry_run_flag=False, env=env)
            # só "true"/"TRUE"/"  true  " (case+trim) contam; "True" também é aceito
            expected = junk.strip().lower() == "true"
            self.assertEqual(m["execute"], expected, "valor: {!r}".format(junk))


if __name__ == "__main__":
    unittest.main()
