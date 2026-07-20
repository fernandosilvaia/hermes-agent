---
name: telnyx-voice-sms
description: "Enviar/receber SMS e fazer ligações com TTS pelo número Telnyx da empresa (+1 617 450-5166)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
dependencies: [requests>=2.31.0, fastapi>=0.110.0, uvicorn>=0.29.0, pynacl>=1.5.0]
metadata:
  hermes:
    tags: [Telnyx, SMS, Voice, Telephony, Communication, OTP]
---

# Telnyx · Voz + SMS

Dá ao Hermes um telefone: enviar e **receber** SMS e fazer ligações com texto falado
(TTS) pelo número dedicado **+1 (617) 450-5166**. Construído do zero (o Hermes Agent não
tem integração nativa com Telnyx).

Três capacidades: **enviar SMS**, **receber SMS** (inclusive códigos de verificação de
cadastro) e **ligar** (versão simples com TTS; gancho para IA conversacional no futuro).

## Quando usar

| O usuário diz algo como… | Use |
|---|---|
| "manda um SMS pro número X avisando Y" | `send_sms.py --to +... --text "..." --execute` (só dispara com gate + allowlist) |
| "manda um SMS de teste pra você mesmo" | `send_sms.py --self --text "..." [--execute]` |
| "chegou algum SMS?" / "qual o último SMS?" | `read_inbox.py last` (OTP mascarado) |
| "qual foi o código de verificação que chegou?" | `read_inbox.py code` (mascarado; `--reveal` só com gate) |
| "liga pro meu número e fala tal coisa" | `make_call.py --to +... --message "..." --execute` |
| "faz uma ligação de teste" | `make_call.py --self --message "..." [--execute]` |
| "liga pra Luiza/pro fornecedor e resolve X" (terceiro) | `request_call_approval.py --to +... --contact "..." --purpose "..."` (aprovação one-tap no Telegram, ver seção 5) |
| "que ligações você pediu essa semana?" | `request_call_approval.py --list --days 7` |

> **DRY-RUN é o padrão PERMANENTE.** `send_sms`/`make_call` só disparam de verdade se, ao
> mesmo tempo: (a) `--dry-run` **não** foi passado, (b) `HERMES_ALLOW_EXECUTE=true`,
> (c) `TELNYX_VOICE_SMS_ENABLED=true`, (d) o destino está na **allowlist** (default: só o
> próprio número) e (e) o teto diário não estourou. Faltando qualquer uma, a skill devolve o
> que **faria** (`"dry_run": true` ou `"blocked": true`) sem nenhum efeito real. `--dry-run`
> explícito sempre vence, mesmo com as envs setadas.

## Credenciais (lidas do ambiente, injetadas pelo cofre)

Nunca hardcoded, nunca logadas.

| Variável | Para quê | Obrigatória |
|---|---|---|
| `TELNYX_API_KEY` | autenticar na API Telnyx | sim |
| `TELNYX_NUMBER` | remetente `from` (padrão `+16174505166`) | não |
| `TELNYX_CONNECTION_ID` | ID da Call Control App (Voice) — só para ligar | só p/ voz |
| `TELNYX_PUBLIC_KEY` | validar assinatura dos webhooks (base64, do portal) | sim (webhook) |
| `TELNYX_INBOX_API_KEY` | token do `GET /sms/last` (Bearer). Sem ela o endpoint fica **fechado** (503) | sim (p/ /sms/last) |
| `TELNYX_WEBHOOK_URL` | URL pública do webhook de voz | recomendada |
| `TELNYX_MESSAGING_PROFILE_ID` | se o número não estiver num profile default | não |
| `TELNYX_ALLOWED_RECIPIENTS` | CSV E.164 de destinos permitidos além do próprio número | não |
| `HERMES_ALLOW_EXECUTE` | gate global: precisa ser `true` p/ qualquer envio/ligação real | p/ executar |
| `TELNYX_VOICE_SMS_ENABLED` | gate da skill: precisa ser `true` p/ envio/ligação real e p/ `--reveal` | p/ executar |
| `TELNYX_DAILY_SEND_CAP` | teto diário de envios/ligações reais (padrão `10`) | não |
| `SMS_INBOX_PATH` / `CALL_LOG_PATH` | onde gravar inbox/log (padrão `/opt/data/...`) | não |
| `TELNYX_SEND_LEDGER_PATH` | ledger de envios reais p/ o teto diário (padrão `/opt/data/...`) | não |

## 1. Enviar SMS

```bash
# DRY-RUN por padrão: mostra o que faria, não envia nada.
python scripts/send_sms.py --self --text "teste"
python scripts/send_sms.py --to +16174505166 --text "Olá do Hermes"

# Envio REAL (só com gate aberto + destino na allowlist + dentro do teto):
HERMES_ALLOW_EXECUTE=true TELNYX_VOICE_SMS_ENABLED=true \
  python scripts/send_sms.py --self --text "teste" --execute
```

Destino fora da allowlist (default: só o próprio número) volta `"blocked": true` — mesmo com
`--execute` e as duas envs setadas. Para enviar a terceiros, um humano precisa adicioná-los a
`TELNYX_ALLOWED_RECIPIENTS` (gate humano). `make_call.py` segue exatamente as mesmas regras.

## 2. Receber SMS (webhook) — o caso de uso mais importante agora

A Telnyx entrega SMS recebido via webhook (`message.received`). O `webhook_server.py` é um
processo FastAPI separado que:

1. **Valida a assinatura Ed25519** de toda requisição (headers `telnyx-signature-ed25519`
   + `telnyx-timestamp`; string assinada = `"<timestamp>|<corpo cru>"`), rejeitando
   requisições forjadas e timestamps velhos (anti-replay).
2. Extrai o texto e grava em `SMS_INBOX_PATH` (JSONL). Se detecta um número de 4–8 dígitos,
   guarda também como `verification_code` (conveniência para OTP de cadastro).

### Subir o servidor

```bash
uvicorn webhook_server:app --host 0.0.0.0 --port 8080
# (rode a partir da pasta scripts/ ou ajuste o import path)
```

Ele espera ser exposto **atrás do seu Caddy (HTTPS)** já configurado, em algo como:

```
https://SEU-DOMINIO/webhooks/telnyx/sms     → recebimento de SMS
https://SEU-DOMINIO/webhooks/telnyx/voice   → eventos de ligação
```

No portal Telnyx, configure essas URLs no Messaging Profile (SMS) e na Call Control
Application (voz). A skill **não** configura o Caddy — só documenta o que espera.

### Ler o que chegou

```bash
python scripts/read_inbox.py last              # último SMS (OTP mascarado)
python scripts/read_inbox.py recent --n 5      # (OTP mascarado)
python scripts/read_inbox.py code              # último código detectado (mascarado)
python scripts/read_inbox.py code --reveal     # revela o OTP SÓ com o gate aberto
```

**OTP nunca sai em claro por padrão.** `last`, `recent` e `code` mascaram o código de
verificação (mostram só os 2 últimos dígitos). `--reveal` só revela em claro se
`HERMES_ALLOW_EXECUTE=true` **e** `TELNYX_VOICE_SMS_ENABLED=true`; sem isso, continua
mascarado.

O endpoint HTTP `GET /sms/last` exige `Authorization: Bearer <TELNYX_INBOX_API_KEY>` — sem a
env, responde **503** (nunca abre sem auth); token errado, **401** — e sempre devolve o OTP
mascarado. O arquivo local (`/opt/data/...`) pode manter o código cru; a resposta pela rede
nunca.

> **Nota de uso legítimo:** receber SMS neste número serve para o próprio Hermes validar
> cadastros de contas/serviços da empresa (o número é da empresa, o uso é a identidade do
> próprio agente). Não use para receber códigos de contas de terceiros.

## 3. Ligar (TTS simples)

Fluxo Call Control (orientado a webhook):

1. `make_call.py` dispara o DIAL e embute a mensagem no `client_state` (base64).
2. Telnyx envia `call.answered` → o `webhook_server.py` emite o comando `speak` (TTS
   `pt-BR`) com essa mensagem.
3. AMD `premium` distingue humano de caixa postal (evento `call.machine.detection.ended`).

```bash
python scripts/make_call.py --to +16174505166 --message "Olá, teste do Hermes"
python scripts/make_call.py --self --message "teste"
```

O `webhook_server.py` loga `call.initiated`, `call.answered`, `call.hangup` e o resultado do
AMD em `CALL_LOG_PATH`. Há um **gancho comentado** onde entraria o ElevenLabs Conversational
AI numa versão futura (conversa por IA em tempo real, como no Billion CRM) — não implementado
agora.

## 4. Ligar para TERCEIRO com aprovação one-tap no Telegram

Regra do Fernando: "no máximo um pedido no telegram". Para ligar para um
membro do time ou uma empresa (fora da allowlist fixa), o agente NÃO abre um
gate interativo de terminal: ele cria um pedido persistente e manda UMA
mensagem ao dono no canal home do Telegram, com botões inline
**Aprovar e ligar** / **Rejeitar**.

```bash
python scripts/request_call_approval.py \
  --to +14075551234 \
  --contact "Luiza (Techmax)" \
  --purpose "Confirmar a visita técnica de amanhã às 9h" \
  --message "Bom dia, Luiza. Confirmando a visita técnica de amanhã às 9h."
```

Fluxo completo:

1. O script grava o pedido (id `crXXXXXXXX`, status `pending`) em
   `$HERMES_HOME/telnyx_voice_sms/call_approvals.json` e envia a mensagem de
   aprovação (contato + número + motivo + prazo) via Bot API, com
   `callback_data` `callreq:a:<id>` / `callreq:r:<id>`. Depois fica
   esperando a decisão (poll no store).
2. O tap do botão chega no gateway
   (`plugins/platforms/telegram/adapter.py::_handle_call_request_callback`),
   que autoriza o usuário (mesma trilha dos botões de exec approval) e roda
   `scripts/decide_call_request.py`, que SÓ grava a decisão (atômica e
   idempotente). O gateway nunca disca.
3. Aprovado: o processo que estava esperando dispara a ligação NA HORA via
   `_call_approval_flow.execute_approved_call()` -> `make_call()`. O número
   aprovado entra na allowlist SÓ desta chamada (overlay de env, mesmo
   padrão do fluxo tenant). Rejeitado ou prazo estourado (default 15 min,
   `TELNYX_CALL_APPROVAL_TIMEOUT_SECONDS`): nada é discado, e o agente
   recebe o resultado.

Garantias (todas testadas em `tests/`):

- **Sem aprovação não há discagem.** Pedido `pending`/`rejected`/`expired`
  nunca chega no `make_call`; tap depois do prazo vira `expired`, nunca
  aprova.
- **Uma aprovação = no máximo UMA ligação.** Claim atômico de uso único;
  double-tap, callback repetido ou retry não rediscam.
- **Os trilhos existentes continuam valendo.** `HERMES_ALLOW_EXECUTE`,
  `TELNYX_VOICE_SMS_ENABLED`, teto diário e E.164 são checados por cima da
  aprovação.
- **Toda ligação se identifica como IA.** O TTS começa SEMPRE com o prefixo
  de identificação (assistente de IA da Axtro em nome do Fernando) antes do
  conteúdo; `TELNYX_AI_DISCLOSURE_TEXT` troca o texto, mas não desliga.
- **Auditável.** Cada transição (created/approved/rejected/expired/executed,
  com quem decidiu e quando) vai para
  `$HERMES_HOME/telnyx_voice_sms/call_approval_audit.jsonl`; a ligação
  executada registra o `call_control_id` amarrado ao id da aprovação.
  `--list --days 7` responde "que ligações você pediu essa semana".

| Variável | Para quê |
|---|---|
| `TELEGRAM_BOT_TOKEN` | mesmo bot do gateway (envio da mensagem de aprovação) |
| `TELEGRAM_HOME_CHANNEL` | chat id do dono (destino do pedido) |
| `TELEGRAM_HOME_CHANNEL_THREAD_ID` | opcional, tópico do canal home |
| `TELNYX_CALL_APPROVAL_CHAT_ID` | opcional, override do chat do pedido |
| `TELNYX_CALL_APPROVAL_TIMEOUT_SECONDS` | prazo de aprovação (default `900`) |
| `TELNYX_CALL_APPROVAL_STORE_PATH` / `TELNYX_CALL_APPROVAL_AUDIT_PATH` | overrides do store/audit |
| `TELNYX_CALL_APPROVAL_DECIDE_SCRIPT` | override do caminho do decide script (gateway) |
| `TELNYX_AI_DISCLOSURE_TEXT` | texto do prefixo de identificação de IA (nunca desliga) |

Modos extras: `--no-wait` (só cria e envia; conferir depois com
`--status <id>` e executar com `--execute <id>`), `--dry-run` (mostra o que
faria sem gravar nem enviar), `--list [--days N]` (auditoria).

## 5. Ligação TENANT-SCOPED (conta Telnyx do próprio cliente)

Tudo acima (`make_call.py`/`send_sms.py` sem `env`) usa SEMPRE a conta Telnyx
**interna da Axtro** (`TELNYX_API_KEY`/`TELNYX_NUMBER` globais deste processo) —
isso não muda em nada com o que segue.

Quando um cliente com sua PRÓPRIA conta Telnyx (um tenant com número dedicado,
provisionado em `org_integrations` no Control Tower) pede pro agente dele no
Telegram ligar pra alguém, o pedido vira um `hermes_job`
(`executor: "telnyx-call"`) no Control Tower — nunca uma chamada direta.
`consume_tenant_calls.py` é o consumidor DEDICADO desse tipo de job (não é o
MacBook Worker, que só sabe `claude-code`/`codex`/`shell`):

```bash
# Uma checagem por execução — rode via cron/systemd timer, não como daemon.
python scripts/consume_tenant_calls.py
python scripts/consume_tenant_calls.py --dry-run   # força modo seguro (teste manual)
```

Fluxo (ver docstring de `consume_tenant_calls.py` para o detalhe completo):

1. `GET /api/hermes/jobs/next?executors=telnyx-call` — só pega jobs deste tipo
   (nunca rouba um `claude-code`/`codex`/`shell` da fila compartilhada, e
   vice-versa: o MacBook Worker também nunca pega um `telnyx-call`).
2. `_tenant_call_policy.validate_job_gate()` reconfirma LOCALMENTE que o job
   já foi aprovado por um humano (`requires_human_gate=true` +
   `result.approved_by`) antes de gastar qualquer chamada de rede — nunca
   confia cego no que veio do Control Tower.
3. `POST /api/hermes/jobs/:id/telnyx-credential` resolve a credencial Telnyx
   DECIFRADA da conta PRÓPRIA do tenant. **Uso único**: a mesma chamada que
   resolve a credencial já marca o job como em execução — não dá pra reler a
   mesma credencial duas vezes pelo mesmo job.
4. `_tenant_call_policy.build_tenant_env()` monta um `env` NOVO, só pra esta
   chamada (nunca `os.environ` real): a credencial do tenant + allowlist
   restrita ao destino DESTE job + ledger de teto diário POR ORG. `make_call()`
   roda com esse `env`, **sem nenhuma alteração na lógica de decisão** — as
   mesmas travas de dry-run/allowlist/teto de `_send_policy.py` valem aqui.
5. `POST /api/hermes/jobs/:id/status` reporta o resultado.

**Gate padrão continua valendo** — o job já aprovado no Control Tower NÃO pula
o dry-run local: a ligação real só acontece com `HERMES_ALLOW_EXECUTE=true`
**E** `TENANT_TELNYX_CALLS_ENABLED=true` (flag PRÓPRIA deste fluxo — ligar
`TELNYX_VOICE_SMS_ENABLED`, o gate do uso interno da Axtro, não libera isso, e
vice-versa).

| Variável (ambiente REAL do consumidor) | Para quê |
|---|---|
| `HOUSE_API_URL` / `HOUSE_INGEST_TOKEN` | falar com o Control Tower (mesmo token do MacBook Worker/dispatch-job) |
| `TENANT_TELNYX_CALLS_ENABLED` | gate da ligação tenant-scoped (independente de `TELNYX_VOICE_SMS_ENABLED`) |
| `TENANT_TELNYX_LEDGER_DIR` | diretório dos ledgers de teto diário, um arquivo por org |
| `TENANT_TELNYX_DAILY_CALL_CAP` | teto diário por org (padrão `5`) |

Não muda em nada: `make_call.py`/`send_sms.py` chamados sem `env` (uso interno
da Axtro), o webhook `voice`/`sms` (`webhook_server.py`), nem os testes
existentes de `_send_policy.py`.

## Segurança e regras de negócio

- **Chave nunca hardcoded/logada** — sempre de `os.environ`. OTP/segredos nunca retornados em
  claro (mascarados: só 2 últimos dígitos, ou `[REDIGIDO]`).
- **Gate padrão de dry-run** (default permanente): envio/ligação real só com `--dry-run`
  ausente **E** `HERMES_ALLOW_EXECUTE=true` **E** `TELNYX_VOICE_SMS_ENABLED=true`. Toda a
  decisão (allowlist, domínio E.164, teto, gate) vive em módulos **puros** e testáveis
  (`scripts/_sms_policy.py`, `scripts/_send_policy.py`), sem rede.
- **Allowlist de destino**: default = só o próprio número (`TELNYX_NUMBER`). Terceiro =
  `blocked`, mesmo com o gate aberto — ampliar só via `TELNYX_ALLOWED_RECIPIENTS` (ato humano).
- **Teto diário** (`TELNYX_DAILY_SEND_CAP`, padrão 10) conta envios reais no ledger e bloqueia
  acima do cap.
- **`GET /sms/last` autenticado**: `Authorization: Bearer <TELNYX_INBOX_API_KEY>`. Sem a env →
  503 (fail-closed, nunca abre sem auth); token errado → 401; resposta sempre com OTP mascarado.
- **Assinatura do webhook validada** (Ed25519 + anti-replay). `TELNYX_VERIFY_SIGNATURE=false`
  existe só para debug local; **nunca** desligar em produção.
- **Idempotência**: webhooks podem chegar duplicados — use `data.id` se for agir sobre eles.
- ⚠️ **Ligações/SMS a terceiros**: para **números de teste próprios** é OK. **SMS a terceiro
  exige o destino na allowlist (`TELNYX_ALLOWED_RECIPIENTS`, ato humano). Ligação a terceiro
  exige aprovação one-tap POR LIGAÇÃO no Telegram (seção 4): um pedido, um toque em Aprovar,
  uma ligação no máximo.** Consentimento/TCPA continua sendo responsabilidade do Fernando
  ANTES de aprovar. O código impõe isso, não é só um comentário.
- **Identificação de IA obrigatória**: toda ligação TTS começa se identificando como
  assistente de IA da Axtro ligando em nome do Fernando, antes de qualquer conteúdo
  (`apply_ai_disclosure` em `make_call.py`; sem flag para desligar).

## Confirmar antes de ir pra produção

Os nomes de campos/eventos e o mecanismo de assinatura foram confirmados na doc atual da
Telnyx, mas APIs mudam — na hora de subir, revalide contra:
`https://developers.telnyx.com` (Messaging, Call Control e Webhooks).
