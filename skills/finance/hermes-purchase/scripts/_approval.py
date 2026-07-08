#!/usr/bin/env python3
"""_approval.py — Lógica PURA de enforcement do gate humano de compra.

Este módulo NÃO importa nada externo (só stdlib: secrets, hashlib, hmac).
Roda no python3 do sistema (3.9.6) sem rede, sem credencial, sem efeito colateral.
Toda a decisão de segurança do `confirm` (e do gate de notificação do `request`)
vive aqui, isolada da função que escreve no ledger / manda Telegram — para que os
testes exercitem SÓ funções puras.

Modelo de ameaça que este módulo fecha (P0):
  O daemon Hermes chama o MESMO CLI para `request` e `confirm`. Antes, um `confirm
  --status aprovada` bastava para o daemon se auto-aprovar e liberar o teto mensal.
  Agora, confirmar de verdade exige DOIS segredos que o daemon não possui:
    1. o approval-token em texto — que só foi entregue no Telegram do dono
       (o daemon só vê o HASH sha256 gravado no ledger, nunca o token cru);
    2. a env HERMES_PURCHASE_ALLOW_CONFIRM=true — que vive FORA do ambiente do
       daemon (é ligada só na sessão humana que aprova).
  Sem os dois + o gate padrão de execução, `confirm` recusa ou vira dry-run.
"""
from __future__ import annotations

import hashlib
import hmac
import math
import secrets

# --- Nomes de env (só nomes; valores nunca ficam no código) -----------------
ENV_GLOBAL_EXECUTE = "HERMES_ALLOW_EXECUTE"          # gate global do daemon
ENV_SKILL_ENABLED = "HERMES_PURCHASE_ENABLED"        # habilita o lado request/notify
ENV_ALLOW_CONFIRM = "HERMES_PURCHASE_ALLOW_CONFIRM"  # human-only: habilita o confirm


# --- Token: gerar / derivar hash / verificar em tempo constante --------------
def generate_token() -> str:
    """Token de aprovação aleatório. Vai SÓ para o canal humano (Telegram)."""
    return secrets.token_urlsafe(16)


def hash_token(token: str) -> str:
    """sha256 hex do token. É isto (e só isto) que pode ser gravado/logado."""
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def verify_token(provided, stored_hash) -> bool:
    """True só se sha256(provided) casar com stored_hash (comparação constante)."""
    if not provided or not stored_hash:
        return False
    computed = hash_token(provided)
    return hmac.compare_digest(computed, stored_hash)


def hash_prefix(stored_hash, n: int = 12) -> str:
    """Prefixo do hash para correlação em auditoria — nunca revela o token."""
    return (stored_hash or "")[:n]


def mask_token(_token) -> str:
    """Qualquer token, mascarado. Usado se algum caminho precisar 'mostrar' o token."""
    return "[REDIGIDO]"


# --- Leitura de env como booleano estrito ------------------------------------
def _is_true(env, name: str) -> bool:
    try:
        return str(env.get(name, "")).strip().lower() == "true"
    except AttributeError:
        return False


def global_execute_allowed(env) -> bool:
    return _is_true(env, ENV_GLOBAL_EXECUTE)


def skill_enabled(env) -> bool:
    return _is_true(env, ENV_SKILL_ENABLED)


def confirm_env_allowed(env) -> bool:
    return _is_true(env, ENV_ALLOW_CONFIRM)


# --- Decisões puras ----------------------------------------------------------
# Vocabulário de decisão:
#   CONFIRMAR               -> pode escrever a mudança real de status (gasto conta)
#   DRY_RUN                 -> preview seguro, nenhum efeito, exit 0
#   RECUSADA_SEM_TOKEN      -> token ausente (ex.: daemon tentando auto-aprovar)
#   RECUSADA_TOKEN_INVALIDO -> token não confere com o hash do ledger
#   RECUSADA_SEM_ENV_HUMANA -> token ok mas HERMES_PURCHASE_ALLOW_CONFIRM ausente

def decide_confirm(provided_token, stored_hash, env, dry_run_flag: bool) -> dict:
    """Decide, sem tocar em nada, o que o `confirm` PODE fazer.

    Ordem (fail-closed):
      0. --dry-run explícito SEMPRE vence -> DRY_RUN (o humano força o modo seguro).
      1. token ausente            -> RECUSADA_SEM_TOKEN (exit 3)
      2. token não confere        -> RECUSADA_TOKEN_INVALIDO (exit 3)
      3. sem env humana           -> RECUSADA_SEM_ENV_HUMANA (exit 4)
      4. sem HERMES_ALLOW_EXECUTE -> DRY_RUN (gate padrão de execução, sem efeito)
      5. tudo ok                  -> CONFIRMAR
    """
    if dry_run_flag:
        return {
            "decision": "DRY_RUN", "dry_run": True, "exit_code": 0,
            "reason": "flag --dry-run: modo seguro forçado pelo humano; nada foi alterado",
        }
    if not provided_token:
        return {
            "decision": "RECUSADA_SEM_TOKEN", "dry_run": False, "exit_code": 3,
            "reason": "approval-token ausente — o daemon não pode auto-aprovar",
        }
    if not verify_token(provided_token, stored_hash):
        return {
            "decision": "RECUSADA_TOKEN_INVALIDO", "dry_run": False, "exit_code": 3,
            "reason": "approval-token não confere com o hash gravado no ledger",
        }
    if not confirm_env_allowed(env):
        return {
            "decision": "RECUSADA_SEM_ENV_HUMANA", "dry_run": False, "exit_code": 4,
            "reason": ("{} != true — env humana ausente; confirm recusa mesmo com token "
                       "certo (a env vive fora do ambiente do daemon)").format(ENV_ALLOW_CONFIRM),
        }
    if not global_execute_allowed(env):
        return {
            "decision": "DRY_RUN", "dry_run": True, "exit_code": 0,
            "reason": "{} != true — gate padrão de execução fechado; dry-run, nada foi alterado".format(
                ENV_GLOBAL_EXECUTE),
        }
    return {
        "decision": "CONFIRMAR", "dry_run": False, "exit_code": 0,
        "reason": "approval-token válido + env humana + gate de execução — confirmação real",
    }


def would_exceed_monthly_cap(entries, target_id, month, amount, cap) -> bool:
    """Fail-closed: True se aprovar/pagar esta entrada estouraria o teto mensal.

    O teto mensal era checado SÓ no `request`, e pendentes não consomem teto. Logo,
    vários pendentes (cada um <= per_purchase_cap) passavam no request e depois eram
    aprovados um a um SEM nenhuma re-checagem — furando o monthly_cap. Esta função
    torna o teto REALMENTE vinculante no momento da aprovação (o momento que importa).

    Soma o que já está 'aprovada'/'paga' no mês, EXCLUINDO a própria entrada (para ser
    idempotente numa re-confirmação aprovada->paga), e adiciona o valor desta. Qualquer
    valor/cap não-finito ou não-numérico -> True (recusa, fail-closed).
    """
    try:
        cap_f = float(cap)
    except (TypeError, ValueError):
        return True
    if not math.isfinite(cap_f):
        return True
    total = 0.0
    for e in entries:
        if e.get("id") == target_id:
            continue
        if e.get("month") == month and e.get("status") in ("aprovada", "paga"):
            try:
                a = float(e.get("amount", 0))
            except (TypeError, ValueError):
                continue
            if math.isfinite(a):
                total += a
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return True
    if not math.isfinite(amt):
        return True
    return (total + amt) > cap_f + 1e-9


def decide_notify(env, dry_run_flag: bool, notify_flag: bool) -> dict:
    """Gate padrão de execução para a entrega REAL do token no Telegram (request).

    Envio real do token SÓ acontece se TODAS forem verdadeiras:
      (a) --notify pedido, (b) NÃO --dry-run,
      (c) HERMES_ALLOW_EXECUTE == true, (d) HERMES_PURCHASE_ENABLED == true.
    Falta qualquer uma -> não envia; o token não é exposto em lugar nenhum.
    """
    if not notify_flag:
        return {"send": False, "reason": "sem --notify: nada enviado"}
    if dry_run_flag:
        return {"send": False, "reason": "flag --dry-run: nada enviado"}
    if not global_execute_allowed(env):
        return {"send": False, "reason": "{} != true: nada enviado".format(ENV_GLOBAL_EXECUTE)}
    if not skill_enabled(env):
        return {"send": False, "reason": "{} != true: nada enviado".format(ENV_SKILL_ENABLED)}
    return {"send": True, "reason": "gates abertos: token entregue ao canal humano"}


# --- Construção das mensagens (pura; garante que o token NÃO vaza p/ o daemon) -
def build_messages(pid, vendor, amount, reason, spent, remaining, token):
    """Devolve (daemon_message, human_message).

    daemon_message: o que vai para o stdout (que o DAEMON vê) — SEM o token.
    human_message:  o que vai SÓ para o Telegram do dono — COM o token e a linha
                    'Para aprovar, rode: confirm --id X --approval-token <TOKEN>'.
    Invariante testável: o token nunca aparece em daemon_message.
    """
    daemon_message = (
        "🧾 Pedido de compra (aprovação HUMANA necessária)\n"
        "ID: {id}\n"
        "Fornecedor: {vendor}\n"
        "Valor: R$ {amount:.2f}\n"
        "Motivo: {reason}\n"
        "Teto do mês: R$ {spent:.2f} usados · R$ {rem:.2f} restantes\n"
        "O approval-token foi entregue SÓ no canal humano (Telegram). O daemon não o vê.\n"
        "Nada foi cobrado — a compra é ato humano."
    ).format(id=pid, vendor=vendor, amount=amount, reason=reason, spent=spent, rem=remaining)

    human_message = (
        "🧾 *Pedido de compra* (aprovação necessária)\n"
        "ID: {id}\n"
        "Fornecedor: {vendor}\n"
        "Valor: R$ {amount:.2f}\n"
        "Motivo: {reason}\n"
        "Teto do mês: R$ {spent:.2f} usados · R$ {rem:.2f} restantes\n\n"
        "Para aprovar, rode (na SUA sessão, com {env}=true):\n"
        "  confirm --id {id} --approval-token {token}\n\n"
        "Esse token só existe aqui no seu Telegram. Não aprove nada que você não pediu."
    ).format(id=pid, vendor=vendor, amount=amount, reason=reason, spent=spent,
             rem=remaining, token=token, env=ENV_ALLOW_CONFIRM)

    return daemon_message, human_message
