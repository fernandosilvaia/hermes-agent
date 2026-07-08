---
name: hermes-purchase
description: "Guarda-corpo de compra: allowlist de fornecedor + teto mensal + livro-caixa + aprovação humana obrigatória por compra. NUNCA cobra sozinho — prepara o pedido para o humano aprovar."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
dependencies: []
metadata:
  hermes:
    tags: [Finance, Guardrail, HumanGate, Budget]
    related_skills: [axtro-factory-monitor]
---

# Hermes Purchase (guarda-corpo de gasto)

> 🚫 **Esta skill NUNCA cobra nada.** Ela não integra cartão, não abre checkout, não
> chama API de pagamento. Ela **decide se uma compra pode ser proposta** e **prepara o
> pedido de aprovação** para o humano. A cobrança em si é sempre ato humano. Isso segue
> a regra fixa da Axtro: *"Toda ação de gasto, mesmo com cartão de teto baixo, precisa de
> aprovação humana por compra"* e *"MVP preview antes de sistema completo (sem chave real)"*.

## O que ela garante

1. **Allowlist de fornecedor** — só fornecedores pré-aprovados no `config.json` passam.
2. **Teto por compra** (padrão R$ 300) e **teto mensal** (padrão R$ 500).
3. **Livro-caixa** (`ledger.jsonl`) — toda compra vira registro; só `aprovada`/`paga`
   consomem o teto do mês (pendentes não).
4. **Aprovação humana obrigatória** — o melhor que a skill devolve é `PODE_PERGUNTAR`,
   que é sinal verde para *pedir*, nunca para *gastar*.

## Configuração

```bash
cp config.example.json config.json   # depois edite allowlist/tetos
```

`config.json` fica fora do controle de versão (contém a política de gasto da empresa);
o `config.example.json` é o template versionado.

## Uso

```bash
# 1. Checar se uma compra é permitida (não registra nada)
python scripts/policy.py --vendor "OpenRouter" --amount 120
python scripts/policy.py --status                     # orçamento restante do mês

# 2. Preparar um pedido de aprovação (registra como 'pendente'; o approval-token
#    vai SÓ para o seu Telegram — o daemon nunca o vê no stdout)
python scripts/request_purchase.py request \
    --vendor "OpenRouter" --amount 120 \
    --reason "recarga do teto do briefing" --notify

# 3. Aprovar (ato HUMANO, fora do daemon). Exige o token que chegou no seu Telegram
#    E a env humana HERMES_PURCHASE_ALLOW_CONFIRM=true (que NÃO vive no ambiente do daemon):
HERMES_ALLOW_EXECUTE=true HERMES_PURCHASE_ALLOW_CONFIRM=true \
  python scripts/request_purchase.py confirm \
    --id 20260706-2130-a1b2 --status aprovada \
    --approval-token <TOKEN-QUE-CHEGOU-NO-TELEGRAM>

# preview seguro (nunca altera nada; --dry-run sempre vence):
python scripts/request_purchase.py confirm --id 20260706-2130-a1b2 --status aprovada --dry-run

# 4. Auditoria (list mascara o hash; toda tentativa também vira linha em audit.log)
python scripts/request_purchase.py list --month 2026-07
```

## Enforcement do gate humano (P0 fechado)

O `confirm` deixou de ser convenção e virou **enforcement real**. Confirmar de
verdade (o que libera o teto mensal) só acontece com **todos** estes ao mesmo tempo:

1. `--approval-token <TOKEN>` conferindo (`hmac.compare_digest`) com o **hash sha256**
   gravado no ledger. O token cru **só** foi entregue no Telegram do dono — o daemon
   vê apenas o hash, nunca o token, e o token nunca aparece no stdout.
2. Env humana `HERMES_PURCHASE_ALLOW_CONFIRM=true`, que deve viver **fora** do ambiente
   do daemon (é ligada só na sessão humana que aprova).
3. Gate padrão de execução: **sem** `--dry-run` + `HERMES_ALLOW_EXECUTE=true`.
   `--dry-run` explícito **sempre vence** (o humano pode forçar o modo seguro).

Falta qualquer segredo humano → **recusa** (exit ≠ 0) e a tentativa é logada. Assim o
daemon não consegue se auto-aprovar — nem se vazar o hash, porque precisa do token cru
(só no Telegram) **e** da env humana. Toda tentativa (sucesso, recusa ou dry-run) vira
linha append-only em `audit.log`, sempre sem o token cru (só prefixo do hash).

## Estados de uma compra no livro-caixa

| status | significa | conta no teto? |
|---|---|---|
| `pendente` | pedido criado, aguardando humano | não |
| `aprovada` | humano aprovou | sim |
| `paga` | pagamento confirmado | sim |
| `recusada` | humano recusou | não |

## Fronteira explícita (o que esta skill NÃO faz — de propósito)

- Não guarda nem usa dados do cartão (Conta Simples fica no Doppler, fora daqui).
- Não executa pagamento, não preenche checkout, não chama gateway.
- Não decide sozinha que "vale a pena" — só aplica limites e registra.

Quando/se um executor de pagamento real for construído no futuro, ele deve **consumir
esta skill como porta de entrada** (checar `policy.py` e exigir `confirm` humano antes),
nunca contorná-la. Critério de entrada desse executor: ver ROADMAP_CAPACIDADES
("Gasto acima do teto sem aprovação → Nunca").
