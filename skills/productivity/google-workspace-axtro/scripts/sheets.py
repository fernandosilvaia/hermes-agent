"""
sheets.py — Criar planilha, ler/escrever ranges e adicionar linhas no Google Sheets.

Uso como biblioteca:
    from sheets import create_sheet, read_range, write_range, append_row

Uso como CLI:
    python sheets.py create --title "Controle de gastos" [--parent <FOLDER_ID>]
    python sheets.py read --id <SHEET_ID> --range "Página1!A1:D10"
    python sheets.py write --id <SHEET_ID> --range "Página1!A1" --values '[["Data","Valor"],["01/07","200"]]'
    python sheets.py append --id <SHEET_ID> --range "Página1!A1" --values '["01/07","200","OpenRouter"]'

--values é um JSON: matriz (lista de listas) para write, lista simples para append.
"""

import argparse
import json

import auth


def create_sheet(title: str, parent_id: str = None) -> dict:
    ss = auth.sheets().spreadsheets().create(
        body={"properties": {"title": title}},
        fields="spreadsheetId, spreadsheetUrl",
    ).execute()
    ss_id = ss["spreadsheetId"]

    if parent_id:
        drive = auth.drive()
        file = drive.files().get(fileId=ss_id, fields="parents").execute()
        prev = ",".join(file.get("parents", []))
        drive.files().update(
            fileId=ss_id, addParents=parent_id, removeParents=prev, fields="id"
        ).execute()

    return {"spreadsheetId": ss_id, "title": title, "url": ss.get("spreadsheetUrl")}


def read_range(spreadsheet_id: str, cell_range: str) -> dict:
    """Lê um range, ex.: 'Página1!A1:D10'."""
    resp = auth.sheets().spreadsheets().values().get(
        spreadsheetId=spreadsheet_id, range=cell_range
    ).execute()
    return {"range": resp.get("range"), "values": resp.get("values", [])}


def write_range(spreadsheet_id: str, cell_range: str, values: list) -> dict:
    """Escreve/atualiza um range. `values` é lista de listas (linhas)."""
    resp = auth.sheets().spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range=cell_range,
        valueInputOption="USER_ENTERED",
        body={"values": values},
    ).execute()
    return {
        "updatedRange": resp.get("updatedRange"),
        "updatedCells": resp.get("updatedCells"),
    }


def append_row(spreadsheet_id: str, cell_range: str, row: list) -> dict:
    """Adiciona uma linha ao final da tabela que começa em cell_range."""
    resp = auth.sheets().spreadsheets().values().append(
        spreadsheetId=spreadsheet_id,
        range=cell_range,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body={"values": [row]},
    ).execute()
    return {"updates": resp.get("updates", {})}


def _cli():
    p = argparse.ArgumentParser(description="Google Sheets via Hermes")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--title", required=True)
    c.add_argument("--parent")

    r = sub.add_parser("read")
    r.add_argument("--id", required=True)
    r.add_argument("--range", required=True)

    w = sub.add_parser("write")
    w.add_argument("--id", required=True)
    w.add_argument("--range", required=True)
    w.add_argument("--values", required=True, help="JSON: lista de listas")

    a = sub.add_parser("append")
    a.add_argument("--id", required=True)
    a.add_argument("--range", required=True)
    a.add_argument("--values", required=True, help="JSON: lista simples (uma linha)")

    args = p.parse_args()
    if args.cmd == "create":
        out = create_sheet(args.title, args.parent)
    elif args.cmd == "read":
        out = read_range(args.id, args.range)
    elif args.cmd == "write":
        out = write_range(args.id, args.range, json.loads(args.values))
    elif args.cmd == "append":
        out = append_row(args.id, args.range, json.loads(args.values))
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
