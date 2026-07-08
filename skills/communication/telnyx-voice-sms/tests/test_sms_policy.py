"""
Testes PUROS da política do lado de RECEBIMENTO (_sms_policy.py).

Sem rede, sem importar requests/fastapi/nacl. Provam o P0 do /sms/last fechado:
  - mask_otp remove o OTP do output (campo E texto);
  - require_token rejeita token errado/ausente e aceita o certo;
  - reveal_allowed só libera o OTP em claro com o gate humano aberto.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import _sms_policy as sp  # noqa: E402


class MaskOtpTestCase(unittest.TestCase):
    def _record(self):
        return {
            "received_at": "2026-07-07T12:00:00+00:00",
            "telnyx_id": "abc-123",
            "from": "+15551230000",
            "to": "+16174505166",
            "text": "Seu codigo Hermes e 458213 valido por 10 min",
            "verification_code": "458213",
        }

    def test_mask_otp_removes_code_from_field_and_text(self):
        rec = self._record()
        masked = sp.mask_otp(rec)
        blob = json.dumps(masked, ensure_ascii=False)
        # O OTP cru NÃO pode aparecer em lugar nenhum da saída.
        self.assertNotIn("458213", blob)
        # O campo foi mascarado, preservando só os 2 últimos dígitos.
        self.assertEqual(masked["verification_code"], "****13")
        self.assertNotIn("458213", masked["text"])
        self.assertIn("****13", masked["text"])

    def test_mask_otp_does_not_mutate_original(self):
        rec = self._record()
        sp.mask_otp(rec)
        # O record original (arquivo local) pode manter o código cru.
        self.assertEqual(rec["verification_code"], "458213")

    def test_mask_otp_preserves_non_secret_fields(self):
        masked = sp.mask_otp(self._record())
        self.assertEqual(masked["from"], "+15551230000")
        self.assertEqual(masked["received_at"], "2026-07-07T12:00:00+00:00")

    def test_mask_otp_short_code_fully_redacted(self):
        masked = sp.mask_otp({"verification_code": "12", "text": "x"})
        self.assertEqual(masked["verification_code"], "[REDIGIDO]")

    def test_mask_otp_leaves_phone_numbers_alone(self):
        # Números E.164 (11+ dígitos contíguos) não são tratados como OTP.
        rec = {"text": "ligue para +16174505166", "verification_code": None}
        masked = sp.mask_otp(rec)
        self.assertIn("+16174505166", masked["text"])

    def test_mask_otp_non_dict_passthrough(self):
        self.assertEqual(sp.mask_otp(None), None)
        self.assertEqual(sp.mask_otp("nao-e-dict"), "nao-e-dict")


class RequireTokenTestCase(unittest.TestCase):
    def test_correct_token_accepted(self):
        self.assertTrue(sp.require_token("s3cr3t-token", "s3cr3t-token"))

    def test_wrong_token_rejected(self):
        # ATAQUE: cliente sem o segredo tenta ler /sms/last -> negado.
        self.assertFalse(sp.require_token("chute-errado", "s3cr3t-token"))

    def test_empty_or_missing_token_rejected(self):
        self.assertFalse(sp.require_token("", "s3cr3t-token"))
        self.assertFalse(sp.require_token(None, "s3cr3t-token"))
        self.assertFalse(sp.require_token("qualquer", ""))
        self.assertFalse(sp.require_token(None, None))


class ExtractBearerTestCase(unittest.TestCase):
    def test_valid_bearer(self):
        self.assertEqual(sp.extract_bearer("Bearer abc123"), "abc123")
        self.assertEqual(sp.extract_bearer("bearer abc123"), "abc123")

    def test_malformed_header_returns_empty(self):
        self.assertEqual(sp.extract_bearer(None), "")
        self.assertEqual(sp.extract_bearer(""), "")
        self.assertEqual(sp.extract_bearer("Basic abc123"), "")
        self.assertEqual(sp.extract_bearer("abc123"), "")


class SmsLastEndpointLogicTestCase(unittest.TestCase):
    """Prova o P0 do /sms/last isolando a lógica de auth+máscara do endpoint,
    SEM subir o FastAPI (que importa nacl/requests)."""

    def _simulate_sms_last(self, authorization_header, expected_env_token, stored_record):
        # Reproduz a decisão do endpoint em termos puros.
        expected = (expected_env_token or "").strip()
        if not expected:
            return {"status": 503}
        provided = sp.extract_bearer(authorization_header)
        if not sp.require_token(provided, expected):
            return {"status": 401}
        return {"status": 200, "body": sp.mask_otp(stored_record)}

    def test_no_env_token_returns_503_never_open(self):
        out = self._simulate_sms_last("Bearer whatever", "", {"verification_code": "999888"})
        self.assertEqual(out["status"], 503)

    def test_wrong_token_returns_401(self):
        out = self._simulate_sms_last("Bearer errado", "real-token",
                                      {"verification_code": "999888"})
        self.assertEqual(out["status"], 401)

    def test_no_auth_header_returns_401(self):
        out = self._simulate_sms_last(None, "real-token", {"verification_code": "999888"})
        self.assertEqual(out["status"], 401)

    def test_correct_token_returns_masked_otp(self):
        stored = {"verification_code": "999888",
                  "text": "codigo 999888", "from": "+15551230000"}
        out = self._simulate_sms_last("Bearer real-token", "real-token", stored)
        self.assertEqual(out["status"], 200)
        blob = json.dumps(out["body"], ensure_ascii=False)
        # Mesmo autenticado, o OTP cru nunca sai pela HTTP.
        self.assertNotIn("999888", blob)
        self.assertEqual(out["body"]["from"], "+15551230000")


class RevealAllowedTestCase(unittest.TestCase):
    def test_reveal_denied_by_default(self):
        self.assertFalse(sp.reveal_allowed({}))

    def test_reveal_denied_with_only_one_env(self):
        self.assertFalse(sp.reveal_allowed({"HERMES_ALLOW_EXECUTE": "true"}))
        self.assertFalse(sp.reveal_allowed({"TELNYX_VOICE_SMS_ENABLED": "true"}))

    def test_reveal_allowed_only_with_both_envs(self):
        self.assertTrue(sp.reveal_allowed({
            "HERMES_ALLOW_EXECUTE": "true",
            "TELNYX_VOICE_SMS_ENABLED": "true",
        }))

    def test_reveal_env_values_must_be_exactly_true(self):
        self.assertFalse(sp.reveal_allowed({
            "HERMES_ALLOW_EXECUTE": "1",
            "TELNYX_VOICE_SMS_ENABLED": "yes",
        }))


if __name__ == "__main__":
    unittest.main()
