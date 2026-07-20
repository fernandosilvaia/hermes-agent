"""
test_operation_config.py - PURE tests of the operation/auth config parsing
(connection_store.validate_operation_def / validate_auth) and the
url/body/auth-header templating in _crm_policy.py. No store, no network.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import connection_store as store  # noqa: E402
import _crm_policy as policy  # noqa: E402


class ValidOperationShapes(unittest.TestCase):
    def test_minimal_get(self):
        errors = store.validate_operation_def({"method": "GET", "path": "/leads"})
        self.assertEqual(errors, [])

    def test_get_with_placeholder(self):
        errors = store.validate_operation_def({"method": "GET", "path": "/leads/{id}"})
        self.assertEqual(errors, [])

    def test_patch_with_body_template(self):
        errors = store.validate_operation_def(
            {"method": "PATCH", "path": "/leads/{id}", "body_template": {"stage": "{stage}"}}
        )
        self.assertEqual(errors, [])

    def test_null_body_template_is_valid(self):
        errors = store.validate_operation_def({"method": "POST", "path": "/leads", "body_template": None})
        self.assertEqual(errors, [])

    def test_lowercase_method_is_valid_here_but_normalized_on_write(self):
        # validate_operation_def is case-insensitive; connection_store.set_operation
        # normalizes to uppercase before storing (tested in test_connection_store.py).
        errors = store.validate_operation_def({"method": "get", "path": "/leads"})
        self.assertEqual(errors, [])


class InvalidOperationShapes(unittest.TestCase):
    def test_not_a_dict(self):
        self.assertTrue(store.validate_operation_def("nope"))

    def test_missing_method(self):
        errors = store.validate_operation_def({"path": "/leads"})
        self.assertTrue(any("method" in e for e in errors))

    def test_unknown_method(self):
        errors = store.validate_operation_def({"method": "TRACE", "path": "/leads"})
        self.assertTrue(any("method" in e for e in errors))

    def test_missing_path(self):
        errors = store.validate_operation_def({"method": "GET"})
        self.assertTrue(any("path" in e for e in errors))

    def test_path_without_leading_slash(self):
        errors = store.validate_operation_def({"method": "GET", "path": "leads"})
        self.assertTrue(any("path" in e for e in errors))

    def test_body_template_not_an_object(self):
        errors = store.validate_operation_def(
            {"method": "PATCH", "path": "/leads/{id}", "body_template": "not-an-object"}
        )
        self.assertTrue(any("body_template" in e for e in errors))


class ValidAuthShapes(unittest.TestCase):
    def test_header_style(self):
        self.assertEqual(store.validate_auth({"style": "header", "header_name": "apikey"}), [])

    def test_bearer_style(self):
        self.assertEqual(store.validate_auth({"style": "bearer"}), [])

    def test_header_style_with_prefix(self):
        self.assertEqual(
            store.validate_auth({"style": "header", "header_name": "X-Api-Key", "prefix": "Token "}), []
        )


class InvalidAuthShapes(unittest.TestCase):
    def test_unknown_style(self):
        errors = store.validate_auth({"style": "basic"})
        self.assertTrue(any("style" in e for e in errors))

    def test_header_style_without_header_name(self):
        errors = store.validate_auth({"style": "header"})
        self.assertTrue(any("header_name" in e for e in errors))

    def test_not_a_dict(self):
        self.assertTrue(store.validate_auth("nope"))

    def test_prefix_wrong_type(self):
        errors = store.validate_auth({"style": "bearer", "prefix": 123})
        self.assertTrue(any("prefix" in e for e in errors))


class UrlTemplating(unittest.TestCase):
    def test_no_placeholders(self):
        url = policy.build_url("https://api.example.com", "/leads", {})
        self.assertEqual(url, "https://api.example.com/leads")

    def test_single_placeholder(self):
        url = policy.build_url("https://api.example.com", "/leads/{id}", {"id": "123"})
        self.assertEqual(url, "https://api.example.com/leads/123")

    def test_missing_placeholder_raises(self):
        with self.assertRaises(policy.TemplateError):
            policy.build_url("https://api.example.com", "/leads/{id}", {})

    def test_placeholder_value_is_url_encoded(self):
        # A malicious/careless id like "../admin" must not change the path shape.
        url = policy.build_url("https://api.example.com", "/leads/{id}", {"id": "../admin"})
        self.assertEqual(url, "https://api.example.com/leads/..%2Fadmin")

    def test_query_injection_via_param_is_encoded(self):
        url = policy.build_url("https://api.example.com", "/leads/{id}", {"id": "1?evil=true"})
        self.assertNotIn("?evil=true", url)

    def test_base_url_trailing_slash_is_normalized(self):
        url = policy.build_url("https://api.example.com/", "/leads", {})
        self.assertEqual(url, "https://api.example.com/leads")


class BodyTemplating(unittest.TestCase):
    def test_none_template_yields_none_body(self):
        self.assertIsNone(policy.build_body(None, {"stage": "won"}))

    def test_exact_placeholder_preserves_type(self):
        body = policy.build_body({"stage": "{stage}", "priority": "{priority}"},
                                  {"stage": "won", "priority": 5})
        self.assertEqual(body, {"stage": "won", "priority": 5})

    def test_partial_string_interpolation(self):
        body = policy.build_body({"note": "moved to {stage}"}, {"stage": "won"})
        self.assertEqual(body, {"note": "moved to won"})

    def test_nested_dict_substitution(self):
        body = policy.build_body({"lead": {"stage": "{stage}"}}, {"stage": "won"})
        self.assertEqual(body, {"lead": {"stage": "won"}})

    def test_missing_body_param_raises(self):
        with self.assertRaises(policy.TemplateError):
            policy.build_body({"stage": "{stage}"}, {})

    def test_static_values_pass_through_untouched(self):
        body = policy.build_body({"source": "hermes", "stage": "{stage}"}, {"stage": "won"})
        self.assertEqual(body, {"source": "hermes", "stage": "won"})


class AuthHeaderBuilding(unittest.TestCase):
    def test_header_style_default_prefix(self):
        headers = policy.build_auth_headers({"style": "header", "header_name": "apikey"}, "sk_live_x")
        self.assertEqual(headers, {"apikey": "sk_live_x"})

    def test_bearer_style_default_prefix(self):
        headers = policy.build_auth_headers({"style": "bearer"}, "sk_live_x")
        self.assertEqual(headers, {"Authorization": "Bearer sk_live_x"})

    def test_header_style_custom_prefix(self):
        headers = policy.build_auth_headers(
            {"style": "header", "header_name": "X-Api-Key", "prefix": "Token "}, "sk_live_x"
        )
        self.assertEqual(headers, {"X-Api-Key": "Token sk_live_x"})

    def test_unknown_style_raises(self):
        with self.assertRaises(policy.AuthError):
            policy.build_auth_headers({"style": "basic"}, "x")

    def test_header_style_without_header_name_raises(self):
        with self.assertRaises(policy.AuthError):
            policy.build_auth_headers({"style": "header"}, "x")


if __name__ == "__main__":
    unittest.main()
