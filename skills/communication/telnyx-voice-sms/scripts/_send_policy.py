"""
_send_policy.py — Lógica PURA de política do lado de ENVIO (SMS + ligação).

Só stdlib. NÃO importa requests nem toca a rede. Concentra TODA a decisão de
segurança de send_sms.py e make_call.py, para que a decisão possa ser testada no
python3 do sistema (3.9.6) sem dependências externas e sem risco de disparar nada.

Regra de ouro (GATE PADRÃO DE DRY-RUN):
    A ação REAL só acontece se, ao mesmo tempo:
      (a) --dry-run NÃO foi passado,
      (b) HERMES_ALLOW_EXECUTE == "true",
      (c) TELNYX_VOICE_SMS_ENABLED == "true",
      (d) o destino está na allowlist (default: só o próprio número), e
      (e) o teto diário de envios não foi atingido.
    Faltando qualquer condição -> dry-run/bloqueado, sem efeito real.
    O --dry-run explícito SEMPRE vence, mesmo com as duas envs setadas.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_NUMBER = "+16174505166"
DEFAULT_DAILY_CAP = 10
DEFAULT_LEDGER_PATH = "/opt/data/telnyx_send_ledger.jsonl"

# E.164: '+' seguido de dígito 1-9 e mais 6 a 14 dígitos.
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def is_valid_e164(number) -> bool:
    return bool(number) and bool(_E164_RE.match(str(number).strip()))


def _own_number(env=None) -> str:
    env = env if env is not None else os.environ
    return (env.get("TELNYX_NUMBER") or DEFAULT_NUMBER).strip()


def _load_recipient_allowlist(env=None):
    """Destinos permitidos. Sempre inclui o próprio número Telnyx; extras vêm de
    TELNYX_ALLOWED_RECIPIENTS (CSV de E.164). Sem a env, a allowlist é SÓ o próprio
    número — enviar para terceiro fica bloqueado até um humano ampliar a lista."""
    env = env if env is not None else os.environ
    allow = {_own_number(env)}
    for part in (env.get("TELNYX_ALLOWED_RECIPIENTS", "") or "").split(","):
        num = part.strip()
        if num:
            allow.add(num)
    return sorted(allow)


# Alias público (mesmo objeto), para chamadas fora do módulo.
load_recipient_allowlist = _load_recipient_allowlist


def evaluate_send(to, allowlist) -> dict:
    """Decide se o destino `to` pode receber. Fora da allowlist -> BLOQUEADO."""
    to_norm = ("" if to is None else str(to)).strip()
    if not to_norm:
        return {"decision": "BLOQUEADO", "to": to, "reason": "destino vazio"}
    if not is_valid_e164(to_norm):
        return {"decision": "BLOQUEADO", "to": to_norm, "reason": "destino não é E.164 válido"}
    if to_norm not in set(allowlist):
        return {"decision": "BLOQUEADO", "to": to_norm,
                "reason": "destino fora da allowlist (terceiro exige gate humano)"}
    return {"decision": "PERMITIDO", "to": to_norm, "reason": "destino na allowlist"}


def _daily_cap(env=None) -> int:
    env = env if env is not None else os.environ
    try:
        return int(env.get("TELNYX_DAILY_SEND_CAP", str(DEFAULT_DAILY_CAP)))
    except (TypeError, ValueError):
        return DEFAULT_DAILY_CAP


def _ledger_path(env=None) -> str:
    env = env if env is not None else os.environ
    return env.get("TELNYX_SEND_LEDGER_PATH", DEFAULT_LEDGER_PATH)


def check_daily_cap(ledger_path, cap, now=None) -> dict:
    """Conta os envios REAIS (sent=True) do dia corrente no ledger JSONL.

    within_cap=True significa que ainda cabe mais um envio hoje (count < cap).
    Arquivo ausente/linha inválida -> ignorado (count parcial, nunca levanta).
    """
    now = now or datetime.now(timezone.utc)
    today = now.strftime("%Y-%m-%d")
    count = 0
    p = Path(ledger_path)
    if p.exists():
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            lines = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(rec.get("at", "")).startswith(today) and rec.get("sent") is True:
                count += 1
    return {"count": count, "cap": cap, "within_cap": count < cap, "date": today}


def gate_allows_execution(dry_run_flag, env=None) -> bool:
    """True só se o gate padrão estiver 100% aberto para a ação real.

    --dry-run explícito (dry_run_flag=True) SEMPRE vence e devolve False.
    """
    if dry_run_flag:
        return False
    env = env if env is not None else os.environ
    if (env.get("HERMES_ALLOW_EXECUTE", "") or "").strip().lower() != "true":
        return False
    if (env.get("TELNYX_VOICE_SMS_ENABLED", "") or "").strip().lower() != "true":
        return False
    return True


def plan_action(action, to, dry_run, env=None, ledger_path=None, cap=None) -> dict:
    """Decisão COMPLETA e sem efeito colateral para send_sms/make_call.

    Retorna um plano com "execute" indicando se a ação real pode ocorrer. As funções
    que chamam a API só disparam a rede quando plan["execute"] é True.
    """
    env = env if env is not None else os.environ
    allowlist = _load_recipient_allowlist(env)
    decision = evaluate_send(to, allowlist)
    if cap is None:
        cap = _daily_cap(env)
    if ledger_path is None:
        ledger_path = _ledger_path(env)
    cap_status = check_daily_cap(ledger_path, cap)

    plan = {
        "action": action,
        "to": decision.get("to", to),
        "decision": decision["decision"],
        "reason": decision["reason"],
        "daily_cap": cap_status,
        "allowlist_size": len(allowlist),
        "sent": False,
        "execute": False,
        "dry_run": True,
        "blocked": False,
    }

    if decision["decision"] != "PERMITIDO":
        plan["blocked"] = True
        plan["dry_run"] = False
        return plan
    if not cap_status["within_cap"]:
        plan["blocked"] = True
        plan["dry_run"] = False
        plan["reason"] = "teto diário de {} envios atingido".format(cap)
        return plan
    if gate_allows_execution(dry_run, env):
        plan["execute"] = True
        plan["dry_run"] = False
    else:
        plan["dry_run"] = True
    return plan


def _mask_number(to) -> str:
    """Mascara o destino para logar no ledger sem gravar o número inteiro."""
    s = ("" if to is None else str(to)).strip()
    if len(s) <= 4:
        return "[REDIGIDO]"
    return "*" * (len(s) - 4) + s[-4:]


def record_send(ledger_path, action, to, now=None) -> dict:
    """Registra um envio REAL no ledger (append JSONL). Só deve ser chamado no
    caminho de execução real, nunca em dry-run/bloqueado."""
    now = now or datetime.now(timezone.utc)
    rec = {"at": now.isoformat(), "action": action, "to": _mask_number(to), "sent": True}
    p = Path(ledger_path)
    if p.parent and not p.parent.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec
