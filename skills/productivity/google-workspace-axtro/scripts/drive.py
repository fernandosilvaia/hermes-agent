"""
drive.py — Listar, criar pasta, upload, buscar e compartilhar no Google Drive.

Uso como biblioteca:
    from drive import list_files, create_folder, upload_file, find_by_name, share_file

Uso como CLI:
    python drive.py list --max 20
    python drive.py list --folder <FOLDER_ID>
    python drive.py mkdir --name "Relatórios" [--parent <FOLDER_ID>]
    python drive.py upload --path ./arquivo.pdf [--parent <FOLDER_ID>] [--name "outro.pdf"]
    python drive.py find --name "proposta"
    python drive.py share --id <FILE_ID> --email fulano@axtroai.com [--role writer]

Papéis de compartilhamento: reader (padrão), commenter, writer.

SEGURANÇA (P0): `share` é dry-run por padrão e bloqueia destinatários externos ao
domínio da empresa. Ver `_share_policy.py`. A ação real só ocorre com --execute +
HERMES_ALLOW_EXECUTE=true + GOOGLE_WORKSPACE_AXTRO_ENABLED=true; --dry-run sempre vence.
"""
from __future__ import annotations

import argparse
import json
import os

from googleapiclient.http import MediaFileUpload

import auth
import _share_policy

FOLDER_MIME = "application/vnd.google-apps.folder"


def list_files(max_results: int = 20, folder_id: str = None, query: str = None) -> list:
    """Lista arquivos/pastas. Restrinja a uma pasta com folder_id ou filtre com query bruta."""
    q_parts = ["trashed = false"]
    if folder_id:
        q_parts.append(f"'{folder_id}' in parents")
    if query:
        q_parts.append(query)
    resp = auth.drive().files().list(
        q=" and ".join(q_parts),
        pageSize=max_results,
        fields="files(id, name, mimeType, modifiedTime, size, webViewLink, parents)",
        orderBy="modifiedTime desc",
    ).execute()
    return resp.get("files", [])


def create_folder(name: str, parent_id: str = None) -> dict:
    body = {"name": name, "mimeType": FOLDER_MIME}
    if parent_id:
        body["parents"] = [parent_id]
    f = auth.drive().files().create(
        body=body, fields="id, name, webViewLink"
    ).execute()
    return f


def upload_file(path: str, parent_id: str = None, name: str = None) -> dict:
    if not os.path.isfile(path):
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")
    body = {"name": name or os.path.basename(path)}
    if parent_id:
        body["parents"] = [parent_id]
    media = MediaFileUpload(path, resumable=True)
    f = auth.drive().files().create(
        body=body, media_body=media, fields="id, name, webViewLink, size"
    ).execute()
    return f


def find_by_name(name: str, max_results: int = 20) -> list:
    """Busca arquivos cujo nome contém o texto dado."""
    safe = name.replace("'", "\\'")
    return list_files(max_results=max_results, query=f"name contains '{safe}'")


def share_file(file_id: str, email: str, role: str = "reader",
               notify: bool = False, approve_external: bool = False,
               dry_run: bool = True) -> dict:
    """Compartilha um arquivo/pasta com um email. role: reader | commenter | writer.

    SEGURANÇA (P0 — canal de exfiltração): toda a decisão passa por
    `_share_policy.evaluate_share` ANTES de qualquer chamada de API. Destinatários
    externos ao domínio da empresa são BLOQUEADOS por padrão; role=writer para
    externo exige aprovação explícita (approve_external=True + gate humano).

    dry_run=True (default seguro) → nunca chama a API; só descreve o que faria.
    A API só é chamada quando decision=PERMITIDO E dry_run=False.
    """
    if role not in ("reader", "commenter", "writer"):
        raise ValueError("role deve ser reader, commenter ou writer")

    verdict = _share_policy.evaluate_share(email, role, approve_external=approve_external)
    would_share = {
        "file_id": file_id,
        "email": email,
        "role": role,
        "notify": notify,
        "approve_external": approve_external,
    }

    # BLOQUEADO → retorna o veredito SEM tocar a API (fecha o furo).
    if verdict["decision"] == "BLOQUEADO":
        return {
            "shared": False,
            "blocked": True,
            "file_id": file_id,
            "email": email,
            "role": role,
            "verdict": verdict,
        }

    # PERMITIDO mas dry-run → descreve a ação SEM tocar a API.
    if dry_run:
        return {
            "shared": False,
            "dry_run": True,
            "would_share": would_share,
            "verdict": verdict,
        }

    # GATE DE AMBIENTE também aqui (não só no CLI): a via de BIBLIOTECA é documentada
    # e um daemon que executa Python poderia chamar share_file(dry_run=False) direto,
    # pulando o gate. Exige HERMES_ALLOW_EXECUTE=true E GOOGLE_WORKSPACE_AXTRO_ENABLED=true.
    # Faltando qualquer uma → dry-run (fail-CLOSED), sem tocar a API.
    gate = _share_policy.resolve_execution(dry_run_flag=False)
    if gate["dry_run"]:
        return {
            "shared": False,
            "dry_run": True,
            "gate_blocked": True,
            "would_share": would_share,
            "verdict": verdict,
            "gate": gate,
        }

    # PERMITIDO e execução real liberada → única via que chama a API.
    perm = {"type": "user", "role": role, "emailAddress": email}
    auth.drive().permissions().create(
        fileId=file_id, body=perm, sendNotificationEmail=notify,
        fields="id",
    ).execute()
    return {
        "shared": True,
        "file_id": file_id,
        "shared_with": email,
        "role": role,
        "verdict": verdict,
    }


def _cli():
    p = argparse.ArgumentParser(description="Google Drive via Hermes")
    sub = p.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("list")
    l.add_argument("--max", type=int, default=20)
    l.add_argument("--folder")
    l.add_argument("--query")

    mk = sub.add_parser("mkdir")
    mk.add_argument("--name", required=True)
    mk.add_argument("--parent")

    up = sub.add_parser("upload")
    up.add_argument("--path", required=True)
    up.add_argument("--parent")
    up.add_argument("--name")

    fi = sub.add_parser("find")
    fi.add_argument("--name", required=True)
    fi.add_argument("--max", type=int, default=20)

    sh = sub.add_parser("share")
    sh.add_argument("--id", required=True)
    sh.add_argument("--email", required=True)
    sh.add_argument("--role", default="reader")
    sh.add_argument("--notify", action="store_true")
    sh.add_argument("--approve-external", dest="approve_external",
                    action="store_true",
                    help="autoriza compartilhar com domínio externo (gate humano)")
    sh.add_argument("--execute", action="store_true",
                    help="tenta a ação real (ainda exige HERMES_ALLOW_EXECUTE=true "
                         "e GOOGLE_WORKSPACE_AXTRO_ENABLED=true)")
    sh.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="força o modo seguro; SEMPRE vence, mesmo com as envs setadas")

    args = p.parse_args()
    if args.cmd == "list":
        out = list_files(args.max, args.folder, args.query)
    elif args.cmd == "mkdir":
        out = create_folder(args.name, args.parent)
    elif args.cmd == "upload":
        out = upload_file(args.path, args.parent, args.name)
    elif args.cmd == "find":
        out = find_by_name(args.name, args.max)
    elif args.cmd == "share":
        # GATE PADRÃO: dry-run é o default PERMANENTE. A ação real só ocorre com
        # --execute (e não --dry-run) + HERMES_ALLOW_EXECUTE=true +
        # GOOGLE_WORKSPACE_AXTRO_ENABLED=true. O flag --dry-run sempre vence.
        dry_run_flag = args.dry_run or not args.execute
        mode = _share_policy.resolve_execution(dry_run_flag)
        out = share_file(
            args.id, args.email, args.role, args.notify,
            approve_external=args.approve_external,
            dry_run=mode["dry_run"],
        )
        out["gate"] = mode
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
