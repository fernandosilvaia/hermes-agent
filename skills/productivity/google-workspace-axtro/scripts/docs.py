"""
docs.py — Criar, ler e inserir texto em Google Docs.

Uso como biblioteca:
    from docs import create_doc, read_doc, insert_text

Uso como CLI:
    python docs.py create --title "Ata da reunião" --body "Texto aqui" [--parent <FOLDER_ID>]
    python docs.py create --title "Relatório" --body-file ./texto.md --markdown
    python docs.py read --id <DOC_ID>
    python docs.py insert --id <DOC_ID> --text "Parágrafo novo" [--at 1]

Sobre --markdown: aplica estilos de título para linhas iniciadas por '# ' e '## '.
Não é um conversor de markdown completo (negrito/tabelas/etc. ficam como texto).
"""

import argparse
import json

import auth


def create_doc(title: str, body: str = "", parent_id: str = None,
               markdown: bool = False) -> dict:
    """Cria um Doc novo. Se parent_id for dado, move o doc para essa pasta."""
    doc = auth.docs().documents().create(body={"title": title}).execute()
    doc_id = doc["documentId"]

    if body:
        _insert(doc_id, body, index=1, markdown=markdown)

    if parent_id:
        # O Docs API cria na raiz do Drive; movemos via Drive API.
        drive = auth.drive()
        file = drive.files().get(fileId=doc_id, fields="parents").execute()
        prev = ",".join(file.get("parents", []))
        drive.files().update(
            fileId=doc_id, addParents=parent_id, removeParents=prev, fields="id, parents"
        ).execute()

    return {
        "documentId": doc_id,
        "title": title,
        "url": f"https://docs.google.com/document/d/{doc_id}/edit",
    }


def _insert(doc_id: str, text: str, index: int = 1, markdown: bool = False):
    """Insere texto no índice dado. Com markdown=True, aplica Heading styles simples."""
    if not markdown:
        requests = [{"insertText": {"location": {"index": index}, "text": text}}]
        auth.docs().documents().batchUpdate(
            documentId=doc_id, body={"requests": requests}
        ).execute()
        return

    # Markdown leve: insere tudo, depois aplica estilo de título por linha.
    requests = [{"insertText": {"location": {"index": index}, "text": text}}]
    # Calcula ranges de linhas de heading para aplicar estilo.
    cursor = index
    style_reqs = []
    for line in text.split("\n"):
        line_len = len(line) + 1  # +1 pelo \n
        heading = None
        if line.startswith("## "):
            heading = "HEADING_2"
        elif line.startswith("# "):
            heading = "HEADING_1"
        if heading:
            style_reqs.append({
                "updateParagraphStyle": {
                    "range": {"startIndex": cursor, "endIndex": cursor + line_len},
                    "paragraphStyle": {"namedStyleType": heading},
                    "fields": "namedStyleType",
                }
            })
        cursor += line_len
    auth.docs().documents().batchUpdate(
        documentId=doc_id, body={"requests": requests + style_reqs}
    ).execute()


def insert_text(doc_id: str, text: str, index: int = 1, markdown: bool = False) -> dict:
    _insert(doc_id, text, index=index, markdown=markdown)
    return {"documentId": doc_id, "inserted_chars": len(text), "at_index": index}


def read_doc(doc_id: str) -> dict:
    """Lê o conteúdo textual de um Doc."""
    doc = auth.docs().documents().get(documentId=doc_id).execute()
    out = []
    for el in doc.get("body", {}).get("content", []):
        para = el.get("paragraph")
        if not para:
            continue
        for run in para.get("elements", []):
            txt = run.get("textRun", {}).get("content")
            if txt:
                out.append(txt)
    return {
        "documentId": doc_id,
        "title": doc.get("title"),
        "text": "".join(out),
    }


def _cli():
    p = argparse.ArgumentParser(description="Google Docs via Hermes")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--title", required=True)
    c.add_argument("--body", default="")
    c.add_argument("--body-file")
    c.add_argument("--parent")
    c.add_argument("--markdown", action="store_true")

    r = sub.add_parser("read")
    r.add_argument("--id", required=True)

    i = sub.add_parser("insert")
    i.add_argument("--id", required=True)
    i.add_argument("--text", required=True)
    i.add_argument("--at", type=int, default=1)
    i.add_argument("--markdown", action="store_true")

    args = p.parse_args()
    if args.cmd == "create":
        body = args.body
        if args.body_file:
            with open(args.body_file, encoding="utf-8") as fh:
                body = fh.read()
        out = create_doc(args.title, body, args.parent, args.markdown)
    elif args.cmd == "read":
        out = read_doc(args.id)
    elif args.cmd == "insert":
        out = insert_text(args.id, args.text, args.at, args.markdown)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
