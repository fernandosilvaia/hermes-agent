# Fable 5 — Masterplan do Hermes Agent da Axtro AI

**Ciclo Fable 5 · 2026-07-07 · repo `02_PRODUTOS/lab/hermes-agent`**

> Plano mestre para o Hermes Agent virar o maestro operacional da Axtro AI.
> Honesto sobre o que EXISTE hoje vs o que é GAP — nada de número inventado.

---

## 1. Visão final

- **Hermes VPS** orquestra (daemon 24/7 na Contabo, `hermes.axtroai.com`).
- **Hermes Local** (MacBook) executa o que precisa dos repos, que vivem no Mac.
- **Claude Code / Codex** fazem código pesado real no repo.
- **Control Tower** (`house.axtroai.com`) mostra telemetria e a fila ao vivo.
- **Raissa** qualifica leads por voz (ElevenLabs + Telnyx).
- **Agentes = papéis operacionais**, não 59 processos caros.
- **Skills = capacidades reutilizáveis**, cada uma com contrato de governança.
- **Fernando** sai da microexecução → estratégia, comercial, decisões críticas.

## 2. Arquitetura em 4 camadas (existe vs gap)

### Command Layer
| Componente | Estado |
|---|---|
| Control Tower (Next 16, `house.axtroai.com`) | ✅ existe |
| `/agent-observability` (cockpit, polling 15s) | ✅ existe |
| `/hermes` (dashboard visual do agente + sub-agentes) | ✅ **construído neste ciclo** (branch `feat/hermes-dashboard-2026-07-07`, não mesclado) |
| Orb de voz (AxtrinhoCore) | ✅ existe |
| Telegram do Hermes | ✅ existe (bot dedicado, allowlist) |
| Aprovações / gates | ⚠️ parcial — gate é prosa, não enforcement (ver P0s) |

### Orchestration Layer
| Componente | Estado |
|---|---|
| Hermes VPS (daemon) | ✅ existe, 24/7 |
| Job Queue (`src/lib/hermes-jobs.ts`, `/api/hermes/jobs`) | ✅ existe |
| MacBook Worker (`scripts/axtro-local-worker.mjs`) | ✅ existe |
| Skill Registry (`src/lib/hermes-skills.ts`, 18 skills) | ✅ existe (estático) |
| Model Router (`src/lib/hermes-model-routing.ts`) | ✅ existe |
| Cost Ledger / Audit Log | ⚠️ **pendente de instrumentação** — sem cost ledger central |
| Kill-switch por `contract.json` no loader | ❌ GAP — loader ignora contract (raiz de vários P0) |

### Execution Layer
| Componente | Estado |
|---|---|
| MacBook Worker (claude-code/shell) | ✅ existe (codex bloqueado por CLI ausente) |
| Migration supabase `0020_hermes_jobs.sql` | ⚠️ existe, **não aplicada em prod** |

### Business Layer
| Componente | Estado |
|---|---|
| Site/diagnóstico Axtro | ✅ existe |
| Raissa + ElevenLabs + Telnyx | ⚠️ SMS testado; voz conversacional é gancho off-by-default; 10DLC pendente |
| CRM da House | ✅ existe (dentro do Control Tower) |
| Google Calendar / Workspace | ✅ existe (mas com P0 de segurança — ver AUDIT_REPORT) |
| Stripe | ⚠️ chave é sempre gate humano; skills Stripe da Frente B são prepare-only |

## 3. Modelo operacional dos agentes

**59 agentes visuais ≠ 59 processos caros.** Os agentes da House são
**papéis operacionais** (fichas em `03_AGENTES/fichas/`); a execução real
acontece por poucos executores: Hermes VPS, Hermes Local, MacBook Worker,
Claude Code, Codex, APIs específicas, rotinas agendadas. Um papel é
"invocado" — carrega-se a ficha como system prompt e roda num dos
executores — não é um daemon permanente por agente.

## 4. Camada AgentOps & Skills (10 papéis)

AgentOps Architect · Local Runner Controller · Skills Librarian · Secrets &
Access Manager · Cost Monitor · GitHub CI Watcher · Security Scanner ·
Workspace Organizer · Factory Health Watchdog · Human Task Collector.

Cobertura atual por skill real (Frente B — `~/Documents/Hermes Agent Axtro/`):
`project-status-auditor`, `factory-health-watchdog`, `local-worker-monitor`,
`macbook-job-dispatcher`, `human-task-collector`, `skill-registry-manager`
já implementadas em staging. Security Scanner existe em `~/.hermes/skills`.
Cost Monitor é **gap** (só contrato `cost_monitor` no registry, sem código).

## 5. Roteamento de modelos

Haiku 4.5 (operação/triagem/status) → Sonnet 5 (implementação/APIs sensíveis
controladas) → Opus 4.8 (arquitetura crítica/decisão sem rollback) →
Claude Code (código pesado no repo) / Codex (scripts/refactors). Regra: o
mais barato que resolve; subir de modelo **antes** da tarefa ficar perigosa.

## 6. Anéis de autonomia (0-3, com 4 proibido)

- **0** leitura/relatório/triagem — livre.
- **1** branch `hermes/*`, PR interno, dry-run, MVP com dados simulados — livre com limite.
- **2** ação externa controlada (SMS a lead consentido, Stripe restrito, merge interno com checks verdes) — exige `human_gates` declarados.
- **3** gasto alto, produção de cliente, migration destrutiva, DNS — sempre humano.
- **4** proibido: secret em log, wallet, cruzar dados de clientes, desligar auditoria.

As skills do daemon corrigidas neste ciclo receberam anéis: google-workspace
(2), telnyx (2), ask-vps (2), hermes-purchase (3, financeiro).

## 7. Padrão premium de skill

Ver `axtro/SKILL_STANDARD.md` e `axtro/CONTRACT_SCHEMA.json` (criados neste
ciclo). Toda skill nasce `enabled=false` / `production_ready=false` /
`activation_stage=staging|scaffold`, com `stop_conditions` e
`telemetry_events` não-vazios, credenciais só por nome de env var, e
**gate de dry-run no próprio script** (dupla-env `HERMES_ALLOW_EXECUTE` +
`<SKILL>_ENABLED`) — porque o loader não faz o gate por contrato sozinho.

## 8. As 7 ondas de skills (Frente B — status)

Implementadas 42 skills em 7 ondas na biblioteca `~/Documents/Hermes Agent Axtro/`
(ver `FABLE5_FINAL_IMPLEMENTATION_REPORT.md` lá). 10 skills permanecem
scaffold (nunca pedidas). Todas `enabled=false`.

## 9. Estado atual honesto

- **Funciona hoje:** daemon VPS 24/7, Telegram, Google Workspace, Telnyx SMS, Job Queue, MacBook Worker, Control Tower, dashboard `/hermes`.
- **P0 de segurança abertos (Frente A):** 5 P0 reais nas skills do daemon — este ciclo os fecha (ver `SECURITY_FIX_REPORT.md`).
- **Pendente de instrumentação:** cost ledger central, kill-switch por contrato no loader, migration de jobs em prod.

## 10. Plano das próximas 72 horas

1. **Fechar os 5 P0** (google-workspace, telnyx, ask-vps, hermes-purchase) — **feito neste ciclo, em staging, aguardando revisão humana**.
2. Fernando revisa `SECURITY_FIX_REPORT.md` e decide ativar (via dupla-env) skill por skill.
3. Mesclar dashboard `/hermes` (gate: main faz auto-deploy).
4. Ensinar o loader do daemon a respeitar `contract.json` (`enabled=false` real no runtime, não só no script) — é a correção estrutural que elimina a categoria "gate-como-prosa".
5. Instrumentar cost ledger central (fecha o gap do Cost Monitor).

## 11. Checklist de produção (definition of done de uma skill)

- [ ] `contract.json` válido (`enabled=false`, stop_conditions, telemetry_events, autonomy_ring, human_gates para ação de risco)
- [ ] Gate de dry-run no script (dupla-env), fail-CLOSED
- [ ] Nenhuma ação real sem o gate; nenhum secret/OTP em output cru
- [ ] `tests/` cobrindo o caminho de ataque (o P0) + o caminho legítimo
- [ ] Degradação segura (erro vira JSON, não traceback)
- [ ] Revisão adversarial independente passou
- [ ] Ativação em produção = decisão humana registrada, nunca automática
