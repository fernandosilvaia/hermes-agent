"""
Testes de consolidate_state.py. Usa fixtures sintéticas (não os 58 fichas reais),
pra ficar rápido e isolado de mudanças no roster de verdade.

    python -m unittest discover -s tests
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import consolidate_state as cs  # noqa: E402

FICHA_OK = """# Fulano — Cargo Teste
**ID:** teste-agente
**Squad:** growth
**Modelo:** claude-sonnet-4-6

## ALMA
Ver ficha no Office.
"""

FICHA_MALFORMED = "# Sem cabeçalho padrão\nConteúdo qualquer sem os campos esperados.\n"

ROUTING_MD = """## Mapa de roteamento (pedido → agente)

| Tipo de pedido | Agente principal |
|---|---|
| Pedido de teste | teste-agente |
| Pedido combinado | teste-agente + agente-fantasma |

## Próxima seção
Não deve ser incluída.
"""


class ParseFichasTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.fichas_dir = Path(self.tmpdir.name)
        (self.fichas_dir / "teste-agente.md").write_text(FICHA_OK, encoding="utf-8")
        (self.fichas_dir / "malformada.md").write_text(FICHA_MALFORMED, encoding="utf-8")

    def test_well_formed_ficha_is_parsed(self):
        fichas = cs.parse_fichas(self.fichas_dir)
        ok = next(f for f in fichas if f["file"] == "teste-agente.md")
        self.assertEqual(ok["id"], "teste-agente")
        self.assertEqual(ok["squad"], "growth")
        self.assertEqual(ok["model"], "claude-sonnet-4-6")
        self.assertNotIn("malformed", ok)

    def test_malformed_ficha_is_flagged_not_dropped(self):
        fichas = cs.parse_fichas(self.fichas_dir)
        bad = next(f for f in fichas if f["file"] == "malformada.md")
        self.assertTrue(bad.get("malformed"))


class ParseRoutingMapTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.routing_path = Path(self.tmpdir.name) / "hermes-orquestrador.md"
        self.routing_path.write_text(ROUTING_MD, encoding="utf-8")

    def test_single_agent_row_is_parsed(self):
        rows = cs.parse_routing_map(self.routing_path)
        row = next(r for r in rows if r["pedido"] == "Pedido de teste")
        self.assertEqual(row["agentes"], ["teste-agente"])

    def test_combined_agent_row_splits_on_plus(self):
        rows = cs.parse_routing_map(self.routing_path)
        row = next(r for r in rows if r["pedido"] == "Pedido combinado")
        self.assertEqual(row["agentes"], ["teste-agente", "agente-fantasma"])

    def test_missing_routing_file_returns_empty_list(self):
        self.assertEqual(cs.parse_routing_map(Path("/nao/existe.md")), [])


class BuildReportTestCase(unittest.TestCase):
    def test_broken_reference_is_detected(self):
        fichas = [{"file": "teste-agente.md", "id": "teste-agente", "name": "X", "squad": "y", "model": "z"}]
        routing = [{"pedido": "Pedido combinado", "agentes": ["teste-agente", "agente-fantasma"]}]
        report = cs.build_report(fichas, routing)
        self.assertEqual(len(report["referencias_quebradas"]), 1)
        self.assertEqual(report["referencias_quebradas"][0]["agente"], "agente-fantasma")

    def test_ficha_without_routing_entry_is_orphan(self):
        fichas = [
            {"file": "a.md", "id": "roteado", "name": "A", "squad": "s", "model": "m"},
            {"file": "b.md", "id": "orfao", "name": "B", "squad": "s", "model": "m"},
        ]
        routing = [{"pedido": "X", "agentes": ["roteado"]}]
        report = cs.build_report(fichas, routing)
        self.assertEqual(report["fichas_orfas"], ["orfao"])

    def test_fully_consistent_roster_has_no_findings(self):
        fichas = [{"file": "a.md", "id": "x", "name": "A", "squad": "s", "model": "m"}]
        routing = [{"pedido": "P", "agentes": ["x"]}]
        report = cs.build_report(fichas, routing)
        self.assertEqual(report["referencias_quebradas"], [])
        self.assertEqual(report["fichas_orfas"], [])


if __name__ == "__main__":
    unittest.main()
