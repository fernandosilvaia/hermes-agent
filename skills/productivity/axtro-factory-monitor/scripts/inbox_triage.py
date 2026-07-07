#!/usr/bin/env python3
"""inbox_triage.py — Triagem de inbox (axtro@axtroai.com) · Anel 0.

Lista os emails não lidos recentes e classifica em urgente / spam / precisa_de_voce /
rotina. **Somente leitura** — nunca marca como lido, nunca responde, nunca arquiva/deleta.
Reusa a autenticação da skill google-workspace-axtro (Service Account + Domain-Wide
Delegation) e o entregador Telegram desta skill.

Uso:
    python scripts/inbox_triage.py                # classifica e entrega no Telegram
    python scripts/inbox_triage.py --dry-run       # só imprime, não envia
    python scripts/inbox_triage.py --max 30         # mais mensagens

Classificação 100% heurística, local — nunca via LLM externo. Metadados de email
(remetente/assunto) são dados privados da empresa/terceiros; mandar isso pra uma API
de terceiros (OpenRouter etc.) cruzaria a mesma linha que a regra de LGPD do CLAUDE.md
já proíbe para PII de cliente. Diferente do briefing.py (que só processa metadados de
git, não conteúdo privado de correspondência), esta skill fica só com heurística local.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import common
import telegram_send

GMAIL_SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent
    / "google-workspace-axtro" / "scripts"
)

# Marketing/spam de verdade: linguagem promocional explícita. NUNCA "noreply"/"no-reply"
# sozinho — isso também aparece em notificações legítimas de sistema (Drive, Calendar),
# como o caso real testado: "drive-shares-dm-noreply@google.com" partilhando uma pasta
# do time não é spam, é rotina de trabalho.
SPAM_HINTS = (
    "unsubscribe", "cancelar inscrição", "newsletter", "promo", "% off", "% de desconto",
    "webinar", "confira nossa oferta", "oferta imperdível", "cupom", "descadastr",
)
URGENT_HINTS = (
    "urgente", "urgent", "prazo", "asap", "action required", "resposta necessária",
    "vence hoje", "último dia", "vencimento",
)
# Notificação automatizada de sistema, legítima, sem ação necessária (calendário, Drive
# compartilhado, updates de acesso) — não é spam nem precisa de resposta.
ROTINA_HINTS = (
    "convite para", "invitation to", "shared calendar", "calendário compartilhado",
    "pasta compartilhada", "updated your access", "atualizou seu acesso",
    "drive-shares", "calendar-notification", "compartilhou um arquivo",
    "compartilhou uma pasta",
)


def _import_gmail():
    sys.path.insert(0, str(GMAIL_SCRIPTS))
    import gmail  # type: ignore
    return gmail


def classify_heuristic(msg: dict) -> str:
    frm = (msg.get("from") or "").lower()
    subj = (msg.get("subject") or "").lower()
    snippet = (msg.get("snippet") or "").lower()
    blob = " ".join((frm, subj, snippet))

    if any(h in blob for h in SPAM_HINTS):
        return "spam"
    if any(h in blob for h in URGENT_HINTS):
        return "urgente"
    if any(h in blob for h in ROTINA_HINTS):
        return "rotina"
    return "precisa_de_voce"  # default conservador: melhor triagem manual do que ignorar


CATEGORY_ORDER = ["urgente", "precisa_de_voce", "spam", "rotina"]
CATEGORY_LABEL = {
    "urgente": "🔴 Urgente", "precisa_de_voce": "🟡 Precisa de você",
    "spam": "⚪ Spam/marketing", "rotina": "🔵 Rotina",
}


def compose_message(by_category: dict, total: int) -> str:
    if total == 0:
        return "📬 Inbox: nenhum email não lido. Tudo em dia."

    lines = ["📬 *Triagem de inbox* — {} não lidos".format(total), ""]
    for cat in CATEGORY_ORDER:
        msgs = by_category.get(cat, [])
        if not msgs:
            continue
        lines.append("{} ({})".format(CATEGORY_LABEL[cat], len(msgs)))
        for m in msgs[:8]:
            frm = (m.get("from") or "?").split("<")[0].strip()[:30]
            subj = (m.get("subject") or "(sem assunto)")[:70]
            lines.append("  • {} — {}".format(frm, subj))
        if len(msgs) > 8:
            lines.append("  … +{} outros".format(len(msgs) - 8))
        lines.append("")
    lines.append("Nada foi marcado como lido, respondido ou arquivado — só leitura.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Triagem de inbox (Anel 0, somente leitura)")
    parser.add_argument("--max", type=int, default=20)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    env = common.load_env()
    if not env.get("GOOGLE_SERVICE_ACCOUNT_KEY_JSON"):
        common.emit({"ok": False, "error": "GOOGLE_SERVICE_ACCOUNT_KEY_JSON ausente — mirror do Doppler pendente"})
        sys.exit(1)
    # auth.py da skill google-workspace-axtro lê direto de os.environ (não de um .env
    # próprio) — injeta aqui o que foi carregado do .env do hermes-agent.
    os.environ.setdefault("GOOGLE_SERVICE_ACCOUNT_KEY_JSON", env["GOOGLE_SERVICE_ACCOUNT_KEY_JSON"])
    os.environ.setdefault("GOOGLE_IMPERSONATED_USER", env.get("GOOGLE_IMPERSONATED_USER", "axtro@axtroai.com"))

    try:
        gmail = _import_gmail()
        messages = gmail.list_recent(max_results=args.max, query="is:unread")
    except Exception as e:  # noqa: BLE001 — qualquer falha de auth/API vira erro reportado, nunca crash silencioso
        common.emit({"ok": False, "error": "falha ao ler Gmail: {}".format(str(e)[:300])})
        sys.exit(1)

    by_category = {c: [] for c in CATEGORY_ORDER}
    for m in messages:
        cat = classify_heuristic(m)
        by_category[cat].append(m)

    message = compose_message(by_category, len(messages))

    if args.dry_run:
        print(message)
        common.emit({"total": len(messages), "por_categoria": {k: len(v) for k, v in by_category.items()}})
        return

    result = telegram_send.send(message, env=env)
    common.emit({**result, "total": len(messages), "por_categoria": {k: len(v) for k, v in by_category.items()}})
    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
