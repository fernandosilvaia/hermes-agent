"""
auth.py — Autenticação compartilhada para a skill google-workspace do Hermes Agent.

Mecanismo: Service Account do Google Cloud + Domain-Wide Delegation.
A service account impersona (age como) a conta axtro@axtroai.com, autorizada
pelo admin do Google Workspace.

Credenciais lidas do ambiente em runtime (injetadas pelo cofre — Doppler/1Password):
  - GOOGLE_SERVICE_ACCOUNT_KEY_JSON : STRING com o JSON inteiro da chave (não é caminho)
  - GOOGLE_SERVICE_ACCOUNT_EMAIL    : (opcional, informativo)
  - GOOGLE_CLIENT_ID                : (opcional, informativo, não secreto)

Nunca hardcode credenciais. Nunca logue o conteúdo de GOOGLE_SERVICE_ACCOUNT_KEY_JSON.
"""

import json
import os
from functools import lru_cache

from google.oauth2 import service_account
from googleapiclient.discovery import build

# Conta impersonada via domain-wide delegation. Pode ser sobrescrita por env
# se um dia precisar agir como outra caixa do mesmo domínio.
IMPERSONATED_USER = os.environ.get("GOOGLE_IMPERSONATED_USER", "axtro@axtroai.com")

# Escopos por serviço — cada função pede só o que precisa (menor privilégio).
# Todos já autorizados no admin do Workspace (ver brief).
SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.modify"],
    "drive": ["https://www.googleapis.com/auth/drive"],
    "docs": [
        "https://www.googleapis.com/auth/documents",
        "https://www.googleapis.com/auth/drive",
    ],
    "sheets": [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ],
    "slides": [
        "https://www.googleapis.com/auth/presentations",
        "https://www.googleapis.com/auth/drive",
    ],
    "calendar": ["https://www.googleapis.com/auth/calendar"],
}


class WorkspaceAuthError(RuntimeError):
    """Erro claro de autenticação — nunca falhar silenciosamente."""


def _load_key_info() -> dict:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_KEY_JSON")
    if not raw:
        raise WorkspaceAuthError(
            "GOOGLE_SERVICE_ACCOUNT_KEY_JSON não está definido no ambiente. "
            "Rode o Hermes através do cofre (ex.: `doppler run -- ...` ou `op run -- ...`) "
            "para injetar a credencial em runtime."
        )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise WorkspaceAuthError(
            "GOOGLE_SERVICE_ACCOUNT_KEY_JSON existe mas não é um JSON válido. "
            "Confirme que a variável contém o CONTEÚDO do arquivo de chave "
            "(a string JSON inteira), não um caminho de arquivo."
        ) from exc


def get_credentials(service: str):
    """Retorna credenciais impersonadas prontas para o serviço pedido."""
    if service not in SCOPES:
        raise WorkspaceAuthError(
            f"Serviço desconhecido: {service!r}. "
            f"Opções: {', '.join(sorted(SCOPES))}."
        )
    info = _load_key_info()
    try:
        creds = service_account.Credentials.from_service_account_info(
            info, scopes=SCOPES[service]
        )
    except Exception as exc:  # noqa: BLE001 — queremos mensagem clara
        raise WorkspaceAuthError(
            f"Falha ao carregar a service account: {exc}"
        ) from exc
    return creds.with_subject(IMPERSONATED_USER)


# Cacheia os clients construídos por (api, versão) — evita reconstruir a cada chamada.
@lru_cache(maxsize=None)
def _build(service: str, api_name: str, api_version: str):
    creds = get_credentials(service)
    # cache_discovery=False evita warnings/erros de cache em ambientes efêmeros (Docker).
    return build(api_name, api_version, credentials=creds, cache_discovery=False)


def gmail():
    return _build("gmail", "gmail", "v1")


def drive():
    return _build("drive", "drive", "v3")


def docs():
    return _build("docs", "docs", "v1")


def sheets():
    return _build("sheets", "sheets", "v4")


def slides():
    return _build("slides", "slides", "v1")


def calendar():
    return _build("calendar", "calendar", "v3")


def whoami() -> dict:
    """Sanity check: confirma que a autenticação funciona e mostra quem estamos impersonando."""
    profile = gmail().users().getProfile(userId="me").execute()
    return {
        "impersonating": IMPERSONATED_USER,
        "emailAddress": profile.get("emailAddress"),
        "messagesTotal": profile.get("messagesTotal"),
        "service_account_email": os.environ.get("GOOGLE_SERVICE_ACCOUNT_EMAIL", "(não informado)"),
    }


if __name__ == "__main__":
    # `python auth.py` → teste de fumaça da autenticação.
    import sys

    try:
        info = whoami()
    except WorkspaceAuthError as exc:
        print(f"[auth] ERRO: {exc}", file=sys.stderr)
        sys.exit(1)
    print("[auth] OK — autenticação funcionando")
    for k, v in info.items():
        print(f"  {k}: {v}")
