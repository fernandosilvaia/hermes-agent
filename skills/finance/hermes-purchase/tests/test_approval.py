"""
Testes de ENFORCEMENT do gate humano de compra (P0).

Provam, sem rede e sem Telegram real (roda no python3 do sistema, 3.9.6):
  - o token cru nunca vai para o stdout do daemon (só o hash sha256 no ledger);
  - confirm com token errado/ausente RECUSA (o daemon não pode se auto-aprovar);
  - confirm com token certo mas SEM a env humana HERMES_PURCHASE_ALLOW_CONFIRM RECUSA;
  - confirm com token certo + env humana + gate de execução ACEITA (libera o teto);
  - amount NaN/Infinity é BLOQUEADO na policy;
  - toda tentativa vira linha em audit.log — sem o token cru.

    python3 -m unittest discover -s tests -v
"""

import argparse
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import policy  # noqa: E402
import _approval  # noqa: E402
import request_purchase as rp  # noqa: E402

SENTINEL = "SENTINEL-TOKEN-abc123XYZ"  # token conhecido só para os testes


def _run(func, ns, env):
    """Executa um cmd_* capturando stdout e o exit code (SystemExit)."""
    buf = io.StringIO()
    code = 0
    with contextlib.redirect_stdout(buf):
        try:
            func(ns, env=env)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
    return buf.getvalue(), code


# ---------------------------------------------------------------------------
# 1. Funções PURAS de decisão (sem I/O, sem rede)
# ---------------------------------------------------------------------------
class PureDecisionTestCase(unittest.TestCase):
    def setUp(self):
        self.hash = _approval.hash_token(SENTINEL)
        self.env_full = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}

    def test_verify_token_roundtrip(self):
        self.assertTrue(_approval.verify_token(SENTINEL, self.hash))
        self.assertFalse(_approval.verify_token("outro", self.hash))
        self.assertFalse(_approval.verify_token(None, self.hash))
        self.assertFalse(_approval.verify_token(SENTINEL, None))

    def test_generate_token_is_random_and_unmasked_output_is_redacted(self):
        self.assertNotEqual(_approval.generate_token(), _approval.generate_token())
        self.assertEqual(_approval.mask_token(SENTINEL), "[REDIGIDO]")

    def test_decide_confirm_missing_token_is_refused(self):
        d = _approval.decide_confirm(None, self.hash, self.env_full, False)
        self.assertEqual(d["decision"], "RECUSADA_SEM_TOKEN")
        self.assertNotEqual(d["exit_code"], 0)

    def test_decide_confirm_wrong_token_is_refused(self):
        d = _approval.decide_confirm("token-errado", self.hash, self.env_full, False)
        self.assertEqual(d["decision"], "RECUSADA_TOKEN_INVALIDO")
        self.assertNotEqual(d["exit_code"], 0)

    def test_decide_confirm_right_token_without_human_env_is_refused(self):
        env = {"HERMES_ALLOW_EXECUTE": "true"}  # falta HERMES_PURCHASE_ALLOW_CONFIRM
        d = _approval.decide_confirm(SENTINEL, self.hash, env, False)
        self.assertEqual(d["decision"], "RECUSADA_SEM_ENV_HUMANA")
        self.assertNotEqual(d["exit_code"], 0)

    def test_decide_confirm_right_token_and_env_but_no_global_execute_is_dry_run(self):
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true"}  # falta HERMES_ALLOW_EXECUTE
        d = _approval.decide_confirm(SENTINEL, self.hash, env, False)
        self.assertEqual(d["decision"], "DRY_RUN")
        self.assertTrue(d["dry_run"])
        self.assertEqual(d["exit_code"], 0)

    def test_decide_confirm_all_gates_open_confirms(self):
        d = _approval.decide_confirm(SENTINEL, self.hash, self.env_full, False)
        self.assertEqual(d["decision"], "CONFIRMAR")
        self.assertFalse(d["dry_run"])

    def test_decide_confirm_dry_run_flag_always_wins(self):
        # mesmo com token certo + todas as envs, --dry-run força o modo seguro
        d = _approval.decide_confirm(SENTINEL, self.hash, self.env_full, True)
        self.assertEqual(d["decision"], "DRY_RUN")
        self.assertTrue(d["dry_run"])

    def test_decide_notify_requires_all_gates(self):
        env_ok = {"HERMES_ALLOW_EXECUTE": "true", "HERMES_PURCHASE_ENABLED": "true"}
        self.assertTrue(_approval.decide_notify(env_ok, False, True)["send"])
        self.assertFalse(_approval.decide_notify(env_ok, True, True)["send"])   # dry-run
        self.assertFalse(_approval.decide_notify(env_ok, False, False)["send"])  # sem notify
        self.assertFalse(_approval.decide_notify({}, False, True)["send"])       # sem envs

    def test_would_exceed_monthly_cap_is_binding_at_confirm(self):
        entries = [
            {"id": "a", "month": "2026-07", "status": "aprovada", "amount": 300.0},
            {"id": "b", "month": "2026-07", "status": "pendente", "amount": 300.0},
        ]
        # aprovar b (300) com 300 já aprovado estoura o teto de 500
        self.assertTrue(_approval.would_exceed_monthly_cap(entries, "b", "2026-07", 300.0, 500.0))
        # dentro do teto (b=150) não estoura
        self.assertFalse(_approval.would_exceed_monthly_cap(entries, "b", "2026-07", 150.0, 500.0))
        # exclui a própria entrada -> idempotente numa re-confirmação aprovada->paga
        self.assertFalse(_approval.would_exceed_monthly_cap(entries, "a", "2026-07", 300.0, 500.0))
        # valor não-finito / cap inválido -> fail-closed (True)
        self.assertTrue(_approval.would_exceed_monthly_cap(entries, "b", "2026-07", float("inf"), 500.0))
        self.assertTrue(_approval.would_exceed_monthly_cap(entries, "b", "2026-07", 100.0, float("nan")))

    def test_build_messages_never_leaks_token_to_daemon(self):
        daemon_msg, human_msg = _approval.build_messages(
            "id1", "OpenRouter", 120.0, "recarga", 0.0, 500.0, SENTINEL)
        # o token cru NÃO pode aparecer na mensagem que o daemon vê (stdout)
        self.assertNotIn(SENTINEL, daemon_msg)
        # mas aparece na mensagem que vai SÓ para o Telegram do dono
        self.assertIn(SENTINEL, human_msg)
        self.assertIn("--approval-token", human_msg)


# ---------------------------------------------------------------------------
# 2. Fluxo real (request + confirm) com ledger/audit temporários, sem rede
# ---------------------------------------------------------------------------
class RequestConfirmTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        d = Path(self.tmp.name)
        # ledger/config/audit isolados — nunca tocam os reais
        policy.CONFIG_PATH = d / "config.json"
        policy.LEDGER_PATH = d / "ledger.jsonl"
        rp.AUDIT_PATH = d / "audit.log"
        policy.CONFIG_PATH.write_text(json.dumps({
            "currency": "BRL", "monthly_cap": 500.0, "per_purchase_cap": 300.0,
            "vendor_allowlist": ["OpenRouter", "Railway", "Anthropic"],
        }), encoding="utf-8")
        # token determinístico para poder afirmar "não vazou"
        self._orig_gen = _approval.generate_token
        _approval.generate_token = lambda: SENTINEL
        self.addCleanup(self._restore_gen)

    def _restore_gen(self):
        _approval.generate_token = self._orig_gen

    def _request(self, vendor="OpenRouter", amount=120.0, reason="recarga", notify=False,
                 dry_run=False, env=None):
        ns = argparse.Namespace(vendor=vendor, amount=amount, reason=reason,
                                notify=notify, dry_run=dry_run)
        return _run(rp.cmd_request, ns, env if env is not None else {})

    def _confirm(self, pid, status="aprovada", token=None, dry_run=False, env=None):
        ns = argparse.Namespace(id=pid, status=status, approval_token=token, dry_run=dry_run)
        return _run(rp.cmd_confirm, ns, env if env is not None else {})

    def _first_id(self):
        entries = policy.load_ledger()
        return entries[0]["id"]

    # ---- request ----------------------------------------------------------
    def test_request_writes_hash_but_never_leaks_token_to_stdout(self):
        out, code = self._request()
        self.assertEqual(code, 0)
        # o token cru NUNCA aparece no stdout que o daemon lê
        self.assertNotIn(SENTINEL, out)
        # mas o HASH do token ESTÁ gravado no ledger
        entries = policy.load_ledger()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["approval_token_sha256"], hashlib.sha256(SENTINEL.encode()).hexdigest())
        self.assertEqual(entries[0]["status"], "pendente")
        # e o hash inteiro também não é despejado no stdout
        self.assertNotIn(entries[0]["approval_token_sha256"], out)

    def test_request_dry_run_writes_nothing(self):
        out, code = self._request(dry_run=True)
        self.assertEqual(code, 0)
        self.assertIn('"dry_run": true', out)
        self.assertEqual(policy.load_ledger(), [])  # nada gravado
        self.assertNotIn(SENTINEL, out)

    def test_request_blocked_by_policy_for_bad_vendor(self):
        out, code = self._request(vendor="Loja Pirata")
        self.assertEqual(code, 2)
        self.assertIn("BLOQUEADA", out)
        self.assertEqual(policy.load_ledger(), [])

    # ---- confirm: o coração do P0 ----------------------------------------
    def test_confirm_auto_approval_without_token_is_refused(self):
        # ATAQUE: o daemon usa o MESMO CLI e tenta confirmar só com o id.
        self._request()
        pid = self._first_id()
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}
        out, code = self._confirm(pid, token=None, env=env)
        self.assertNotEqual(code, 0)
        self.assertIn("RECUSADA_SEM_TOKEN", out)
        # status NÃO mudou -> teto não foi liberado
        self.assertEqual(policy.load_ledger()[0]["status"], "pendente")
        self.assertEqual(policy.month_to_date_spent(), 0.0)

    def test_confirm_wrong_token_is_refused(self):
        self._request()
        pid = self._first_id()
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}
        out, code = self._confirm(pid, token="chute-errado", env=env)
        self.assertNotEqual(code, 0)
        self.assertIn("RECUSADA_TOKEN_INVALIDO", out)
        self.assertEqual(policy.load_ledger()[0]["status"], "pendente")

    def test_confirm_right_token_without_human_env_is_refused(self):
        self._request()
        pid = self._first_id()
        # daemon tem HERMES_ALLOW_EXECUTE mas NÃO tem a env humana
        env = {"HERMES_ALLOW_EXECUTE": "true"}
        out, code = self._confirm(pid, token=SENTINEL, env=env)
        self.assertNotEqual(code, 0)
        self.assertIn("RECUSADA_SEM_ENV_HUMANA", out)
        self.assertEqual(policy.load_ledger()[0]["status"], "pendente")
        self.assertEqual(policy.month_to_date_spent(), 0.0)

    def test_confirm_right_token_with_human_env_accepts(self):
        # CAMINHO LEGÍTIMO: humano com token do Telegram + env humana + gate de execução.
        self._request()
        pid = self._first_id()
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}
        out, code = self._confirm(pid, token=SENTINEL, env=env)
        self.assertEqual(code, 0)
        self.assertIn("CONFIRMAR", out)
        self.assertEqual(policy.load_ledger()[0]["status"], "aprovada")
        self.assertEqual(policy.month_to_date_spent(), 120.0)  # agora conta no teto

    def test_confirm_cannot_exceed_monthly_cap_across_approvals(self):
        # EVASÃO: pendentes não consomem teto no request; N pendentes (cada <= per_purchase_cap)
        # aprovados um a um furariam o monthly_cap. O confirm agora re-valida o teto.
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}
        self._request(vendor="Railway", amount=300.0)
        id1 = policy.load_ledger()[-1]["id"]
        self._request(vendor="Anthropic", amount=300.0)
        id2 = policy.load_ledger()[-1]["id"]
        # primeiro aprova (300 <= 500) -> CONFIRMAR
        out1, code1 = self._confirm(id1, token=SENTINEL, env=env)
        self.assertEqual(code1, 0)
        self.assertIn("CONFIRMAR", out1)
        # segundo estouraria (300+300=600 > 500) -> RECUSADA_ESTOURA_TETO, sem efeito
        out2, code2 = self._confirm(id2, token=SENTINEL, env=env)
        self.assertNotEqual(code2, 0)
        self.assertIn("RECUSADA_ESTOURA_TETO", out2)
        by_id = {e["id"]: e for e in policy.load_ledger()}
        self.assertEqual(by_id[id2]["status"], "pendente")   # não mudou
        self.assertEqual(policy.month_to_date_spent(), 300.0)  # teto não foi furado

    def test_confirm_dry_run_flag_does_not_change_status(self):
        self._request()
        pid = self._first_id()
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}
        out, code = self._confirm(pid, token=SENTINEL, dry_run=True, env=env)
        self.assertEqual(code, 0)
        self.assertIn('"dry_run": true', out)
        self.assertEqual(policy.load_ledger()[0]["status"], "pendente")

    def test_confirm_without_global_execute_is_safe_dry_run(self):
        # token certo + env humana, mas sem HERMES_ALLOW_EXECUTE -> dry-run, sem efeito
        self._request()
        pid = self._first_id()
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true"}
        out, code = self._confirm(pid, token=SENTINEL, env=env)
        self.assertEqual(code, 0)
        self.assertIn("DRY_RUN", out)
        self.assertEqual(policy.load_ledger()[0]["status"], "pendente")

    def test_confirm_unknown_id_is_error(self):
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}
        out, code = self._confirm("nao-existe", token=SENTINEL, env=env)
        self.assertNotEqual(code, 0)
        self.assertIn("não encontrado", out)

    # ---- audit ------------------------------------------------------------
    def test_denied_attempt_is_audited_without_raw_token(self):
        self._request()
        pid = self._first_id()
        env = {"HERMES_PURCHASE_ALLOW_CONFIRM": "true", "HERMES_ALLOW_EXECUTE": "true"}
        self._confirm(pid, token="chute-errado", env=env)
        audit_text = rp.AUDIT_PATH.read_text(encoding="utf-8")
        # a tentativa foi registrada...
        self.assertIn("RECUSADA_TOKEN_INVALIDO", audit_text)
        # ...mas o token cru (o certo E o chutado) nunca aparece na trilha
        self.assertNotIn(SENTINEL, audit_text)
        self.assertNotIn("chute-errado", audit_text)
        # e cada linha é JSON válido (append-only)
        for line in audit_text.splitlines():
            if line.strip():
                json.loads(line)


if __name__ == "__main__":
    unittest.main()
