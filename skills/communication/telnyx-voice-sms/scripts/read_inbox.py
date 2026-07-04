"""
read_inbox.py — Lê os SMS recebidos (gravados pelo webhook_server.py).

Uso como biblioteca:
    from read_inbox import last_sms, recent_sms, last_code

Uso como CLI:
    python read_inbox.py last          # último SMS recebido
    python read_inbox.py recent --n 5  # últimos N
    python read_inbox.py code          # último código de verificação (OTP) detectado

Env:
    SMS_INBOX_PATH  (opcional, padrão /opt/data/telnyx_sms_inbox.jsonl —
                     precisa bater com o valor usado no webhook_server.py)
"""

import argparse
import json
import os

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


def recent_sms(n: int = 5) -> list:
    return _read_all()[-n:][::-1]  # mais recentes primeiro


def last_sms() -> dict:
    allm = _read_all()
    return allm[-1] if allm else {"message": "nenhum SMS recebido ainda"}


def last_code() -> dict:
    """Retorna o SMS mais recente que contém um código de verificação (4-8 dígitos)."""
    for rec in reversed(_read_all()):
        if rec.get("verification_code"):
            return {
                "verification_code": rec["verification_code"],
                "from": rec.get("from"),
                "text": rec.get("text"),
                "received_at": rec.get("received_at"),
            }
    return {"message": "nenhum código de verificação recebido ainda"}


def _cli():
    p = argparse.ArgumentParser(description="Ler inbox de SMS recebidos (Hermes)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("last")
    r = sub.add_parser("recent")
    r.add_argument("--n", type=int, default=5)
    sub.add_parser("code")

    args = p.parse_args()
    if args.cmd == "last":
        out = last_sms()
    elif args.cmd == "recent":
        out = recent_sms(args.n)
    elif args.cmd == "code":
        out = last_code()
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
