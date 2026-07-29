"""
instagram_publish.py — Publica foto/video/Reels no Instagram Business via Meta
Graph API, em DUAS etapas separadas de proposito: preparar (draft) e publicar
de verdade (publish). Nunca junta as duas numa chamada so.

Por que duas etapas: a API do Instagram ja funciona assim por baixo (cria um
"container" de midia, depois publica o container), e isso encaixa direto com
a regra de negocio: o agente PREPARA o post sozinho, mas so publica de
verdade depois que o Fernando confirmar explicitamente na conversa. create_draft()
nunca deixa nada publico; publish_draft() e o unico ponto que publica de
verdade e so deve ser chamado depois dessa confirmacao.

A API do Instagram exige uma URL PUBLICA pra buscar a midia (nao aceita
upload direto de arquivo). Por isso o passo 0 (upload_to_public_media) copia
o arquivo local pra pasta publica temporaria do Caddy
(/opt/data/public_media -> https://hermes.axtroai.com/media/<uuid>), que some
sozinha depois de 30min (cron de limpeza na VPS). So funciona em instancias
com essa rota configurada (hoje: o Axtro Agent na VPS). Ver
skills/media/video-editing se precisar editar o video/imagem antes de postar.

Uso como biblioteca:
    from instagram_publish import upload_to_public_media, create_draft, publish_draft, delete_draft

Uso como CLI:
    python instagram_publish.py upload video_pronto.mp4
    python instagram_publish.py draft --media-url https://hermes.axtroai.com/media/xxx.mp4 \
        --caption "Legenda do post" --type REELS
    python instagram_publish.py publish --container-id 123456789
    python instagram_publish.py cancel --container-id 123456789

Env necessarias:
    META_ACCESS_TOKEN (ou META_APP_API_TOKEN)  — token de longa duracao com
        instagram_basic, instagram_content_publish, pages_show_list,
        pages_read_engagement
    META_PAGE_ID       — Page ID do Facebook vinculada à conta Instagram Business
    HERMES_PUBLIC_MEDIA_BASE_URL  (opcional, padrao https://hermes.axtroai.com/media)
    HERMES_PUBLIC_MEDIA_DIR       (opcional, padrao /opt/data/public_media)

⚠️ REGRA DE NEGOCIO (inegociavel): create_draft() NUNCA publica nada, so cria
   o rascunho no lado do Instagram (ainda invisivel pro publico). publish_draft()
   E QUEM PUBLICA DE VERDADE — so chame depois que o Fernando disser
   explicitamente "pode publicar" (ou equivalente) NA CONVERSA, pro post
   especifico em questao. Nunca assuma aprovacao de uma vez anterior.
"""

import argparse
import json
import os
import shutil
import time
import uuid
from pathlib import Path

import requests

GRAPH_BASE = "https://graph.facebook.com/v20.0"
DEFAULT_PUBLIC_MEDIA_DIR = "/opt/data/public_media"
DEFAULT_PUBLIC_MEDIA_BASE_URL = "https://hermes.axtroai.com/media"


def _access_token() -> str:
    token = os.environ.get("META_ACCESS_TOKEN") or os.environ.get("META_APP_API_TOKEN")
    if not token:
        raise RuntimeError(
            "META_ACCESS_TOKEN (ou META_APP_API_TOKEN) nao esta no ambiente. "
            "Rode via cofre (Doppler) para injetar."
        )
    return token


def _page_id() -> str:
    page_id = os.environ.get("META_PAGE_ID")
    if not page_id:
        raise RuntimeError("META_PAGE_ID nao esta no ambiente.")
    return page_id


def upload_to_public_media(local_path: str) -> str:
    """Copia um arquivo local pra pasta publica temporaria e devolve a URL
    publica (some sozinho em 30min, cron de limpeza cuida disso)."""
    src = Path(local_path)
    if not src.exists():
        raise FileNotFoundError(f"Arquivo nao encontrado: {local_path}")
    media_dir = Path(os.environ.get("HERMES_PUBLIC_MEDIA_DIR", DEFAULT_PUBLIC_MEDIA_DIR))
    media_dir.mkdir(parents=True, exist_ok=True)
    dest_name = f"{uuid.uuid4().hex}{src.suffix.lower()}"
    dest = media_dir / dest_name
    shutil.copy2(src, dest)
    base_url = os.environ.get("HERMES_PUBLIC_MEDIA_BASE_URL", DEFAULT_PUBLIC_MEDIA_BASE_URL)
    return f"{base_url.rstrip('/')}/{dest_name}"


def _resolve_ig_account_id(token: str, page_id: str) -> str:
    resp = requests.get(
        f"{GRAPH_BASE}/{page_id}",
        params={"fields": "instagram_business_account", "access_token": token},
        timeout=15,
    )
    data = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API erro ao resolver conta Instagram: {json.dumps(data)}")
    ig_account = (data.get("instagram_business_account") or {}).get("id")
    if not ig_account:
        raise RuntimeError(
            "Nenhuma conta Instagram Business vinculada a essa Page. "
            "Confirme que a conta é Business/Creator e está linkada à Page no Meta Business Suite."
        )
    return ig_account


def create_draft(media_url: str, caption: str, media_type: str = "REELS") -> dict:
    """Cria o container de midia no Instagram — RASCUNHO, ainda nao publico.
    media_type: IMAGE, VIDEO ou REELS.
    Retorna o container_id que precisa ser passado pra publish_draft() depois
    da aprovacao explicita do Fernando."""
    if media_type not in ("IMAGE", "VIDEO", "REELS"):
        raise ValueError("media_type deve ser IMAGE, VIDEO ou REELS.")
    token = _access_token()
    page_id = _page_id()
    ig_account_id = _resolve_ig_account_id(token, page_id)

    params = {"access_token": token, "caption": caption}
    if media_type == "IMAGE":
        params["image_url"] = media_url
    else:
        params["media_type"] = media_type
        params["video_url"] = media_url

    resp = requests.post(f"{GRAPH_BASE}/{ig_account_id}/media", data=params, timeout=60)
    data = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API erro ao criar rascunho: {json.dumps(data)}")
    container_id = data.get("id")
    if not container_id:
        raise RuntimeError(f"Resposta inesperada da Graph API: {json.dumps(data)}")
    return {
        "container_id": container_id,
        "ig_account_id": ig_account_id,
        "media_type": media_type,
        "status": "rascunho criado, AINDA NAO PUBLICO — chame publish_draft() so depois da aprovacao explicita",
    }


def get_draft_status(container_id: str) -> dict:
    """Consulta o status de processamento do container (util pra video/reels
    grande, que a Meta processa de forma assincrona antes de poder publicar)."""
    token = _access_token()
    resp = requests.get(
        f"{GRAPH_BASE}/{container_id}",
        params={"fields": "status_code,status", "access_token": token},
        timeout=15,
    )
    data = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API erro ao consultar status: {json.dumps(data)}")
    return data


def publish_draft(container_id: str, ig_account_id: str = None) -> dict:
    """PUBLICA DE VERDADE o container ja criado. So chame depois que o
    Fernando confirmar explicitamente, na conversa, que quer publicar ESSE
    post especifico."""
    token = _access_token()
    if not ig_account_id:
        ig_account_id = _resolve_ig_account_id(token, _page_id())

    resp = requests.post(
        f"{GRAPH_BASE}/{ig_account_id}/media_publish",
        data={"access_token": token, "creation_id": container_id},
        timeout=60,
    )
    data = resp.json()
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API erro ao publicar: {json.dumps(data)}")
    post_id = data.get("id")
    return {
        "post_id": post_id,
        "permalink": f"https://www.instagram.com/p/{post_id}/" if post_id else None,
        "status": "PUBLICADO",
    }


def delete_draft(container_id: str) -> dict:
    """Descarta um rascunho que nao vai ser publicado (o container do
    Instagram expira sozinho depois de um tempo, mas isso libera na hora)."""
    token = _access_token()
    resp = requests.delete(
        f"{GRAPH_BASE}/{container_id}",
        params={"access_token": token},
        timeout=15,
    )
    data = resp.json() if resp.content else {}
    if resp.status_code >= 400:
        raise RuntimeError(f"Graph API erro ao descartar rascunho: {json.dumps(data)}")
    return {"container_id": container_id, "status": "descartado"}


def _cli():
    p = argparse.ArgumentParser(description="Publicar no Instagram (Meta Graph API)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("upload", help="Hospedar um arquivo local temporariamente pra ter URL publica")
    s.add_argument("local_path")

    s = sub.add_parser("draft", help="Criar rascunho (NAO publica)")
    s.add_argument("--media-url", required=True)
    s.add_argument("--caption", required=True)
    s.add_argument("--type", dest="media_type", default="REELS", choices=["IMAGE", "VIDEO", "REELS"])

    s = sub.add_parser("status", help="Consultar status de processamento do rascunho")
    s.add_argument("--container-id", required=True)

    s = sub.add_parser("publish", help="PUBLICAR DE VERDADE (so depois de aprovacao explicita)")
    s.add_argument("--container-id", required=True)
    s.add_argument("--ig-account-id", default=None)

    s = sub.add_parser("cancel", help="Descartar um rascunho")
    s.add_argument("--container-id", required=True)

    args = p.parse_args()

    try:
        if args.command == "upload":
            out = {"public_url": upload_to_public_media(args.local_path)}
        elif args.command == "draft":
            out = create_draft(args.media_url, args.caption, args.media_type)
        elif args.command == "status":
            out = get_draft_status(args.container_id)
        elif args.command == "publish":
            out = publish_draft(args.container_id, args.ig_account_id)
        elif args.command == "cancel":
            out = delete_draft(args.container_id)
        else:
            p.error("comando desconhecido")
            return
    except (RuntimeError, ValueError, FileNotFoundError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        raise SystemExit(1)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
