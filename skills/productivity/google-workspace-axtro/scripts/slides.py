"""
slides.py — Criar apresentação, adicionar slide (título+corpo) e ler texto no Google Slides.

Uso como biblioteca:
    from slides import create_presentation, add_slide, read_presentation

Uso como CLI:
    python slides.py create --title "Pitch Axtro" [--parent <FOLDER_ID>]
    python slides.py add --id <PRES_ID> --title "Problema" --body "Texto do corpo"
    python slides.py read --id <PRES_ID>
"""

import argparse
import json
import uuid

import auth


def create_presentation(title: str, parent_id: str = None) -> dict:
    pres = auth.slides().presentations().create(body={"title": title}).execute()
    pres_id = pres["presentationId"]

    if parent_id:
        drive = auth.drive()
        file = drive.files().get(fileId=pres_id, fields="parents").execute()
        prev = ",".join(file.get("parents", []))
        drive.files().update(
            fileId=pres_id, addParents=parent_id, removeParents=prev, fields="id"
        ).execute()

    return {
        "presentationId": pres_id,
        "title": title,
        "url": f"https://docs.google.com/presentation/d/{pres_id}/edit",
    }


def add_slide(presentation_id: str, title: str, body: str = "") -> dict:
    """Adiciona um slide com layout TÍTULO+CORPO e preenche os placeholders."""
    svc = auth.slides()
    slide_id = f"slide_{uuid.uuid4().hex[:12]}"

    # 1) cria o slide com o layout predefinido
    svc.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": [{
            "createSlide": {
                "objectId": slide_id,
                "slideLayoutReference": {"predefinedLayout": "TITLE_AND_BODY"},
            }
        }]},
    ).execute()

    # 2) descobre os objectIds dos placeholders TITLE e BODY nesse slide
    pres = svc.presentations().get(presentationId=presentation_id).execute()
    title_id = body_id = None
    for slide in pres.get("slides", []):
        if slide.get("objectId") != slide_id:
            continue
        for el in slide.get("pageElements", []):
            ph = el.get("shape", {}).get("placeholder", {})
            kind = ph.get("type")
            if kind == "TITLE" and title_id is None:
                title_id = el["objectId"]
            elif kind in ("BODY", "SUBTITLE") and body_id is None:
                body_id = el["objectId"]

    # 3) insere os textos
    reqs = []
    if title_id and title:
        reqs.append({"insertText": {"objectId": title_id, "text": title}})
    if body_id and body:
        reqs.append({"insertText": {"objectId": body_id, "text": body}})
    if reqs:
        svc.presentations().batchUpdate(
            presentationId=presentation_id, body={"requests": reqs}
        ).execute()

    return {"presentationId": presentation_id, "slideId": slide_id, "title": title}


def read_presentation(presentation_id: str) -> dict:
    """Lê o texto de todos os slides."""
    pres = auth.slides().presentations().get(presentationId=presentation_id).execute()
    slides_out = []
    for i, slide in enumerate(pres.get("slides", []), start=1):
        texts = []
        for el in slide.get("pageElements", []):
            for line in el.get("shape", {}).get("text", {}).get("textElements", []):
                content = line.get("textRun", {}).get("content")
                if content and content.strip():
                    texts.append(content.strip())
        slides_out.append({"slide": i, "objectId": slide.get("objectId"), "text": texts})
    return {
        "presentationId": presentation_id,
        "title": pres.get("title"),
        "slides": slides_out,
    }


def _cli():
    p = argparse.ArgumentParser(description="Google Slides via Hermes")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--title", required=True)
    c.add_argument("--parent")

    a = sub.add_parser("add")
    a.add_argument("--id", required=True)
    a.add_argument("--title", required=True)
    a.add_argument("--body", default="")

    r = sub.add_parser("read")
    r.add_argument("--id", required=True)

    args = p.parse_args()
    if args.cmd == "create":
        out = create_presentation(args.title, args.parent)
    elif args.cmd == "add":
        out = add_slide(args.id, args.title, args.body)
    elif args.cmd == "read":
        out = read_presentation(args.id)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
