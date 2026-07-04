---
name: ask-vps-hermes
description: "Delega uma tarefa ou pergunta para o Hermes que roda 24/7 na VPS da Axtro (o Hermes principal, com Google Workspace, Telnyx, etc)."
version: 1.0.0
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

## Quando usar

| O usuário diz algo como… | Ação |
|---|---|
| "manda um email pra X" (via Google Workspace) | Delega pro Hermes da VPS |
| "manda um SMS/liga pra X" | Delega pro Hermes da VPS |
| "o que o Hermes da VPS sabe sobre Y?" | Delega pro Hermes da VPS |
| "cria uma nota/lembrete no meu Mac" | **NÃO delega** — usa as skills locais (apple-notes, apple-reminders) |

## Como chamar

```bash
python scripts/ask_vps.py "manda um email pra fulano@x.com avisando que a reunião foi remarcada"
```

## Autenticação

Lê `HERMES_VPS_API_SERVER_KEY` do ambiente (injetado pelo cofre — Doppler). É o mesmo segredo
que autentica tanto no Caddy (camada de borda) quanto no próprio servidor de API do Hermes da
VPS — um segredo, duas camadas de verificação.

## Limitações importantes

- Isso é **pergunta/resposta síncrona** — manda a tarefa, espera a resposta completa, não é
  "dispara e esquece". Para tarefas longas, pode demorar.
- O Hermes da VPS executa a tarefa com **as próprias credenciais e gates dele** — esta skill
  não dá nenhum atalho de permissão, só encaminha a solicitação.
- Esta é a direção **fácil** da ponte (Local pedindo pra VPS). A direção contrária (VPS
  pedindo pro Local) não existe ainda — precisaria expor esta máquina publicamente via um
  túnel, o que é uma decisão de segurança separada, ainda não tomada.
