"""Testes de rentcast_call.py — HTTP sempre mockado, zero rede real."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import rentcast_call as rc


def _fake_rent_response():
    resp = mock.Mock()
    resp.ok = True
    resp.json.return_value = {
        "rent": 1620, "rentRangeLow": 1550, "rentRangeHigh": 1690,
        "subjectProperty": {"formattedAddress": "123 Main St, Boston, MA", "bedrooms": 3, "bathrooms": 2, "squareFootage": 1878},
        "comparables": [{"formattedAddress": "x"}, {"formattedAddress": "y"}],
    }
    return resp


def _fake_value_response():
    resp = mock.Mock()
    resp.ok = True
    resp.json.return_value = {
        "price": 250000, "priceRangeLow": 195000, "priceRangeHigh": 304000,
        "subjectProperty": {"formattedAddress": "123 Main St, Boston, MA", "bedrooms": 3, "bathrooms": 2, "squareFootage": 1878},
        "comparables": [{"formattedAddress": "x"}],
    }
    return resp


class TestMissingKey(unittest.TestCase):
    def test_raises_clear_error_without_api_key(self):
        with mock.patch("rentcast_call.get_secret", return_value=None):
            with self.assertRaises(rc.RentcastError):
                rc.estimate("rent", address="123 Main St")


class TestValidation(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("rentcast_call.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_invalid_kind_rejected(self):
        with self.assertRaises(rc.RentcastError):
            rc.estimate("bogus", address="123 Main St")

    def test_no_address_or_latlng_rejected(self):
        with self.assertRaises(rc.RentcastError):
            rc.estimate("rent")


class TestRentEstimate(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("rentcast_call.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_rent_estimate_by_address(self):
        session = mock.Mock()
        session.get.return_value = _fake_rent_response()
        result = rc.estimate("rent", address="123 Main St, Boston, MA 02101", session=session)

        self.assertTrue(result["ok"])
        self.assertEqual(result["rent"], 1620)
        self.assertEqual(result["rent_range_low"], 1550)
        self.assertEqual(result["rent_range_high"], 1690)
        self.assertEqual(result["comparables_count"], 2)

    def test_sends_api_key_in_header_not_query(self):
        session = mock.Mock()
        session.get.return_value = _fake_rent_response()
        rc.estimate("rent", address="123 Main St", session=session)

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["headers"]["X-Api-Key"], "fake-key")
        self.assertNotIn("apiKey", kwargs["params"])
        self.assertNotIn("key", kwargs["params"])

    def test_rent_estimate_by_latlng(self):
        session = mock.Mock()
        session.get.return_value = _fake_rent_response()
        rc.estimate("rent", lat=42.36, lng=-71.06, session=session)

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["latitude"], 42.36)
        self.assertEqual(kwargs["params"]["longitude"], -71.06)

    def test_optional_refinement_params_forwarded(self):
        session = mock.Mock()
        session.get.return_value = _fake_rent_response()
        rc.estimate("rent", address="x", bedrooms=3, bathrooms=2, square_footage=1800, session=session)

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["bedrooms"], 3)
        self.assertEqual(kwargs["params"]["bathrooms"], 2)
        self.assertEqual(kwargs["params"]["squareFootage"], 1800)


class TestValueEstimate(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("rentcast_call.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_value_estimate_uses_value_endpoint(self):
        session = mock.Mock()
        session.get.return_value = _fake_value_response()
        result = rc.estimate("value", address="123 Main St", session=session)

        args, _ = session.get.call_args
        self.assertEqual(args[0], "https://api.rentcast.io/v1/avm/value")
        self.assertTrue(result["ok"])
        self.assertEqual(result["price"], 250000)
        self.assertEqual(result["price_range_low"], 195000)


class TestApiErrorHandling(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("rentcast_call.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_non_ok_response_never_invents_estimate(self):
        session = mock.Mock()
        resp = mock.Mock()
        resp.ok = False
        resp.status_code = 404
        resp.json.return_value = {"error": "No property found"}
        session.get.return_value = resp

        result = rc.estimate("rent", address="endereço inexistente", session=session)

        self.assertFalse(result["ok"])
        self.assertNotIn("rent", result)
        self.assertEqual(result["status_code"], 404)


if __name__ == "__main__":
    unittest.main()
