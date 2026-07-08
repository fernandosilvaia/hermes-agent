# Hermes Worker Model — quem faz o quê

**O Hermes não é um orquestrador de Claude Code e Codex. O Hermes é o Operating
System de IA da empresa.** Claude Code e Codex são apenas dois workers — bons em
código. As skills são os braços operacionais da empresa. O Autonomy Core é a
camada que mantém tudo nos trilhos.

---

## Os papéis (não confundir)

| Papel | Quem | O que faz | O que NÃO faz |
|---|---|---|---|
| **Cérebro operacional** | **Hermes** | planeja, delega, executa skills, valida, relata, aprende, cria skills novas | não escreve arquitetura de software do zero nem produz código de produção sozinho |
| **Arquiteto de software** | **Claude Code** | arquitetura, plano técnico, revisão ampla, refatoração grande, auditoria de contexto grande | não é o dono da operação da empresa; não decide negócio |
| **Engenheiro de código** | **Codex** | um bug, uma UI, Figma→código, um teste, refatoração controlada (tarefa fechada, arquivos listados, regra de parada) | não faz varredura global; não decide arquitetura |
| **Departamentos operacionais** | **Skills** | operações reais da empresa (voz, SDR, CRM, finanças, docs, browser, monitoramento…) | não rodam fora do executor oficial; não fazem ação real sem passar pelo Autonomy Core |
| **Segurança e governança** | **Autonomy Core** | decide o que pode rodar sozinho, o que é dry-run, o que exige gate humano; loga tudo | não bloqueia por burocracia — só o necessário para não causar dano grave |
| **Aprovação** | **Humano (Fernando)** | aprova **apenas** ações sensíveis (dinheiro, comunicação externa real, produção, delete, chamada real) | não precisa aprovar o trabalho seguro do dia a dia |

**Regra mental:** Hermes é o CEO operacional de IA. Claude Code é o CTO/arquiteto que
ele chama para pensar sistema. Codex é o dev que ele chama para uma tarefa fechada.
As skills são os funcionários de cada departamento. O Autonomy Core é o compliance.

---

## Como o Hermes decide quem chamar

```
                        ┌─────────────────────────┐
                        │   HERMES (cérebro)      │
                        │  planeja · delega ·     │
                        │  valida · relata ·      │
                        │  aprende · cria skill   │
                        └───────────┬─────────────┘
                                    │  para CADA passo, pergunta:
        ┌───────────────────────────┼───────────────────────────┐
        ▼                           ▼                           ▼
  "é operação da           "preciso pensar             "é uma tarefa de
   empresa?"                arquitetura / rever          código fechada?"
        │                   / refatorar grande?"                │
        ▼                           ▼                           ▼
   ┌─────────┐               ┌──────────────┐            ┌──────────┐
   │  SKILL  │               │  CLAUDE CODE │            │  CODEX   │
   │(via     │               │ (arquiteto)  │            │(engenheiro)
   │ runner) │               └──────────────┘            └──────────┘
        │                           │                           │
        ▼                           ▼                           ▼
   Autonomy Core              devolve plano /            devolve patch /
   decide + loga              revisão / design           teste / script
        │                           │                           │
        └───────────┬───────────────┴───────────────────────────┘
                    ▼
             HERMES valida o resultado → relatório → aprende
                    │
                    ▼  (se ação sensível)
             GATE HUMANO (só quando necessário)
```

---

## Quando chamar cada worker (regras práticas)

### Chamar **Claude Code** (arquiteto) quando:
- desenhar a arquitetura de um projeto ou de uma skill nova não-trivial
- revisar um diff grande / auditar um repo inteiro
- refatoração ampla que cruza muitos arquivos
- decidir trade-offs técnicos (banco, auth, fila, deploy) **antes** de mandar pro Codex
- planejar a quebra de um pedido grande em tickets

### Chamar **Codex** (engenheiro) quando a tarefa é FECHADA:
- um bug específico, com arquivos listados e regra de parada
- uma tela / componente de UI, ou Figma→código
- escrever um teste unitário, um script, um lint fix
- refatoração controlada de escopo pequeno
> Codex recebe **UMA** tarefa, **UM** projeto, lista de arquivos fechada, regra de
> parada. Nunca varredura global. (Risco baixo→direto; médio→Claude Code planeja
> antes; alto→Claude Code antes e depois + gate humano.)

### Executar **skill direto** (via `skill_runner`) quando:
- é operação da empresa que já tem skill (mandar relatório interno, triar inbox,
  gerar diagnóstico, atualizar CRM interno, rodar monitoramento…)
- o Autonomy Core classifica como `safe` ou `medium_risk` com testes → roda sozinho

### Pedir **aprovação humana** quando (e SÓ quando):
- vai **gastar dinheiro** (financial_sensitive)
- vai **enviar comunicação externa real** — e-mail, SMS, ligação, DM (external_communication)
- vai **mexer em produção** (production_sensitive)
- vai **apagar dados**
- vai fazer **chamada real** a um serviço externo com efeito irreversível

---

## O contrato entre Hermes e os workers

| | Skill | Claude Code | Codex |
|---|---|---|---|
| **entrada** | `contract.json` + args | contexto amplo + objetivo | tarefa fechada + arquivos + regra de parada |
| **passa pelo Autonomy Core?** | **sim, sempre** (runner) | não (produz plano/código, não age na empresa) | não (produz código, não age na empresa) |
| **saída** | resultado + log + relatório | plano / revisão / design | patch / teste / script |
| **quem valida** | Hermes (+ testes da skill) | Hermes lê e decide aplicar | Hermes + Claude Code (se médio/alto risco) |

**Ponto-chave de segurança:** ação real na empresa só acontece por **skill via
`skill_runner`** — nunca direto por Claude Code ou Codex, que só produzem artefatos
(plano, código). Isso mantém um único ponto de governança: o Autonomy Core. Código
gerado por Codex/Claude Code, quando vira operação, é empacotado como skill com
`contract.json` e passa pelo mesmo trilho.

---

## Aprender e criar skills novas

O Hermes fecha o loop:
1. **valida** cada resultado (testes, checagem, dry-run antes de real).
2. **relata** (log estruturado + relatório humano — ver Autonomy Core).
3. **aprende**: se uma necessidade aparece de forma **recorrente** (ex.: "toda semana
   eu monto o mesmo relatório de X"), isso vira candidato a skill nova.
4. **cria skill**: Hermes chama Claude Code p/ desenhar + Codex p/ implementar, gera
   o `contract.json` (classe de risco + anel honestos), adiciona em
   `GOVERNED_SKILLS.txt`, deixa `enabled:false` até validar, e só então liga.

Assim o repertório operacional da empresa cresce sozinho, mas cada braço novo já
nasce dentro dos trilhos.

---

Ver também: [HERMES_COMPANY_OS.md](HERMES_COMPANY_OS.md) ·
[HERMES_SKILL_MAP.md](HERMES_SKILL_MAP.md) ·
[HERMES_AUTONOMY_AREAS.md](HERMES_AUTONOMY_AREAS.md) ·
[Autonomy Core](../axtro/README_AUTONOMY_CORE.md)
