# Hermes Company OS — o sistema operacional de IA da AxtroAI

**Atualizado 2026-07-08**

O Hermes é o **Operating System de IA da empresa**. Ele coordena a Software House AI
e os projetos da AxtroAI: planeja, delega, executa operações via skills, chama os
workers de código (Claude Code e Codex) quando precisa, valida, relata, aprende e
cria skills novas quando enxerga uma necessidade recorrente.

Não é um chatbot. Não é um orquestrador de dois modelos. É o **cérebro operacional**
que faz a empresa rodar, com uma camada de governança (Autonomy Core) que garante
liberdade com trilhos.

---

## O modelo em uma frase

> **Hermes** decide e coordena · **Claude Code** arquiteta · **Codex** codifica ·
> **Skills** operam os departamentos · **Autonomy Core** governa · **Humano** aprova
> só o sensível.

Detalhe dos papéis: [HERMES_WORKER_MODEL.md](HERMES_WORKER_MODEL.md).

---

## As 10 capacidades do Hermes

| # | Capacidade | Como acontece |
|---|---|---|
| 1 | **Planejar** | quebra um objetivo de negócio em passos; decide o que é skill, o que é Claude Code, o que é Codex |
| 2 | **Delegar** | roteia cada passo ao worker certo (skill / arquiteto / engenheiro) |
| 3 | **Executar skills** | roda a skill pelo executor oficial `skill_runner` → Autonomy Core decide o modo |
| 4 | **Chamar Claude Code** | arquitetura, revisão ampla, refatoração grande, plano técnico |
| 5 | **Chamar Codex** | tarefa de código fechada: bug, UI, script, teste, refatoração controlada |
| 6 | **Usar skills internas** | operações de empresa (SDR, CRM, finanças, docs, monitoramento…) |
| 7 | **Validar** | testes, checagem de output, dry-run antes de qualquer ação real |
| 8 | **Gerar relatórios** | log estruturado (JSONL) + relatório humano a cada execução |
| 9 | **Aprender** | registra o que funcionou; detecta padrões recorrentes |
| 10 | **Criar skills** | quando um padrão se repete, empacota como skill nova (contract + testes) |

---

## O loop operacional (o "kernel" do Hermes)

```
   PEDIDO / GATILHO
        │
        ▼
   1. PLANEJAR ──────────────────────────────┐
        │  quebra em passos                   │
        ▼                                     │
   2. DELEGAR                                 │
        ├─ operação da empresa → SKILL        │
        ├─ pensar sistema     → CLAUDE CODE   │  aprende e
        └─ código fechado     → CODEX         │  realimenta
        │                                     │  o plano
        ▼                                     │
   3. EXECUTAR (skill via skill_runner)       │
        │   Autonomy Core: safe? sensível?    │
        │   ┌── dry-run se sensível sem gate   │
        │   └── real se seguro / com gate      │
        ▼                                     │
   4. VALIDAR (testes, checagem, diff)        │
        │                                     │
        ▼                                     │
   5. RELATAR (log JSONL + relatório) ────────┤
        │                                     │
        ▼                                     │
   6. APRENDER → padrão recorrente? ──────────┘
        │  sim
        ▼
   7. CRIAR SKILL NOVA (contract + testes, enabled:false até validar)
```

Em qualquer ponto que a ação seja **sensível** (dinheiro, comunicação externa real,
produção, delete, chamada real), o Autonomy Core **para e pede gate humano** — e só
aí. O resto flui sozinho.

---

## Governança — as regras que nunca quebram

Herdadas do **Autonomy Core** ([README](../axtro/README_AUTONOMY_CORE.md)):

- 🚫 **não gastar dinheiro** sem aprovação (`financial_sensitive`)
- 🚫 **não enviar comunicação externa real** (e-mail/SMS/ligação/DM) sem aprovação (`external_communication`)
- 🚫 **não mexer em produção** sem gate (`production_sensitive`)
- 🚫 **não expor secrets** (credenciais nunca em log/stdout; fail-closed se faltam)
- 🚫 **não apagar dados** sem aprovação
- 🚫 **não fazer chamada real** a serviço externo sem autorização
- 🛑 **kill switch global** (`HERMES_KILL_SWITCH=on`) para tudo na hora

Tudo isso é **enforced em runtime**, não é regra de documento: toda skill passa pelo
`skill_runner` → `autonomy_core.decide` antes de agir. Anéis de autonomia (0–4) e
classes de risco (safe / medium / high / production / financial / external) decidem
o que roda sozinho e o que espera o humano. Mapa por área:
[HERMES_AUTONOMY_AREAS.md](HERMES_AUTONOMY_AREAS.md).

---

## Os departamentos (áreas operacionais)

As skills são organizadas em 10 áreas de negócio. Cada uma é um "departamento" que o
Hermes coordena:

1. **Engineering** — build, refatoração, testes, deploy assistido
2. **Voice AI** — voz, ligação, transcrição, atendimento por voz
3. **SDR & Sales** — prospecção, qualificação, follow-up, propostas
4. **CRM** — cadastro, pipeline, histórico de cliente
5. **Marketing** — conteúdo, campanhas, social, criativos
6. **Finance** — cobrança, gasto, faturamento, conciliação
7. **Operations** — orquestração interna, filas, automações
8. **Documentation** — docs técnicos, comerciais, handoffs, propostas
9. **Browser Automation** — navegação, scraping, preenchimento, RPA
10. **Monitoring & Reports** — saúde dos projetos, KPIs, relatórios

Mapa completo (skill · função · risco · autonomia · quando chamar cada worker):
[HERMES_SKILL_MAP.md](HERMES_SKILL_MAP.md).

---

## Como isto opera a empresa (exemplo real)

**Objetivo:** "Prospectar 20 leads novos e preparar follow-up."
1. **Planejar** — Hermes divide: buscar leads (SDR) → enriquecer (SDR) → montar
   sequência (Marketing) → agendar follow-up (Operations).
2. **Executar direto** — busca e enriquecimento são `medium_risk` (leem dados,
   não enviam nada) → rodam sozinhos via skill.
3. **Validar** — Hermes confere a lista, dedup, qualidade.
4. **Gate humano** — o **envio real** da sequência é `external_communication` →
   Autonomy Core roda em **dry-run** (monta tudo) e **espera o Fernando aprovar**.
5. **Relatar** — log + relatório: 20 leads, sequência pronta, aguardando aprovação.
6. **Aprender** — se isso vira semanal, Hermes propõe uma skill "prospecção-semanal".

Nenhum dinheiro gasto, nenhuma mensagem real enviada sem o Fernando dizer sim — e
mesmo assim o trabalho pesado já está pronto quando ele chega para aprovar.

---

Ver também o relatório executivo:
[reports/HERMES_COMPANY_OS_REPORT.md](../reports/HERMES_COMPANY_OS_REPORT.md).
