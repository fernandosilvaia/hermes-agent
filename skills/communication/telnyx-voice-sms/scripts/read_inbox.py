"""
read_inbox.py — Lê os SMS recebidos (gravados pelo webhook_server.py).

Por padrão MASCARA o OTP em toda saída (last/recent/code). O código em claro só é
revelado com --reveal E com o gate humano aberto (HERMES_ALLOW_EXECUTE=true E
TELNYX_VOICE_SMS_ENABLED=true) — senão continua mascarado.

Uso como biblioteca:
    from read_inbox import last_sms, recent_sms, last_code

Uso como CLI:
    python read_inbox.py last            # último SMS (OTP mascarado)
    python read_inbox.py recent --n 5    # últimos N (OTP mascarado)
    python read_inbox.py code            # último código de verificação (mascarado)
    python read_inbox.py code --reveal   # revela o OTP SÓ com o gate aberto

Env:
    SMS_INBOX_PATH  (opcional, padrão /opt/data/telnyx_sms_inbox.jsonl —
                     precisa bater com o valor usado no webhook_server.py)
    HERMES_ALLOW_EXECUTE / TELNYX_VOICE_SMS_ENABLED  (gate p/ --reveal)
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Política PURA (stdlib only) — máscara de OTP + gate de reveal.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _sms_policy import mask_otp, reveal_allowed  # noqa: E402

SMS_INBOX_PATH = os.environ.get("SMS_INBOX_PATH", "/opt/data/telnyx_sms_inbox.jsonl")


def _read_all() -> list:
    if not os.path.isfile(SMS_INBOX_PATH):
        return []
    out = []
    with open(SMS_INBOX_PATH, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    out.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return out


def recent_sms(n: int = 5, reveal: bool = False) -> list:
    """Últimos N SMS, mais recentes primeiro. OTP MASCARADO por padrão também na
    via de BIBLIOTECA (o daemon importa esta função direto). `reveal=True` só devolve
    em claro com o gate humano aberto (reveal_allowed); senão mascara."""
    recs = _read_all()[-n:][::-1]
    if reveal and reveal_allowed():
        return recs
    return [mask_otp(r) for r in recs]


def last_sms(reveal: bool = False) -> dict:
    """Último SMS recebido. OTP MASCARADO por padrão também na via de BIBLIOTECA —
    antes, last_sms() de biblioteca vazava o código 2FA cru (a máscara só existia no
    CLI). `reveal=True` só revela com o gate humano aberto (reveal_allowed)."""
    allm = _read_all()
    if not allm:
        return {"message": "nenhum SMS recebido ainda"}
    rec = allm[-1]
    if reveal and reveal_allowed():
        return rec
    return mask_otp(rec)


def last_code(reveal: bool = False) -> dict:
    """Retorna o SMS mais recente que contém um código de verificação (4-8 dígitos).

    Por padrão o OTP vem MASCARADO. `reveal=True` só devolve em claro se o gate humano
    estiver aberto (reveal_allowed()); caso contrário mascara mesmo com reveal=True.
    """
    for rec in reversed(_read_all()):
        if rec.get("verification_code"):
            out = {
                "verification_code": rec["verification_code"],
                "from": rec.get("from"),
                "text": rec.get("text"),
                "received_at": rec.get("received_at"),
            }
            if reveal and reveal_allowed():
                return out
            return mask_otp(out)
    return {"message": "nenhum código de verificação recebido ainda"}


def _cli():
    # --reveal disponível em todos os subcomandos (antes ou depois do subcomando).
    reveal_parent = argparse.ArgumentParser(add_help=False)
    reveal_parent.add_argument(
        "--reveal", action="store_true",
        help="revela o OTP em claro (exige HERMES_ALLOW_EXECUTE=true e "
             "TELNYX_VOICE_SMS_ENABLED=true; senão continua mascarado)")

    p = argparse.ArgumentParser(description="Ler inbox de SMS recebidos (Hermes)",
                                parents=[reveal_parent])
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("last", parents=[reveal_parent])
    r = sub.add_parser("recent", parents=[reveal_parent])
    r.add_argument("--n", type=int, default=5)
    sub.add_parser("code", parents=[reveal_parent])

    args = p.parse_args()
    reveal = bool(args.reveal) and reveal_allowed()

    # As funções de biblioteca já mascaram por padrão e só revelam com o gate
    # aberto — o CLI delega a elas (fonte única), sem re-mascarar.
    if args.cmd == "last":
        out = last_sms(reveal=bool(args.reveal))
    elif args.cmd == "recent":
        out = recent_sms(args.n, reveal=bool(args.reveal))
    elif args.cmd == "code":
        out = last_code(reveal=bool(args.reveal))

    if args.reveal and not reveal and isinstance(out, dict):
        out = dict(out)
        out["_reveal"] = "negado: gate fechado (HERMES_ALLOW_EXECUTE + TELNYX_VOICE_SMS_ENABLED)"

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
