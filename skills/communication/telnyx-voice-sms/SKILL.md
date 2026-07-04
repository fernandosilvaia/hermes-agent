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
| "manda um SMS pro número X avisando Y" | `send_sms.py --to +... --text "..."` |
| "manda um SMS de teste pra você mesmo" | `send_sms.py --self --text "..."` |
| "chegou algum SMS?" / "qual o último SMS?" | `read_inbox.py last` |
| "qual foi o código de verificação que chegou?" | `read_inbox.py code` |
| "liga pro meu número e fala tal coisa" | `make_call.py --to +... --message "..."` |
| "faz uma ligação de teste" | `make_call.py --self --message "..."` |

## Credenciais (lidas do ambiente, injetadas pelo cofre)

Nunca hardcoded, nunca logadas.

| Variável | Para quê | Obrigatória |
|---|---|---|
| `TELNYX_API_KEY` | autenticar na API Telnyx | sim |
| `TELNYX_NUMBER` | remetente `from` (padrão `+16174505166`) | não |
| `TELNYX_CONNECTION_ID` | ID da Call Control App (Voice) — só para ligar | só p/ voz |
| `TELNYX_PUBLIC_KEY` | validar assinatura dos webhooks (base64, do portal) | sim (webhook) |
| `TELNYX_WEBHOOK_URL` | URL pública do webhook de voz | recomendada |
| `TELNYX_MESSAGING_PROFILE_ID` | se o número não estiver num profile default | não |
| `SMS_INBOX_PATH` / `CALL_LOG_PATH` | onde gravar inbox/log (padrão `/opt/data/...`) | não |

## 1. Enviar SMS

```bash
python scripts/send_sms.py --to +15551234567 --text "Olá do Hermes"
python scripts/send_sms.py --self --text "teste"     # valida o próprio número
```

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
python scripts/read_inbox.py last     # último SMS
python scripts/read_inbox.py recent --n 5
python scripts/read_inbox.py code     # último código de verificação detectado
```

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

## Segurança e regras de negócio

- **Chave nunca hardcoded/logada** — sempre de `os.environ`.
- **Assinatura do webhook validada** (Ed25519 + anti-replay). `TELNYX_VERIFY_SIGNATURE=false`
  existe só para debug local; **nunca** desligar em produção.
- **Idempotência**: webhooks podem chegar duplicados — use `data.id` se for agir sobre eles.
- ⚠️ **Ligações**: ligar para **números de teste próprios** é OK sem confirmação. **Qualquer
  campanha ou ligação para terceiros externos exige confirmação explícita do Fernando ANTES**
  (regra de negócio da empresa; consentimento/TCPA é responsabilidade dele antes de qualquer
  campanha). Respeite a política de aprovação manual do Hermes aqui.

## Confirmar antes de ir pra produção

Os nomes de campos/eventos e o mecanismo de assinatura foram confirmados na doc atual da
Telnyx, mas APIs mudam — na hora de subir, revalide contra:
`https://developers.telnyx.com` (Messaging, Call Control e Webhooks).
