#!/usr/bin/env python3
"""telegram_send.py — Entrega mensagens no Telegram via bot da Axtro.

Usa o TELEGRAM_BOT_TOKEN e TELEGRAM_ALLOWED_USERS já presentes no .env do
hermes-agent. Só stdlib (urllib). Divide mensagens acima de 4096 chars.

Uso como CLI:
    echo "texto" | python scripts/telegram_send.py
    python scripts/telegram_send.py --text "oi" --chat-id 123

Como biblioteca:
    from telegram_send import send
    send("mensagem")
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import List, Optional

import common

TELEGRAM_LIMIT = 4096


def _chunks(text: str, size: int = TELEGRAM_LIMIT) -> List[str]:
    if len(text) <= size:
        return [text]
    out = []
    remaining = text
    while remaining:
        if len(remaining) <= size:
            out.append(remaining)
            break
        # tenta quebrar numa quebra de linha antes do limite
        cut = remaining.rfind("\n", 0, size)
        if cut < size // 2:
            cut = size
        out.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    return out


def _default_chat_id(env) -> Optional[str]:
    raw = env.get("TELEGRAM_ALLOWED_USERS", "").strip()
    if not raw:
        return None
    # aceita "123" ou "123,456" — usa o primeiro
    first = raw.replace(";", ",").split(",")[0].strip()
    return first or None


def send(text: str, chat_id: Optional[str] = None, env=None, disable_preview: bool = True) -> dict:
    env = env or common.load_env()
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN ausente no .env"}
    chat_id = chat_id or _default_chat_id(env)
    if not chat_id:
        return {"ok": False, "error": "chat_id ausente (TELEGRAM_ALLOWED_USERS vazio)"}

    url = "https://api.telegram.org/bot{}/sendMessage".format(token)
    results = []
    for part in _chunks(text):
        payload = json.dumps({
            "chat_id": chat_id,
            "text": part,
            "disable_web_page_preview": disable_preview,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                results.append({"ok": body.get("ok", False)})
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            return {"ok": False, "error": "HTTP {}: {}".format(e.code, detail[:300])}
        except (urllib.error.URLError, OSError) as e:
            return {"ok": False, "error": "rede: {}".format(e)}
        time.sleep(0.3)  # respeita rate-limit do Telegram entre chunks
    return {"ok": all(r["ok"] for r in results), "parts": len(results)}


def main():
    parser = argparse.ArgumentParser(description="Enviar mensagem no Telegram")
    parser.add_argument("--text", help="texto; se omitido, lê do stdin")
    parser.add_argument("--chat-id", help="override do chat_id")
    args = parser.parse_args()

    text = args.text if args.text is not None else sys.stdin.read()
    if not text.strip():
        common.emit({"ok": False, "error": "texto vazio"})
        sys.exit(1)
    result = send(text, chat_id=args.chat_id)
    common.emit(result)
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
