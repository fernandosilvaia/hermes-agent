"""
Testes do rastreio de prazos (deadlines.py). Puro, sem arquivos reais do disco.

    python -m unittest discover -s tests
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import deadlines as dl  # noqa: E402


class ResolvedHintsTestCase(unittest.TestCase):
    def test_resolved_deadline_line_is_recognized_as_resolved(self):
        # Caso real: "✅ ~~RESOLVIDO 2026-07-05~~: Deploy..." não é prazo em aberto.
        line = "6. ✅ ~~Railway control-tower: criar projeto dedicado~~ — RESOLVIDO 2026-07-03"
        low = line.lower()
        self.assertTrue(any(h in low for h in dl.RESOLVED_HINTS))

    def test_open_deadline_line_has_no_resolved_hint(self):
        line = "Entrega do relatório: prazo 2026-08-01"
        low = line.lower()
        self.assertFalse(any(h in low for h in dl.RESOLVED_HINTS))


class ScanFileTestCase(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.path = Path(self.tmpdir.name) / "STATUS.md"

    def _write(self, text):
        self.path.write_text(text, encoding="utf-8")

    def test_resolved_line_with_past_date_is_not_reported(self):
        self._write("✅ RESOLVIDO 2026-07-05: Deploy do control-tower concluído.\n")
        hits = dl.scan_file(self.path, window_days=14)
        self.assertEqual(hits, [])

    def test_open_deadline_within_window_is_reported(self):
        future = dl.TODAY + __import__("datetime").timedelta(days=5)
        self._write("Prazo do contrato: {}\n".format(future.isoformat()))
        hits = dl.scan_file(self.path, window_days=14)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["status"], "proximo")

    def test_deadline_far_in_the_past_beyond_floor_is_not_reported(self):
        old = dl.TODAY - __import__("datetime").timedelta(days=90)
        self._write("Prazo vencido: {}\n".format(old.isoformat()))
        hits = dl.scan_file(self.path, window_days=14)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
