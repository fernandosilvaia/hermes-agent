"""Testes de attom_call.py — HTTP sempre mockado, zero rede real."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import attom_call as ac


def _fake_success_response(kind="detail"):
    resp = mock.Mock()
    resp.ok = True
    resp.json.return_value = {
        "status": {"version": "1.0.0", "code": 0, "msg": "SuccessWithResult", "total": 1},
        "property": [{"address": {"line1": "468 Sequoia Dr"}, "building": {"rooms": {"beds": 3}}}],
    }
    return resp


def _fake_no_result_response():
    resp = mock.Mock()
    resp.ok = True
    resp.json.return_value = {
        "status": {"version": "1.0.0", "code": 400, "msg": "SuccessWithoutResult", "total": 0},
    }
    return resp


class TestMissingKey(unittest.TestCase):
    def test_raises_clear_error_without_api_key(self):
        with mock.patch("attom_call.get_secret", return_value=None):
            with self.assertRaises(ac.AttomError):
                ac.lookup("detail", address1="468 Sequoia Dr", address2="Smyrna, DE 19977")


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("attom_call.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_invalid_kind_rejected(self):
        with self.assertRaises(ac.AttomError):
            ac.lookup("bogus", address1="x", address2="y")

    def test_missing_address2_rejected(self):
        with self.assertRaises(ac.AttomError):
            ac.lookup("detail", address1="468 Sequoia Dr", address2="")


class TestLookup(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("attom_call.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_detail_lookup_strips_status_wrapper(self):
        session = mock.Mock()
        session.get.return_value = _fake_success_response()
        result = ac.lookup("detail", address1="468 Sequoia Dr", address2="Smyrna, DE 19977", session=session)

        self.assertTrue(result["ok"])
        self.assertNotIn("status", result["property"])
        self.assertIn("property", result["property"])

    def test_sends_api_key_header_and_split_address_params(self):
        session = mock.Mock()
        session.get.return_value = _fake_success_response()
        ac.lookup("detail", address1="468 Sequoia Dr", address2="Smyrna, DE 19977", session=session)

        args, kwargs = session.get.call_args
        self.assertEqual(args[0], "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/detail")
        self.assertEqual(kwargs["headers"]["APIKey"], "fake-key")
        self.assertEqual(kwargs["params"]["address1"], "468 Sequoia Dr")
        self.assertEqual(kwargs["params"]["address2"], "Smyrna, DE 19977")

    def test_avm_kind_uses_avm_endpoint(self):
        session = mock.Mock()
        session.get.return_value = _fake_success_response()
        ac.lookup("avm", address1="x", address2="y", session=session)

        args, _ = session.get.call_args
        self.assertEqual(args[0], "https://api.gateway.attomdata.com/propertyapi/v1.0.0/avm/snapshot")

    def test_snapshot_kind_uses_snapshot_endpoint(self):
        session = mock.Mock()
        session.get.return_value = _fake_success_response()
        ac.lookup("snapshot", address1="x", address2="y", session=session)

        args, _ = session.get.call_args
        self.assertEqual(args[0], "https://api.gateway.attomdata.com/propertyapi/v1.0.0/property/snapshot")


class TestErrorHandling(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("attom_call.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_success_without_result_never_reported_as_ok(self):
        """status.code=400/'SuccessWithoutResult' é HTTP 200 mas SEM dado — não pode
        virar ok:true silenciosamente."""
        session = mock.Mock()
        session.get.return_value = _fake_no_result_response()
        result = ac.lookup("detail", address1="endereço inexistente", address2="Nowhere, XX 00000", session=session)

        self.assertFalse(result["ok"])
        self.assertNotIn("property", result)
        self.assertEqual(result["attom_status"]["code"], 400)

    def test_http_error_never_invents_property_data(self):
        session = mock.Mock()
        resp = mock.Mock()
        resp.ok = False
        resp.status_code = 401
        resp.json.return_value = {"status": {"msg": "Unauthorized"}}
        session.get.return_value = resp

        result = ac.lookup("detail", address1="x", address2="y", session=session)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status_code"], 401)


if __name__ == "__main__":
    unittest.main()
