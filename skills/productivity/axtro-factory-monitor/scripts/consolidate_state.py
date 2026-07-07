#!/usr/bin/env python3
"""consolidate_state.py — "Estado vivo" da fábrica: CLAUDE.md + roster de agentes (Anel 0).

Consolida num único arquivo (`03_AGENTES/ESTADO_VIVO.md`):
  1. O CLAUDE.md raiz, verbatim (fonte de verdade da empresa — nunca resumido/reescrito,
     só copiado, pra não arriscar drift/alucinação sobre regras da empresa).
  2. Um roster das fichas de agente (`03_AGENTES/fichas/*.md`): nome, ID, squad, modelo.
  3. Um relatório de consistência entre o roster e o mapa de roteamento do
     `hermes-orquestrador.md` — IDs referenciados no roteamento sem ficha correspondente
     (referência quebrada) e fichas sem nenhuma entrada de roteamento (órfãs).

100% leitura das fontes + 1 escrita local (o próprio ESTADO_VIVO.md, versionado). Não
requer nenhuma credencial nem toca em nada fora de 03_AGENTES/ e CLAUDE.md.

Uso:
    python scripts/consolidate_state.py                # gera e grava ESTADO_VIVO.md
    python scripts/consolidate_state.py --dry-run       # só imprime o relatório de drift
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import common

FICHA_HEADER_RE = re.compile(
    r"^#\s*(?P<name>.+?)\s*\n\*\*ID:\*\*\s*(?P<id>\S+)\s*\n"
    r"\*\*Squad:\*\*\s*(?P<squad>\S+)\s*\n\*\*Modelo:\*\*\s*(?P<model>\S+)",
    re.MULTILINE,
)
# célula da tabela de roteamento: "| ... | agente-id |" ou "a + b" (múltiplos agentes)
ROUTING_ROW_RE = re.compile(r"^\|\s*(?P<pedido>[^|]+?)\s*\|\s*(?P<agentes>[^|]+?)\s*\|\s*$")


def parse_fichas(fichas_dir: Path) -> list:
    fichas = []
    for path in sorted(fichas_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        m = FICHA_HEADER_RE.search(text)
        if m:
            fichas.append({
                "file": path.name, "name": m.group("name"), "id": m.group("id"),
                "squad": m.group("squad"), "model": m.group("model"),
            })
        else:
            fichas.append({"file": path.name, "name": None, "id": path.stem,
                            "squad": None, "model": None, "malformed": True})
    return fichas


def parse_routing_map(routing_path: Path) -> list:
    """Extrai (pedido, [ids]) da tabela markdown 'Mapa de roteamento'. Ignora o
    cabeçalho da tabela e a linha separadora."""
    if not routing_path.exists():
        return []
    text = routing_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    rows = []
    in_table = False
    for line in lines:
        if line.strip().startswith("| Tipo de pedido"):
            in_table = True
            continue
        if in_table:
            if line.strip().startswith("|---"):
                continue
            m = ROUTING_ROW_RE.match(line.strip())
            if not m:
                if line.strip() == "" or not line.strip().startswith("|"):
                    break  # fim da tabela
                continue
            agente_ids = [a.strip() for a in re.split(r"\+", m.group("agentes"))]
            rows.append({"pedido": m.group("pedido"), "agentes": agente_ids})
    return rows


def build_report(fichas: list, routing: list) -> dict:
    ficha_ids = {f["id"] for f in fichas}
    routed_ids = set()
    broken_refs = []
    for row in routing:
        for agente in row["agentes"]:
            routed_ids.add(agente)
            if agente not in ficha_ids:
                broken_refs.append({"pedido": row["pedido"], "agente": agente})

    orphan_fichas = sorted(ficha_ids - routed_ids)
    malformed = [f["file"] for f in fichas if f.get("malformed")]

    return {
        "total_fichas": len(fichas),
        "total_rotas": len(routing),
        "referencias_quebradas": broken_refs,
        "fichas_orfas": orphan_fichas,
        "fichas_malformadas": malformed,
    }


def compose_estado_vivo(claude_md: str, fichas: list, report: dict) -> str:
    lines = ["# Estado Vivo — Axtro AI Factory", "",
             "> Gerado automaticamente por `axtro-factory-monitor/scripts/consolidate_state.py`. "
             "Não editar à mão — rode o script de novo para atualizar. Fonte de verdade "
             "sobre regras da empresa continua sendo o CLAUDE.md (reproduzido verbatim abaixo).",
             "", "---", "", "## 1. CLAUDE.md (raiz, verbatim)", "", claude_md, "",
             "---", "", "## 2. Roster de agentes ({} fichas)".format(len(fichas)), "",
             "| Nome | ID | Squad | Modelo |", "|---|---|---|---|"]
    for f in fichas:
        if f.get("malformed"):
            lines.append("| ⚠️ *(malformada)* | {} | — | — |".format(f["id"]))
        else:
            lines.append("| {} | `{}` | {} | {} |".format(f["name"], f["id"], f["squad"], f["model"]))

    lines += ["", "---", "", "## 3. Consistência roteamento × roster", "",
              "- Fichas: {} · Rotas no mapa: {}".format(report["total_fichas"], report["total_rotas"])]

    if report["referencias_quebradas"]:
        lines.append("")
        lines.append("### ⚠️ Referências quebradas (roteamento aponta pra ficha inexistente)")
        for b in report["referencias_quebradas"]:
            lines.append("- `{}` (pedido: \"{}\")".format(b["agente"], b["pedido"]))
    else:
        lines.append("- ✅ Nenhuma referência quebrada no mapa de roteamento.")

    if report["fichas_orfas"]:
        lines.append("")
        lines.append("### ℹ️ Fichas sem entrada no mapa de roteamento ({})".format(len(report["fichas_orfas"])))
        lines.append(", ".join("`{}`".format(i) for i in report["fichas_orfas"]))

    if report["fichas_malformadas"]:
        lines.append("")
        lines.append("### ⚠️ Fichas com cabeçalho fora do padrão (não parseadas)")
        lines.append(", ".join(report["fichas_malformadas"]))

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Consolida CLAUDE.md + fichas num estado vivo")
    parser.add_argument("--dry-run", action="store_true", help="só imprime o relatório de drift")
    args = parser.parse_args()

    root = common.find_axtro_root()
    claude_md_path = root / "CLAUDE.md"
    fichas_dir = root / "03_AGENTES" / "fichas"
    routing_path = root / "03_AGENTES" / "skills-claude" / "hermes-orquestrador.md"
    output_path = root / "03_AGENTES" / "ESTADO_VIVO.md"

    if not fichas_dir.is_dir():
        common.emit({"ok": False, "error": "fichas_dir ausente: {}".format(fichas_dir)})
        sys.exit(1)

    fichas = parse_fichas(fichas_dir)
    routing = parse_routing_map(routing_path)
    report = build_report(fichas, routing)

    if args.dry_run:
        common.emit(report)
        return

    claude_md = claude_md_path.read_text(encoding="utf-8", errors="replace") if claude_md_path.exists() else "*(CLAUDE.md não encontrado)*"
    content = compose_estado_vivo(claude_md, fichas, report)
    output_path.write_text(content, encoding="utf-8")
    common.emit({"ok": True, "output": str(output_path), **report})


if __name__ == "__main__":
    main()
