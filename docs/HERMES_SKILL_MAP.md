# Hermes Skill Map — os departamentos operacionais

**Atualizado 2026-07-08.** Mapa das skills que o Hermes coordena, por área de negócio.
Fonte: inventário real de duas origens (nada inventado).

## Como ler

**Fonte da skill:**
- 🟢 **governada** — no daemon, já ligada no Autonomy Core (`GOVERNED_SKILLS.txt`), enforcement em runtime.
- ⚪ **nativa Nous** — toolbelt herdado do fork; pass-through (não governado pela Axtro).
- 🟡 **lib Wave-1** — biblioteca `~/Documents/Hermes Agent Axtro/` (52 skills). **Todas `ring 0`, `enabled:false`, dry-run/prepare-only, sem `risk_class`.** São o catálogo de departamentos a integrar no Autonomy Core.

**Risco** = classe de risco do Autonomy Core (`safe` / `medium_risk` / `high_risk` /
`production_sensitive` / `financial_sensitive` / `external_communication`). Para as
🟡 lib e ⚪ nativas o valor é uma **proposta** (elas ainda não declaram `risk_class`);
é exatamente o campo a preencher ao integrá-las.

**Roteamento** (as 4 perguntas do pedido) está resumido por área, porque o padrão é
por departamento, não por skill:
- **Executar direto** = Hermes roda via `skill_runner` sem humano (skills `safe`/`medium` com teste).
- **Claude Code** = pensar/arquitetar/revisar (não executa operação da empresa).
- **Codex** = escrever/consertar o código de uma skill (tarefa fechada).
- **Aprovação humana** = gate obrigatório (dinheiro, comunicação externa real, produção, delete, chamada real).

> **Estado honesto:** hoje o Autonomy Core governa **só as 6 daemon-governadas**. As
> 52 lib são scaffolding Wave-1 (dry-run, sem ação real). Este mapa serve para (a)
> operar já com as 6 + toolbelt nativo, e (b) integrar a biblioteca área por área,
> atribuindo `risk_class` conforme a coluna Risco.

---

## 1. Engineering
**Departamento:** build, revisão, testes, deploy assistido. Aqui vivem os dois workers de código.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| claude-code / codex / opencode | ⚪ nativa | delegar código ao worker (feature, PR) | high_risk (executa CLI de código) | via worker + gate p/ merge |
| github-pr-workflow / github-code-review / github-issues / github-repo-management / github-auth | ⚪ nativa | ciclo de PR, review, issues, repos | medium→production_sensitive (merge/release) | direto p/ ler; gate p/ merge/release |
| plan / spike / tdd / systematic-debugging / simplify-code / requesting-code-review | ⚪ nativa | disciplina de engenharia (planejar, testar, revisar) | safe/medium | direto |
| codebase-inspection / node-inspect-debugger / python-debugpy / jupyter-live-kernel | ⚪ nativa | inspeção e debug | medium_risk | direto |
| pr-builder | 🟡 lib | monta título/corpo/checklist do PR (nunca abre) | medium_risk | prepare-only |
| test-runner | 🟡 lib | detecta framework e prepara lista fechada de comandos | high_risk (roda comandos) | prepare-only |
| claude-code-task-runner / codex-task-runner | 🟡 lib | monta o plano de invocação do worker (nunca executa) | production_sensitive | prepare-only |
| supabase-migration-drafter | 🟡 lib | rascunha migration de banco | production_sensitive | prepare-only |
| vercel-preview-deployer | 🟡 lib | prepara deploy de preview | production_sensitive (+ gasto) | prepare-only |
| github-ci-watcher | 🟡 lib | observa CI do GitHub | medium_risk | prepare-only |
| mvp-brief-generator | 🟡 lib | gera brief de MVP (compute puro) | safe | prepare-only |
| mvp-job-creator | 🟡 lib | vira brief aprovado em job seguro do Worker | production_sensitive | prepare-only |

**Roteamento:** **Claude Code** desenha a arquitetura e revisa o diff grande. **Codex**
escreve o código/scripts/testes da tarefa fechada. **Executar direto:** inspeção,
plano, testes locais (medium). **Aprovação humana:** abrir/mergear PR em repo de
cliente, migration, deploy, qualquer `production_sensitive`.

---

## 2. Voice AI
**Departamento:** voz, ligação, SMS, atendimento por voz (a Raissa).

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| telnyx-voice-sms | 🟢 governada | telefone da empresa: envia/recebe SMS e faz ligação TTS | **external_communication** (+ financial: gasta telefonia) | Ring 2 · gate + allowlist + dry-run |
| raissa-transcript-analyzer | 🟡 lib | analisa transcrição da Raissa → dores/objeções/score | safe (só análise) | prepare-only |
| heartmula / songsee / audiocraft | ⚪ nativa | geração/análise de áudio e música | medium_risk | direto p/ rascunho |

**Roteamento:** **Executar direto:** análise de transcrição (safe). **Aprovação humana:**
**toda** ligação real e **todo** SMS real (external_communication + gasto). **Codex:**
ajustar o parser da Raissa. **Claude Code:** desenhar o fluxo de atendimento por voz.

---

## 3. SDR & Sales
**Departamento:** prospecção, qualificação, follow-up, proposta.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| diagnostic-form-analyzer | 🟡 lib | analisa form do site e monta briefing pra Raissa | safe | prepare-only |
| lead-scoring | 🟡 lib | pontua leads (compute) | safe | prepare-only |
| lead-enrichment | 🟡 lib | enriquece lead (API externa, read) | medium_risk (rede) | prepare-only |
| route-selector | 🟡 lib | decide rota lead→MVP (recomenda) | safe | prepare-only |
| solution-template-finder | 🟡 lib | casa necessidade × catálogo de soluções | safe | prepare-only |
| sales-handoff-pack | 🟡 lib | consolida diagnóstico+transcrição+score p/ o closer | safe | prepare-only |
| proposal-builder | 🟡 lib | rascunha proposta comercial (nunca envia/fecha) | medium_risk (→ financial no link) | prepare-only |
| calendar-booker | 🟡 lib | sugere horário + rascunho de convite (nunca cria evento) | external_communication (→ ao promover) | prepare-only |
| pricing-strategy / closing-strategy / deal-risk-analyzer / objection-predictor / meeting-script-builder | 🟡 lib | estratégia de venda (recomenda) | safe/medium | prepare-only |
| xurl / himalaya | ⚪ nativa | X/Twitter (post, DM) · e-mail IMAP/SMTP | external_communication | gate p/ envio real |

**Roteamento:** **Executar direto:** scoring, enrichment (read), rota, handoff, rascunho
de proposta (tudo prepare-only/safe/medium). **Aprovação humana:** enviar proposta,
criar convite real, mandar DM/e-mail real, gerar link de pagamento. **Claude Code:**
desenhar a máquina de estados do funil. **Codex:** implementar um scorer/parser novo.

---

## 4. CRM
**Departamento:** cadastro, pipeline, histórico e sucesso do cliente.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| client-onboarding-builder | 🟡 lib | monta plano de onboarding (nunca agenda/envia) | medium_risk (→ external ao enviar) | prepare-only |
| post-sale-checkin | 🟡 lib | rascunha check-in pós-venda (nunca envia) | external_communication (→ ao promover) | prepare-only |
| customer-success-followup | 🟡 lib | avalia saúde da relação e próxima ação | medium_risk | prepare-only |
| referral-request-builder | 🟡 lib | rascunha pedido de indicação (gate em satisfação real) | external_communication (→ ao promover) | prepare-only |
| upsell-detector | 🟡 lib | detecta sinal de upsell (não contata) | medium_risk | prepare-only |
| adjustment-request-classifier | 🟡 lib | classifica pedido de ajuste vs escopo | safe | prepare-only |
| client-feedback-collector | 🟡 lib | estrutura feedback recebido (não responde) | safe | prepare-only |
| airtable / notion | ⚪ nativa | CRUD de registros, pipeline, base | medium_risk | direto p/ base interna; gate p/ delete |
| google-workspace-axtro | 🟢 governada | Gmail/Drive/Docs/Sheets/Calendar como funcionário Axtro | external_communication (envia e-mail) | Ring 2 · gate |

**Roteamento:** **Executar direto:** classificação, estruturação de feedback, detecção
de upsell, atualizar base interna (Airtable/Notion). **Aprovação humana:** enviar
qualquer mensagem ao cliente, apagar registro. **Codex:** integração nova com o CRM.
**Claude Code:** modelar o pipeline.

---

## 5. Marketing
**Departamento:** conteúdo, campanha, criativo, social.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| campaign-angle-generator / offer-builder / creative-brief-generator | 🟡 lib | ângulos, oferta, brief criativo (rascunho) | safe/medium | prepare-only |
| funnel-analyzer / cro-recommendation | 🟡 lib | acha gargalo do funil, recomenda CRO | safe | prepare-only |
| organic-content-calendar | 🟡 lib | calendário de conteúdo orgânico | safe | prepare-only |
| ad-copy-generator | 🟡 lib | rascunha copy de anúncio (nunca publica/gasta) | medium_risk (→ external+financial ao publicar) | prepare-only |
| social-post-generator | 🟡 lib | rascunha post LinkedIn/IG (nunca publica) | external_communication (→ ao promover) | prepare-only |
| case-study-builder | 🟡 lib | monta case de sucesso (bloqueia sem autorização do cliente) | medium_risk (dados de cliente) · gate | prepare-only |
| creative/* (16) | ⚪ nativa | design, infográfico, vídeo, p5js, diagramas | safe/medium | direto (artefato) |
| gif-search / youtube-content | ⚪ nativa | GIFs · transcrição→conteúdo do YouTube | safe | direto |

**Roteamento:** **Executar direto:** gerar ângulos, calendário, análise de funil,
criativos/rascunhos (nada publica). **Aprovação humana:** **publicar** qualquer post,
subir anúncio (external_communication) e **gastar mídia** (financial_sensitive),
divulgar case (dados de cliente). **Codex:** gerador novo. **Claude Code:** estratégia de conteúdo.

---

## 6. Finance
**Departamento:** cobrança, gasto, faturamento, conciliação. Área de **maior gate**.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| hermes-purchase | 🟢 governada | guarda-corpo de gasto: allowlist + teto + ledger + aprovação (nunca paga sozinho) | **financial_sensitive** | Ring 3 · token humano fora-de-banda |
| checkout-link-creator | 🟡 lib | monta payload de Payment Link Stripe (nunca chama a API) | financial_sensitive | prepare-only · proibição estrutural |
| stripe-product-creator | 🟡 lib | monta payload de produto/preço Stripe (nunca chama API/secret) | financial_sensitive | prepare-only · proibição estrutural |
| stripe-finance-reader | 🟡 lib | lê snapshot financeiro → resumo (revenue, MRR, churn) | medium_risk (dado sensível, read) | prepare-only |
| polymarket | ⚪ nativa | consulta mercados/preços | safe (read) | direto |

**Roteamento:** **Executar direto:** ler/resumir finanças (read). **Aprovação humana:**
**qualquer** cobrança, criação de produto/preço, link de pagamento, gasto — sempre
via o padrão de token fora-de-banda da `hermes-purchase`. **Codex:** integração Stripe.
**Claude Code:** desenhar o fluxo de faturamento.

---

## 7. Operations
**Departamento:** orquestração interna, filas, provisionamento, automações.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| project-status-auditor | 🟢 governada | raio-X read-only dos repos da House (branch, não-commitado, parado) | safe | Ring 0 · direto |
| ask-vps-hermes | 🟢 governada | ponte read-only p/ o Hermes na VPS (só consulta, nunca ação) | high_risk (rede, injeção) | Ring 2 · gate |
| axtro-factory-monitor | 🟢 governada | briefing matinal + watch de secret vazado → Telegram | external_communication (Telegram interno) · **sem contract → R1 bloqueada** | Ring 0 (precisa contract) |
| skill-registry-manager | 🟡 lib | valida/lista/audita o registry de skills (dry-run) | production_sensitive (altera o que roda) | prepare-only |
| macbook-job-dispatcher | 🟡 lib | despacha job pro Worker no MacBook | production_sensitive | prepare-only |
| human-task-collector | 🟡 lib | coleta tarefa humana (agentops) | medium_risk | prepare-only |
| login-access-delivery | 🟡 lib | **a mais sensível:** instruções manuais de provisionamento (nunca gera senha/token/secret) | production_sensitive + secrets-surface · gate duro | prepare-only |
| maps / apple-reminders / openhue | ⚪ nativa | rotas · lembretes · luzes | safe | direto |

**Roteamento:** **Executar direto:** auditoria de status, consulta à VPS, monitor
(read). **Aprovação humana:** alterar o registry (muda o que roda), despachar job real,
**qualquer** provisionamento de acesso, tocar produção. **Claude Code:** desenhar a
orquestração. **Codex:** implementar um dispatcher.

---

## 8. Documentation
**Departamento:** docs técnicos e comerciais, handoffs, treinamento, propostas.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| delivery-pack-builder | 🟡 lib | monta pacote de entrega em linguagem de cliente (não envia) | medium_risk (→ external ao entregar) | prepare-only |
| training-material-generator | 🟡 lib | gera material de treino (rascunho, não publica) | safe | prepare-only |
| obsidian / notion | ⚪ nativa | notas, base de conhecimento | medium_risk | direto (interno) |
| powerpoint / nano-pdf / ocr-and-documents | ⚪ nativa | .pptx, editar PDF, extrair texto | safe/medium | direto |
| google-workspace-axtro | 🟢 governada | Docs/Sheets/Slides como funcionário Axtro | external_communication (compartilha/e-mail) | Ring 2 · gate |
| apple-notes | ⚪ nativa | notas locais | safe | direto |

**Roteamento:** **Executar direto:** gerar docs/treino/decks internos. **Aprovação humana:**
**entregar** ao cliente (external), compartilhar arquivo externo. **Codex:** gerador de doc.
**Claude Code:** estrutura da documentação técnica.

---

## 9. Browser Automation
**Departamento:** navegação, scraping, preenchimento, RPA.
> **Nota honesta:** a biblioteca Wave-1 **não tem** skill de browser. Aqui é 100% toolbelt nativo.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| computer-use | ⚪ nativa | dirige o desktop em background (click/type/scroll) | high_risk (pode fazer qualquer coisa na tela) | gate p/ ação real |
| dogfood | ⚪ nativa | QA exploratório de web app: acha bug, junta evidência | medium_risk | direto p/ QA em staging |
| pretext | ⚪ nativa | demos de browser sem DOM | safe | direto |

**Roteamento:** **Executar direto:** QA em staging, demos. **Aprovação humana:** qualquer
automação que **submeta formulário real**, faça login em conta de produção, ou aja em
sistema de cliente. **Claude Code:** desenhar o fluxo de RPA. **Codex:** script de automação.

---

## 10. Monitoring & Reports
**Departamento:** saúde dos projetos, KPIs, relatórios.

| Skill | Fonte | Função | Risco (proposto) | Autonomia |
|---|---|---|---|---|
| project-status-auditor | 🟢 governada / 🟡 lib | raio-X read-only dos repos (existe nas duas frentes) | safe | Ring 0 · direto |
| factory-health-watchdog | 🟡 lib | saúde da fábrica: job travado, worker offline, lead parado | safe | prepare-only |
| local-worker-monitor | 🟡 lib | monitora o worker local | safe | prepare-only |
| weekly-growth-report | 🟡 lib | consolida relatório semanal (leads, conteúdo, comercial) | safe | prepare-only |
| blogwatcher | ⚪ nativa | monitora blogs/RSS | safe | direto |
| weights-and-biases | ⚪ nativa | logs de experimento/ML | medium_risk | direto |
| teams-meeting-pipeline | ⚪ nativa | pipeline de resumo de reunião do Teams | medium_risk | direto p/ resumo |

**Roteamento:** **Executar direto:** **quase tudo** aqui é `safe` read-only → o Hermes
roda sozinho e entrega o relatório. **Aprovação humana:** só se um relatório for
**enviado para fora** (vira external_communication). **Codex:** novo coletor de métrica.
**Claude Code:** desenhar o dashboard.

---

## Resumo por número

| Área | 🟢 gov | 🟡 lib | ⚪ nativa (destaque) |
|---|---|---|---|
| Engineering | — | 9 | claude-code, codex, github/* (6), software-dev/* (9) |
| Voice AI | 1 (telnyx) | 1 | audiocraft, songsee |
| SDR & Sales | — | 13 | xurl, himalaya |
| CRM | 1 (gw-axtro) | 7 | airtable, notion |
| Marketing | — | 9 | creative/* (16), youtube-content |
| Finance | 1 (purchase) | 3 | polymarket |
| Operations | 3 | 4 | maps, openhue |
| Documentation | 1 (gw-axtro) | 2 | obsidian, powerpoint, notion |
| Browser Automation | — | 0 | computer-use, dogfood |
| Monitoring & Reports | 2 | 4 | blogwatcher, teams-pipeline |

**Total:** 6 governadas (live) · 52 lib (Wave-1 a integrar) · 71 nativas (toolbelt).
Detalhe da autonomia por área e dos gates: [HERMES_AUTONOMY_AREAS.md](HERMES_AUTONOMY_AREAS.md).
