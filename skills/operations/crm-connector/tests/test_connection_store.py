"""
test_connection_store.py - proves connection registration/retrieval works,
multiple named connections do not collide, corrupt/missing store files
degrade predictably, api_key masking never leaks the real value, and the
store file is written with 0600 permissions.

No network. No rede.

Rodar:
    python3 -m unittest discover -s tests -v
"""
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import connection_store as store  # noqa: E402


class TempStoreTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store_path = Path(self._tmp.name) / "connections.json"

    def tearDown(self):
        self._tmp.cleanup()


class MultipleConnectionsDoNotCollide(TempStoreTestCase):
    def test_two_named_connections_stay_independent(self):
        store.upsert_connection(
            "ecoloop", base_url="https://api.ecoloopcrm.com",
            auth={"style": "header", "header_name": "apikey"},
            api_key="ecoloop-secret", path=self.store_path,
        )
        store.upsert_connection(
            "billion_crm", base_url="https://api.billioncrm.com",
            auth={"style": "bearer"},
            api_key="billion-secret", path=self.store_path,
        )

        names = store.list_connections(path=self.store_path)
        self.assertEqual(names, ["billion_crm", "ecoloop"])

        eco = store.get_connection("ecoloop", path=self.store_path)
        bil = store.get_connection("billion_crm", path=self.store_path)
        self.assertEqual(eco["api_key"], "ecoloop-secret")
        self.assertEqual(bil["api_key"], "billion-secret")
        self.assertEqual(eco["base_url"], "https://api.ecoloopcrm.com")
        self.assertEqual(bil["base_url"], "https://api.billioncrm.com")

    def test_updating_one_connection_does_not_touch_another(self):
        store.upsert_connection(
            "a", base_url="https://a.example.com",
            auth={"style": "bearer"}, api_key="key-a", path=self.store_path,
        )
        store.upsert_connection(
            "b", base_url="https://b.example.com",
            auth={"style": "bearer"}, api_key="key-b", path=self.store_path,
        )
        # Re-register 'a' with a new key.
        store.upsert_connection(
            "a", base_url="https://a.example.com",
            auth={"style": "bearer"}, api_key="key-a-rotated", path=self.store_path,
        )
        self.assertEqual(store.get_connection("a", path=self.store_path)["api_key"], "key-a-rotated")
        self.assertEqual(store.get_connection("b", path=self.store_path)["api_key"], "key-b")

    def test_removing_one_connection_leaves_others_intact(self):
        store.upsert_connection("a", base_url="https://a.example.com",
                                 auth={"style": "bearer"}, api_key="k", path=self.store_path)
        store.upsert_connection("b", base_url="https://b.example.com",
                                 auth={"style": "bearer"}, api_key="k", path=self.store_path)
        removed = store.remove_connection("a", path=self.store_path)
        self.assertTrue(removed)
        self.assertIsNone(store.get_connection("a", path=self.store_path))
        self.assertIsNotNone(store.get_connection("b", path=self.store_path))

    def test_removing_unknown_connection_returns_false(self):
        self.assertFalse(store.remove_connection("does-not-exist", path=self.store_path))


class OperationMappingDoesNotCollideAcrossConnections(TempStoreTestCase):
    def test_operations_are_scoped_per_connection(self):
        store.upsert_connection("ecoloop", base_url="https://api.ecoloopcrm.com",
                                 auth={"style": "header", "header_name": "apikey"},
                                 api_key="k1", path=self.store_path)
        store.upsert_connection("billion", base_url="https://api.billioncrm.com",
                                 auth={"style": "bearer"}, api_key="k2", path=self.store_path)

        store.set_operation("ecoloop", "list_leads", {"method": "GET", "path": "/leads"}, path=self.store_path)
        store.set_operation("billion", "list_deals", {"method": "GET", "path": "/deals"}, path=self.store_path)

        eco = store.get_connection("ecoloop", path=self.store_path)
        bil = store.get_connection("billion", path=self.store_path)
        self.assertIn("list_leads", eco["operations"])
        self.assertNotIn("list_leads", bil["operations"])
        self.assertIn("list_deals", bil["operations"])
        self.assertNotIn("list_deals", eco["operations"])

    def test_upsert_connection_preserves_existing_operations(self):
        store.upsert_connection("ecoloop", base_url="https://api.ecoloopcrm.com",
                                 auth={"style": "header", "header_name": "apikey"},
                                 api_key="k1", path=self.store_path)
        store.set_operation("ecoloop", "list_leads", {"method": "GET", "path": "/leads"}, path=self.store_path)
        # Re-register (e.g. rotating the key) must not wipe the operations map.
        store.upsert_connection("ecoloop", base_url="https://api.ecoloopcrm.com",
                                 auth={"style": "header", "header_name": "apikey"},
                                 api_key="k1-rotated", path=self.store_path)
        conn = store.get_connection("ecoloop", path=self.store_path)
        self.assertEqual(conn["api_key"], "k1-rotated")
        self.assertIn("list_leads", conn["operations"])

    def test_set_operation_on_unknown_connection_raises(self):
        with self.assertRaises(store.ConnectionStoreError):
            store.set_operation("nope", "list_leads", {"method": "GET", "path": "/leads"}, path=self.store_path)

    def test_remove_operation(self):
        store.upsert_connection("ecoloop", base_url="https://api.ecoloopcrm.com",
                                 auth={"style": "header", "header_name": "apikey"},
                                 api_key="k1", path=self.store_path)
        store.set_operation("ecoloop", "list_leads", {"method": "GET", "path": "/leads"}, path=self.store_path)
        self.assertTrue(store.remove_operation("ecoloop", "list_leads", path=self.store_path))
        self.assertFalse(store.remove_operation("ecoloop", "list_leads", path=self.store_path))
        self.assertNotIn("list_leads", store.get_connection("ecoloop", path=self.store_path)["operations"])


class ApiKeyMasking(TempStoreTestCase):
    def test_masked_view_hides_all_but_last_four_chars(self):
        store.upsert_connection("ecoloop", base_url="https://api.ecoloopcrm.com",
                                 auth={"style": "bearer"}, api_key="sk_live_abcd1234",
                                 path=self.store_path)
        conn = store.get_connection("ecoloop", path=self.store_path)
        masked = store.masked_view(conn)
        self.assertTrue(masked["api_key"].endswith("1234"))
        self.assertNotIn("sk_live_abcd1234", masked["api_key"])
        self.assertNotIn("sk_live", masked["api_key"])

    def test_masked_view_does_not_mutate_the_original(self):
        store.upsert_connection("ecoloop", base_url="https://api.ecoloopcrm.com",
                                 auth={"style": "bearer"}, api_key="real-secret",
                                 path=self.store_path)
        conn = store.get_connection("ecoloop", path=self.store_path)
        store.masked_view(conn)
        self.assertEqual(store.get_connection("ecoloop", path=self.store_path)["api_key"], "real-secret")


class StoreFilePermissions(TempStoreTestCase):
    def test_store_file_is_written_owner_read_write_only(self):
        store.upsert_connection("ecoloop", base_url="https://api.ecoloopcrm.com",
                                 auth={"style": "bearer"}, api_key="k", path=self.store_path)
        mode = stat.S_IMODE(os.stat(self.store_path).st_mode)
        self.assertEqual(mode, 0o600)


class CorruptOrMissingStore(TempStoreTestCase):
    def test_missing_store_file_returns_empty_connections(self):
        self.assertEqual(store.list_connections(path=self.store_path), [])
        self.assertIsNone(store.get_connection("anything", path=self.store_path))

    def test_corrupt_json_raises_clear_error(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text("{not valid json", encoding="utf-8")
        with self.assertRaises(store.ConnectionStoreError):
            store.load_store(path=self.store_path)

    def test_wrong_shape_raises_clear_error(self):
        self.store_path.parent.mkdir(parents=True, exist_ok=True)
        self.store_path.write_text(json.dumps({"not": "the right shape"}), encoding="utf-8")
        with self.assertRaises(store.ConnectionStoreError):
            store.load_store(path=self.store_path)


class ConnectionValidation(TempStoreTestCase):
    def test_invalid_name_rejected(self):
        with self.assertRaises(store.ConnectionStoreError):
            store.upsert_connection("bad name!", base_url="https://x.com",
                                     auth={"style": "bearer"}, api_key="k", path=self.store_path)

    def test_bad_base_url_rejected(self):
        with self.assertRaises(store.ConnectionStoreError):
            store.upsert_connection("ok", base_url="not-a-url",
                                     auth={"style": "bearer"}, api_key="k", path=self.store_path)

    def test_empty_api_key_rejected(self):
        with self.assertRaises(store.ConnectionStoreError):
            store.upsert_connection("ok", base_url="https://x.com",
                                     auth={"style": "bearer"}, api_key="", path=self.store_path)


if __name__ == "__main__":
    unittest.main()
