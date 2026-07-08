---
name: ask-vps-hermes
description: "Delega uma CONSULTA DE LEITURA para o Hermes que roda 24/7 na VPS da Axtro (o Hermes principal, com Google Workspace, Telnyx). Ponte read-only com allowlist, anti-injeção e gate de dry-run — nunca relaya instrução de ação."
version: 1.1.0
author: Hermes Agent (Axtro)
license: MIT
platforms: [macos, linux]
dependencies: [requests>=2.31.0]
metadata:
  hermes:
    tags: [Axtro, VPS, Bridge, Delegation]
---

# Perguntar/Delegar para o Hermes da VPS

Esta máquina (Mac local) roda uma instância separada do Hermes, focada nas skills que só
funcionam em macOS (Apple Notes, Reminders, FindMy, iMessage). Para qualquer coisa que
dependa das integrações que só existem na VPS — Google Workspace (Gmail/Drive/Docs/Sheets/
Slides/Calendar), Telnyx (SMS/ligação), ou apenas para consultar o estado/memória do agente
principal — use esta skill em vez de tentar fazer localmente.

## ⚠️ Ponte de leitura, não de ação (P0)

Esta ponte é **P0-crítica**: o Hermes da VPS detém Google Workspace + Telnyx, e o
Hermes **local** processa conteúdo NÃO-confiável (Telegram/emails). Por isso a ponte
**só repassa CONSULTA DE LEITURA** — nunca instrução de ação. Toda decisão de segurança
mora em `scripts/_relay_policy.py` (módulo puro e testável):

- **Allowlist de `task_type`**: só `consultar`, `resumir`, `status`. Qualquer outro → BLOQUEADO.
- **Sanitização**: remove chars de controle **e chars invisíveis/zero-width**
  (impede obfuscação tipo `en​vie email`) e trunca em 4000 chars.
- **Anti-injeção**: se a mensagem contém marker de ação/efeito real ("envie email",
  "mande sms", "ligue para", "compartilhe", "encaminhe/forward", "responda email",
  "conceda acesso/como editor", "pix", "disque", "delete", "transfira", "execute",
  "ignore previous", "system:", "user:") → BLOQUEADO, sem tocar na VPS. A consulta
  permitida ainda vai serializada como JSON dentro de uma fence, pra não forjar
  a estrutura do envelope via newline.
- **Envelope read-only**: a consulta permitida vai embrulhada num preâmbulo que instrui
  o lado VPS a NÃO executar nenhuma ação. Nunca há passthrough cru.
- **Gate de dry-run (default permanente)**: o POST real só acontece se, ao mesmo tempo,
  `--dry-run` não foi passado **e** `HERMES_ALLOW_EXECUTE=true` **e**
  `ASK_VPS_HERMES_ENABLED=true`. Falta qualquer uma → dry-run (retorna o envelope que
  mandaria, sem efeito). O `--dry-run` explícito sempre vence.

> Pedidos de **ação** (mandar email/SMS, ligar, compartilhar) **não** passam por esta ponte.
> Eles são um gate humano (ver `contract.json` → `human_gates`): o Hermes da VPS executa
> ação com os próprios gates dele, disparados por um humano — não por texto relayado.

## Quando usar

| O usuário diz algo como… | Ação |
|---|---|
| "o que o Hermes da VPS sabe sobre Y?" | Delega como **consulta de leitura** (`--task-type consultar`) |
| "me dá um resumo da minha caixa de entrada" | Delega como leitura (`--task-type resumir`) |
| "qual o status do agente principal?" | Delega como leitura (`--task-type status`) |
| "manda um email/SMS/liga pra X" | **NÃO** passa pela ponte — é gate humano na VPS |
| "cria uma nota/lembrete no meu Mac" | **NÃO delega** — usa skills locais (apple-notes, apple-reminders) |

## Como chamar

```bash
# dry-run (default seguro) — só monta e mostra o envelope, não chama a VPS
python scripts/ask_vps.py --task-type consultar "quantos emails não lidos eu tenho?"

# execução real (staging) — exige as DUAS envs setadas via cofre:
#   HERMES_ALLOW_EXECUTE=true e ASK_VPS_HERMES_ENABLED=true
python scripts/ask_vps.py --task-type resumir --execute "resumo da minha agenda de hoje"
```

## Autenticação

Lê `HERMES_VPS_API_SERVER_KEY` do ambiente (injetado pelo cofre — Doppler). É o mesmo segredo
que autentica tanto no Caddy (camada de borda) quanto no próprio servidor de API do Hermes da
VPS — um segredo, duas camadas de verificação.

## Limitações importantes

- Isso é **pergunta/resposta síncrona de leitura** — manda a consulta, espera a resposta
  completa. Não é "dispara e esquece", e **não é canal de ação**.
- O Hermes da VPS responde a consulta com **as próprias credenciais e gates dele** — esta
  skill não dá nenhum atalho de permissão; e mais: ela filtra o que chega até lá, embrulhando
  tudo num envelope read-only.
- Esta é a direção **fácil** da ponte (Local pedindo pra VPS). A direção contrária (VPS
  pedindo pro Local) não existe ainda — precisaria expor esta máquina publicamente via um
  túnel, o que é uma decisão de segurança separada, ainda não tomada.

## Segurança / testes

- Contrato: `contract.json` (`enabled=false`, `production_ready=false`, `autonomy_ring=2`,
  `human_gates` para ação de efeito real).
- Decisão pura e testável: `scripts/_relay_policy.py` (só stdlib, sem rede/segredo).
- Testes sem rede (rodam no python3 do sistema):

  ```bash
  python3 -m unittest discover -s tests -v
  ```
