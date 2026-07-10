# Hermes Autonomy Areas — quanto poder o Hermes tem em cada área

**Atualizado 2026-07-08.** Traduz cada área de negócio para a linguagem do
**Autonomy Core** (anéis 0–4 + classes de risco), dizendo o que roda sozinho e o
que exige gate humano. É a régua que o `skill_runner` aplica em runtime.

## Régua (do Autonomy Core)

**Anéis** — 0 observar/ler · 1 criar/editar arquivos·docs·testes · 2 executar skill
interna segura · 3 preparar mudança de produção (aprova antes de aplicar) · 4 execução
autônoma avançada (só se liberada no contrato).

**Classes de risco** — `safe` roda só · `medium_risk` roda só se tiver contrato+testes
· `high_risk` roda com preflight+log (máx staging) · `production_sensitive` exige gate
· `financial_sensitive` nunca gasta real sem aprovação · `external_communication` nunca
envia real sem aprovação.

**Gates (o humano seta FORA do daemon):** `HERMES_RING_GATE` (operacional, anel ≥2) ·
`HERMES_HUMAN_APPROVAL` (classes sensíveis) · **token fora-de-banda** (dinheiro, padrão
`hermes-purchase`) · `HERMES_KILL_SWITCH=on` para tudo.

---

## Matriz de autonomia por área

| Área | Anel típico | Classe dominante | Roda sozinho? | Gate principal |
|---|---|---|---|---|
| **Engineering** | 1–3 | medium → production_sensitive | sim p/ plano, inspeção, teste local | aprovação p/ merge/migration/deploy |
| **Voice AI** | 2 | external_communication (+financial) | só análise de transcrição | aprovação p/ **toda** ligação/SMS real |
| **SDR & Sales** | 0–2 | safe/medium (external ao enviar) | sim p/ score, rota, rascunho | aprovação p/ enviar/convidar/link de pagamento |
| **CRM** | 1–2 | medium (external ao contatar) | sim p/ classificar, base interna | aprovação p/ mensagem ao cliente / delete |
| **Marketing** | 1 | safe/medium (external+financial ao publicar) | sim p/ criar rascunho/criativo/análise | aprovação p/ publicar + gastar mídia |
| **Finance** | 3 | **financial_sensitive** | só leitura/resumo | **token fora-de-banda** p/ qualquer gasto/cobrança |
| **Operations** | 0–2 | medium → production_sensitive | sim p/ auditoria/monitor/consulta | aprovação p/ registry/dispatch/provisão de acesso |
| **Documentation** | 1–2 | safe/medium (external ao entregar) | sim p/ gerar doc/treino/deck interno | aprovação p/ entregar/compartilhar externo |
| **Browser Automation** | 2 | high_risk | sim p/ QA em staging/demos | aprovação p/ agir em produção/sistema de cliente |
| **Monitoring & Reports** | 0 | **safe** | **sim, quase tudo** (read-only) | aprovação só se o relatório sair p/ fora |

**Leitura rápida:** as áreas de **maior autonomia** são Monitoring/Reports e a parte de
análise de SDR/CRM/Marketing (tudo read/rascunho → o Hermes trabalha sozinho). As de
**maior gate** são Finance (dinheiro), Voice AI (ligação/SMS real), Operations
(provisão/produção) e Engineering na hora de mergear/deployar.

---

## Detalhe por área

### Engineering — anel 1→3
- **Sozinho (anel 1, medium):** planejar, inspecionar código, rodar teste local, rascunhar PR, montar plano de tarefa p/ Claude Code/Codex.
- **Gate (production_sensitive):** abrir/mergear PR em repo de cliente, migration de banco, deploy, dispatch de job real. → `HERMES_HUMAN_APPROVAL`.
- **Estado:** workers de código (claude-code/codex) são nativos e prontos; os task-runners da lib são Wave-1 (prepare-only).

### Voice AI — anel 2
- **Sozinho (safe):** analisar transcrição da Raissa, extrair score.
- **Gate (external_communication + financial):** **qualquer** SMS ou ligação real — dupla trava: allowlist de destinatário setada fora-de-banda **e** aprovação. É a única área daemon-live que gasta e fala com fora.
- **Estado:** `telnyx-voice-sms` governada e ligada; caps de gasto ($2/dia) + dry-run.

### SDR & Sales — anel 0→2
- **Sozinho (safe/medium):** scoring, enriquecimento read, seleção de rota, handoff, rascunho de proposta.
- **Gate (external_communication / financial):** enviar proposta, criar convite de calendário, mandar DM/e-mail, gerar link de pagamento.
- **Estado:** 13 skills lib (Wave-1, prepare-only). Ao integrar: as de rascunho viram `external_communication` só na hora do envio.

### CRM — anel 1→2
- **Sozinho (safe/medium):** classificar pedido, estruturar feedback, detectar upsell, atualizar base **interna** (Airtable/Notion).
- **Gate:** enviar qualquer mensagem ao cliente (external_communication); **apagar registro** (delete → aprovação).
- **Estado:** 7 skills lib Wave-1 + `google-workspace-axtro` governada (e-mail = gate).

### Marketing — anel 1
- **Sozinho (safe/medium):** ângulos, oferta, brief, análise de funil, calendário, criativos e rascunhos — **nada publica**.
- **Gate (external_communication + financial):** publicar post/anúncio e **gastar mídia**; divulgar case (dados de cliente → autorização explícita).
- **Estado:** 9 skills lib Wave-1 + toolbelt criativo nativo (16 skills).

### Finance — anel 3 (maior gate)
- **Sozinho (medium):** ler e resumir snapshot financeiro (read-only).
- **Gate (financial_sensitive):** **qualquer** cobrança, criação de produto/preço, link de pagamento, gasto — via **token fora-de-banda** (padrão `hermes-purchase`: token só no Telegram, hash no ledger, `hmac.compare_digest`). Env-gate sozinho **não basta** aqui.
- **Estado:** `hermes-purchase` governada (ring 3) + 3 skills Stripe lib com **proibição estrutural** (nunca chamam a API real).

### Operations — anel 0→2
- **Sozinho (safe/medium):** auditar status dos repos, consultar a VPS (read), rodar monitor.
- **Gate (production_sensitive):** alterar o **skill registry** (muda o que roda), despachar job real, **provisionar acesso** (login-access-delivery — mais sensível, toca secrets), tocar produção.
- **Estado:** 3 governadas (auditor, ask-vps, factory-monitor*) + 4 lib. *factory-monitor está bloqueada por R1 (sem `contract.json`).

### Documentation — anel 1→2
- **Sozinho (safe/medium):** gerar docs, treino, decks — **internos**.
- **Gate (external_communication):** **entregar** ao cliente, compartilhar arquivo externo.
- **Estado:** 2 lib + toolbelt nativo (obsidian, powerpoint, notion) + `google-workspace-axtro`.

### Browser Automation — anel 2 (high_risk)
- **Sozinho (medium):** QA exploratório em **staging**, demos.
- **Gate (high_risk / production):** submeter formulário real, logar em conta de produção, agir em sistema de cliente. `computer-use` pode fazer qualquer coisa na tela → gate p/ qualquer efeito real.
- **Estado:** 100% toolbelt nativo (a lib não tem browser).

### Monitoring & Reports — anel 0 (maior autonomia)
- **Sozinho (safe):** **quase tudo** — auditoria, saúde da fábrica, relatório semanal, monitor. Read-only por natureza.
- **Gate:** só se o relatório for **enviado para fora** (aí vira external_communication).
- **Estado:** 2 governadas + 4 lib + nativos. É a área onde o Hermes tem mais liberdade real hoje.

---

## Como uma skill nova ganha autonomia (o caminho)

1. Nasce com `contract.json` declarando `risk_class` + `autonomy_ring` honestos (as 52 da lib ainda **não** têm `risk_class` — é o campo a preencher).
2. Entra em `GOVERNED_SKILLS.txt` (senão é pass-through, fora do controle do core).
3. Começa `enabled:false` → só dry-run enquanto valida.
4. Ganha testes (obrigatório p/ `medium_risk` rodar sozinho).
5. Liga `enabled:true`. Ação real de classe sensível **só** com o gate humano da área.
6. Kill switch sempre disponível.

> **Invariantes que nenhuma área quebra:** não gastar sem aprovação · não enviar
> comunicação externa real sem aprovação · não mexer em produção sem gate · não expor
> secrets · não apagar dados sem aprovação · não fazer chamada real sem autorização.

Enforcement em runtime: [Autonomy Core](../axtro/README_AUTONOMY_CORE.md) ·
mapa das skills: [HERMES_SKILL_MAP.md](HERMES_SKILL_MAP.md).
