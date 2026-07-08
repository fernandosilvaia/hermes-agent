"""
gmail.py — Enviar, listar, buscar e organizar email como axtro@axtroai.com.

Uso como biblioteca:
    from gmail import send_email, list_recent, search, mark_read
    send_email(to="fulano@x.com", subject="Oi", body="Corpo do email")

Uso como CLI (o jeito que o Hermes normalmente chama):
    python gmail.py send --to fulano@x.com --subject "Oi" --body "Corpo"
    python gmail.py list --max 10
    python gmail.py search --query "from:cliente@x.com is:unread"
    python gmail.py read --id <MESSAGE_ID>
    python gmail.py mark-read --id <MESSAGE_ID>
"""

import argparse
import base64
import json
from email.message import EmailMessage

import auth
import _share_policy


def _raw(message: EmailMessage) -> dict:
    return {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode()}


def send_email(to: str, subject: str, body: str, cc: str = None, bcc: str = None,
               html: bool = False, approve_external: bool = False,
               dry_run: bool = True) -> dict:
    """Envia um email. `to`/`cc`/`bcc` podem ser vírgula-separados.

    SEGURANÇA (P0 — canal irmão de exfiltração): enviar email é tão capaz de
    vazar dado corporativo para fora quanto drive.share. Toda a lista de
    destinatários (to+cc+bcc) passa por `_share_policy.evaluate_recipients`
    ANTES de qualquer chamada de API: destinatário externo ao domínio da empresa
    é BLOQUEADO por padrão (só liberado com approve_external + allowlist de
    parceiros configurada fora de banda por um humano). dry_run=True (default
    seguro) nunca chama a API; a API só é chamada com decisão PERMITIDO E o gate
    de dupla-env (HERMES_ALLOW_EXECUTE + GOOGLE_WORKSPACE_AXTRO_ENABLED) aberto.
    """
    all_recipients = ",".join([r for r in (to, cc, bcc) if r])
    verdict = _share_policy.evaluate_recipients(all_recipients, approve_external=approve_external)
    would_send = {"to": to, "cc": cc, "bcc": bcc, "subject": subject}

    if verdict["decision"] == "BLOQUEADO":
        return {"sent": False, "blocked": True, "verdict": verdict, **would_send}
    if dry_run:
        return {"sent": False, "dry_run": True, "would_send": would_send, "verdict": verdict}
    gate = _share_policy.resolve_execution(dry_run_flag=False)
    if gate["dry_run"]:
        return {"sent": False, "dry_run": True, "gate_blocked": True,
                "would_send": would_send, "gate": gate, "verdict": verdict}

    msg = EmailMessage()
    msg["To"] = to
    if cc:
        msg["Cc"] = cc
    if bcc:
        msg["Bcc"] = bcc
    msg["Subject"] = subject
    if html:
        msg.set_content("Este email requer um cliente compatível com HTML.")
        msg.add_alternative(body, subtype="html")
    else:
        msg.set_content(body)

    sent = auth.gmail().users().messages().send(userId="me", body=_raw(msg)).execute()
    return {"sent": True, "id": sent.get("id"), "threadId": sent.get("threadId"),
            "to": to, "subject": subject}


def _headers(msg: dict) -> dict:
    out = {}
    for h in msg.get("payload", {}).get("headers", []):
        out[h["name"].lower()] = h["value"]
    return out


def list_recent(max_results: int = 10, query: str = None) -> list:
    """Lista mensagens recentes (metadados). Use `query` para filtrar (sintaxe do Gmail)."""
    svc = auth.gmail()
    resp = svc.users().messages().list(
        userId="me", maxResults=max_results, q=query
    ).execute()
    results = []
    for ref in resp.get("messages", []):
        full = svc.users().messages().get(
            userId="me", id=ref["id"], format="metadata",
            metadataHeaders=["From", "To", "Subject", "Date"],
        ).execute()
        h = _headers(full)
        results.append({
            "id": full["id"],
            "threadId": full.get("threadId"),
            "from": h.get("from"),
            "subject": h.get("subject"),
            "date": h.get("date"),
            "snippet": full.get("snippet"),
            "unread": "UNREAD" in full.get("labelIds", []),
        })
    return results


def search(query: str, max_results: int = 20) -> list:
    """Busca por sintaxe do Gmail, ex.: 'from:x@y.com subject:fatura is:unread'."""
    return list_recent(max_results=max_results, query=query)


def _decode_body(payload: dict) -> str:
    """Extrai o texto de um payload de mensagem (procura text/plain, cai pro primeiro texto)."""
    def walk(part):
        mime = part.get("mimeType", "")
        data = part.get("body", {}).get("data")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        for sub in part.get("parts", []) or []:
            found = walk(sub)
            if found:
                return found
        if data:  # fallback: qualquer corpo com dados
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        return None

    return walk(payload) or ""


def read_message(message_id: str) -> dict:
    """Lê uma mensagem completa (cabeçalhos + corpo em texto)."""
    full = auth.gmail().users().messages().get(
        userId="me", id=message_id, format="full"
    ).execute()
    h = _headers(full)
    return {
        "id": full["id"],
        "threadId": full.get("threadId"),
        "from": h.get("from"),
        "to": h.get("to"),
        "subject": h.get("subject"),
        "date": h.get("date"),
        "unread": "UNREAD" in full.get("labelIds", []),
        "body": _decode_body(full.get("payload", {})),
    }


def mark_read(message_id: str) -> dict:
    """Marca uma mensagem como lida (remove o label UNREAD)."""
    auth.gmail().users().messages().modify(
        userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
    ).execute()
    return {"id": message_id, "marked": "read"}


def _cli():
    p = argparse.ArgumentParser(description="Gmail via Hermes (axtro@axtroai.com)")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("send")
    s.add_argument("--to", required=True)
    s.add_argument("--subject", required=True)
    s.add_argument("--body", required=True)
    s.add_argument("--cc")
    s.add_argument("--bcc")
    s.add_argument("--html", action="store_true")
    s.add_argument("--approve-external", action="store_true",
                   help="marca aprovacao para destinatario externo (só vale com o dominio na allowlist de parceiros)")
    s.add_argument("--execute", action="store_true", help="sai do dry-run (precisa das duas envs do gate)")
    s.add_argument("--dry-run", action="store_true", help="forca dry-run (sempre vence)")

    l = sub.add_parser("list")
    l.add_argument("--max", type=int, default=10)
    l.add_argument("--query")

    se = sub.add_parser("search")
    se.add_argument("--query", required=True)
    se.add_argument("--max", type=int, default=20)

    r = sub.add_parser("read")
    r.add_argument("--id", required=True)

    m = sub.add_parser("mark-read")
    m.add_argument("--id", required=True)

    args = p.parse_args()
    if args.cmd == "send":
        # Dry-run é o default: só sai dele com --execute E as duas envs do gate.
        # --dry-run explícito sempre vence (resolvido dentro de send_email via gate).
        dry_run = getattr(args, "dry_run", False) or not getattr(args, "execute", False)
        out = send_email(args.to, args.subject, args.body, args.cc, args.bcc, args.html,
                         approve_external=getattr(args, "approve_external", False),
                         dry_run=dry_run)
    elif args.cmd == "list":
        out = list_recent(args.max, args.query)
    elif args.cmd == "search":
        out = search(args.query, args.max)
    elif args.cmd == "read":
        out = read_message(args.id)
    elif args.cmd == "mark-read":
        out = mark_read(args.id)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
