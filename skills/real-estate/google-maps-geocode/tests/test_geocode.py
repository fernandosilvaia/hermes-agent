"""Testes de geocode.py — HTTP sempre mockado, zero rede real."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import geocode as gc


def _fake_response(status="OK", **overrides):
    body = {
        "status": status,
        "results": [{
            "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
            "geometry": {"location": {"lat": 37.4224764, "lng": -122.0842499}},
            "place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA",
            "address_components": [
                {"long_name": "Mountain View", "short_name": "Mountain View", "types": ["locality"]},
                {"long_name": "California", "short_name": "CA", "types": ["administrative_area_level_1"]},
                {"long_name": "94043", "short_name": "94043", "types": ["postal_code"]},
                {"long_name": "United States", "short_name": "US", "types": ["country"]},
            ],
        }],
    }
    body.update(overrides)
    resp = mock.Mock()
    resp.json.return_value = body
    resp.raise_for_status.return_value = None
    return resp


class TestGeocodeMissingKey(unittest.TestCase):
    def test_raises_clear_error_without_api_key(self):
        with mock.patch("geocode.get_secret", return_value=None):
            with self.assertRaises(gc.GeocodeError):
                gc.geocode("some address")


class TestGeocodeDirect(unittest.TestCase):
    def setUp(self):
        self.patcher = mock.patch("geocode.get_secret", return_value="fake-key")
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_geocode_parses_address_and_components(self):
        session = mock.Mock()
        session.get.return_value = _fake_response()
        result = gc.geocode("1600 Amphitheatre Parkway, Mountain View, CA", session=session)

        self.assertTrue(result["ok"])
        self.assertEqual(result["lat"], 37.4224764)
        self.assertEqual(result["lng"], -122.0842499)
        self.assertEqual(result["components"]["city"], "Mountain View")
        self.assertEqual(result["components"]["state"], "CA")
        self.assertEqual(result["components"]["postal_code"], "94043")

    def test_geocode_sends_api_key_and_address_as_params(self):
        session = mock.Mock()
        session.get.return_value = _fake_response()
        gc.geocode("some address", session=session)

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["key"], "fake-key")
        self.assertEqual(kwargs["params"]["address"], "some address")

    def test_zero_results_never_invents_coordinate(self):
        session = mock.Mock()
        session.get.return_value = _fake_response(status="ZERO_RESULTS", results=[])
        result = gc.geocode("endereço que não existe", session=session)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "ZERO_RESULTS")
        self.assertNotIn("lat", result)

    def test_reverse_geocode_sends_latlng_param(self):
        session = mock.Mock()
        session.get.return_value = _fake_response()
        gc.reverse_geocode(37.4224764, -122.0842499, session=session)

        _, kwargs = session.get.call_args
        self.assertEqual(kwargs["params"]["latlng"], "37.4224764,-122.0842499")


if __name__ == "__main__":
    unittest.main()
