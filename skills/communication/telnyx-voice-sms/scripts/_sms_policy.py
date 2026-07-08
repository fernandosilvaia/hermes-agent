"""
_sms_policy.py — Lógica PURA de política do lado de RECEBIMENTO (inbox/OTP).

Só stdlib. NÃO importa requests, fastapi, nacl nem toca a rede. Serve para poder
ser testado no python3 do sistema (3.9.6) sem nenhuma dependência externa e para
concentrar toda a DECISÃO de segurança do endpoint /sms/last e do read_inbox.

Contém:
    mask_otp(record)      -> cópia do record com verification_code e OTP no texto mascarados
    require_token(a, b)   -> comparação constant-time (hmac.compare_digest)
    extract_bearer(header)-> extrai o token de "Authorization: Bearer <token>"
    reveal_allowed(env)   -> True só com o gate HERMES_ALLOW_EXECUTE + TELNYX_VOICE_SMS_ENABLED
"""
from __future__ import annotations

import hmac
import os
import re

# Mesma heurística de OTP usada ao gravar o inbox: sequência isolada de 4 a 8 dígitos.
_DIGIT_RUN = re.compile(r"\b(\d{4,8})\b")


def _mask_code(code) -> str:
    """Mascara um código, mantendo no máximo os 2 últimos dígitos.

    Códigos com 2 dígitos ou menos viram [REDIGIDO] (mostrar 2 de 2 não mascara nada).
    """
    if code is None:
        return code
    s = str(code)
    if len(s) <= 2:
        return "[REDIGIDO]"
    return "*" * (len(s) - 2) + s[-2:]


def mask_otp(record):
    """Devolve uma CÓPIA do record com o OTP mascarado.

    - verification_code -> mascarado (só 2 últimos dígitos).
    - text -> toda sequência de 4-8 dígitos mascarada (fecha o vazamento mesmo que o
      código apareça no corpo mais de uma vez ou não tenha sido flagado no campo).
    Nunca muta o record original (o arquivo local pode manter o código cru; a saída
    HTTP/CLI é que nunca devolve OTP em claro).
    """
    if not isinstance(record, dict):
        return record
    masked = dict(record)
    if masked.get("verification_code"):
        masked["verification_code"] = _mask_code(masked["verification_code"])
    text = masked.get("text")
    if isinstance(text, str) and text:
        masked["text"] = _DIGIT_RUN.sub(lambda m: _mask_code(m.group(1)), text)
    return masked


def require_token(provided, expected) -> bool:
    """True só se provided casar com expected em comparação constant-time.

    Strings/valores vazios ou ausentes -> False (nunca autoriza sem token configurado).
    """
    if not provided or not expected:
        return False
    return hmac.compare_digest(str(provided), str(expected))


def extract_bearer(header) -> str:
    """Extrai o token de um header 'Authorization: Bearer <token>'.

    Retorna "" se o header estiver ausente/malformado (esquema errado, sem token).
    """
    if not header or not isinstance(header, str):
        return ""
    parts = header.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def reveal_allowed(env=None) -> bool:
    """True só se o gate humano estiver 100% aberto para revelar o OTP em claro.

    Exige HERMES_ALLOW_EXECUTE == "true" E TELNYX_VOICE_SMS_ENABLED == "true".
    Faltando qualquer uma -> False (o padrão é sempre mascarar).
    """
    env = env if env is not None else os.environ
    if (env.get("HERMES_ALLOW_EXECUTE", "") or "").strip().lower() != "true":
        return False
    if (env.get("TELNYX_VOICE_SMS_ENABLED", "") or "").strip().lower() != "true":
        return False
    return True
