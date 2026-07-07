#!/usr/bin/env python3
"""briefing.py — Briefing da manhã consolidado da fábrica Axtro (Anel 0).

Orquestra scan.py + secrets_scan.py + deadlines.py, monta uma mensagem única
e entrega no Telegram. Opcionalmente passa por um modelo barato (OpenRouter)
para virar um texto mais humano + um insight cruzado entre projetos.

Uso:
    python scripts/briefing.py                 # monta e envia no Telegram
    python scripts/briefing.py --dry-run       # só imprime, não envia
    python scripts/briefing.py --llm           # narrativa via OpenRouter
    python scripts/briefing.py --stale-days 6 --window 14

Filosofia [SILENT]: se não há nada digno de nota, envia um "tudo tranquilo"
curto em vez de spam. 100% leitura — nunca escreve em repo nenhum.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import common
import telegram_send

SCRIPTS = Path(__file__).resolve().parent


def run_json(script: str, *args) -> dict:
    try:
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / script), *args],
            capture_output=True, text=True, timeout=180,
        )
        if out.stdout.strip():
            return json.loads(out.stdout)
    except (subprocess.SubprocessError, OSError, json.JSONDecodeError) as e:
        return {"_error": "{}: {}".format(script, e)}
    return {"_error": "{}: sem saída".format(script)}


FLAG_LABEL = {
    "parado": "⏸️ parado",
    "nao_commitado": "✏️ mudanças locais",
    "nao_pushado": "⬆️ não-pushado",
    "atras_do_remoto": "⬇️ atrás do remoto",
    "sem_upstream": "🔌 sem remoto",
}


def compose(scan: dict, secrets: dict, deadlines: dict, stale_days: int) -> str:
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    lines = ["☀️ *Briefing Axtro* — {}".format(now), ""]

    s = scan.get("summary", {})
    lines.append("🏭 {} repos · {} parados · {} não-pushados · {} c/ mudanças locais".format(
        s.get("total_repos", "?"), s.get("parados", 0),
        s.get("nao_pushados", 0), s.get("com_mudancas_locais", 0),
    ))
    lines.append("")

    # Projetos que pedem atenção (têm flags)
    atencao = [r for r in scan.get("repos", []) if r.get("flags")]
    if atencao:
        lines.append("⚠️ Precisam de atenção:")
        for r in atencao[:12]:
            flags = ", ".join(FLAG_LABEL.get(f, f) for f in r["flags"])
            dias = r.get("days_since_commit")
            dias_txt = " · {}d sem commit".format(int(dias)) if dias is not None else ""
            lines.append("  • {} ({}){}: {}".format(r["name"], r["branch"], dias_txt, flags))
        if len(atencao) > 12:
            lines.append("  … +{} outros".format(len(atencao) - 12))
        lines.append("")
    else:
        lines.append("✅ Nenhum repo com pendência de git.")
        lines.append("")

    # Prazos
    prazos = deadlines.get("prazos", [])
    if prazos:
        lines.append("📅 Prazos ({} vencidos):".format(deadlines.get("vencidos", 0)))
        for p in prazos[:8]:
            marker = "🔴" if p["status"] == "vencido" else "🟡"
            quando = "venceu há {}d".format(-p["days_left"]) if p["days_left"] < 0 else "em {}d".format(p["days_left"])
            lines.append("  {} {} ({}) — {}".format(marker, p["date"], quando, p["line"][:90]))
        lines.append("")

    # Segredos vazados — SEMPRE destaque se houver
    total_alertas = secrets.get("total_alertas", 0)
    if total_alertas:
        lines.append("🚨 *SEGREDO POSSIVELMENTE VAZADO* ({} alerta(s)):".format(total_alertas))
        for det in secrets.get("detalhes", [])[:6]:
            for f in det["findings"][:3]:
                lines.append("  • {} — {}:{} [{}] {}".format(
                    det["repo"], f["file"], f["line"], f["type"], f["masked"]))
        lines.append("  → revise e rode `git rm --cached` / rotacione a chave se confirmado.")
        lines.append("")

    # Erros de coleta (transparência: nunca finge que varreu tudo)
    for block, label in ((scan, "scan"), (secrets, "secrets"), (deadlines, "deadlines")):
        if block.get("_error"):
            lines.append("⚙️ falha em {}: {}".format(label, block["_error"]))

    nada_relevante = not atencao and not prazos and not total_alertas
    if nada_relevante:
        lines = ["☀️ *Briefing Axtro* — {}".format(now), "",
                 "✅ Tudo tranquilo. {} repos, nenhum parado, sem prazo batendo, sem segredo vazado.".format(
                     s.get("total_repos", "?"))]

    return "\n".join(lines)


def llm_polish(raw_message: str, scan: dict, env) -> str:
    """Passa os achados por um modelo barato p/ narrativa + insight cruzado."""
    api_key = env.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return raw_message
    model = env.get("AXTRO_BRIEFING_MODEL", "google/gemini-2.5-flash-lite")
    prompt = (
        "Você é o Hermes, orquestrador da software house Axtro AI. A partir dos dados "
        "mecânicos abaixo, escreva um briefing da manhã curto (máx 12 linhas), em PT-BR, "
        "tom direto de sócio técnico. Priorize o que precisa de ação hoje. Se houver um "
        "padrão cruzado entre projetos que compartilham stack, aponte em 1 linha. Não invente "
        "nada que não esteja nos dados.\n\nDADOS:\n" + json.dumps(scan, ensure_ascii=False)[:6000]
    )
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 500,
        "temperature": 0.4,
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=payload,
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
            "X-Title": "Axtro Factory Briefing",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            text = body["choices"][0]["message"]["content"].strip()
            return text + "\n\n— dados brutos —\n" + raw_message
    except (urllib.error.URLError, OSError, KeyError, json.JSONDecodeError):
        # Fallback silencioso: se o LLM falhar, entrega o mecânico. Nunca trava o briefing.
        return raw_message


def main():
    parser = argparse.ArgumentParser(description="Briefing da manhã Axtro")
    parser.add_argument("--dry-run", action="store_true", help="imprime, não envia")
    parser.add_argument("--llm", action="store_true", help="narrativa via OpenRouter")
    parser.add_argument("--stale-days", type=int, default=common.STALE_DAYS_DEFAULT)
    parser.add_argument("--window", type=int, default=14)
    args = parser.parse_args()

    scan = run_json("scan.py", "--stale-days", str(args.stale_days))
    secrets = run_json("secrets_scan.py")
    deadlines = run_json("deadlines.py", "--window", str(args.window))

    message = compose(scan, secrets, deadlines, args.stale_days)

    env = common.load_env()
    if args.llm:
        message = llm_polish(message, scan, env)

    if args.dry_run:
        print(message)
        return

    result = telegram_send.send(message, env=env)
    common.emit(result)
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
