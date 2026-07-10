# Relatório — Hermes como Operating System de IA da AxtroAI

**2026-07-08 · repo `02_PRODUTOS/lab/hermes-agent`**

## Resumo executivo

O Hermes deixa de ser "orquestrador de Claude Code e Codex" e passa a ser o
**Operating System de IA da empresa**: o cérebro que planeja, delega, executa
operações via skills, chama os workers de código quando precisa, valida, relata,
aprende e cria skills novas. Claude Code e Codex viram **dois workers** (bons em
código). As skills são os **departamentos**. O **Autonomy Core** é o compliance que
mantém liberdade com trilhos. O **humano aprova só o sensível**.

Este relatório explica como o Hermes opera a empresa com esses quatro elementos —
skills, Claude Code, Codex e aprovação humana apenas quando necessário — e o estado
real de cada peça hoje.

**Documentos deste pacote:**
- [HERMES_COMPANY_OS.md](../docs/HERMES_COMPANY_OS.md) — a visão e as 10 capacidades
- [HERMES_WORKER_MODEL.md](../docs/HERMES_WORKER_MODEL.md) — quem faz o quê
- [HERMES_SKILL_MAP.md](../docs/HERMES_SKILL_MAP.md) — skills por 10 áreas
- [HERMES_AUTONOMY_AREAS.md](../docs/HERMES_AUTONOMY_AREAS.md) — autonomia e gates por área
- [Autonomy Core](../axtro/README_AUTONOMY_CORE.md) — o enforcement em runtime

---

## O modelo

| Papel | Quem | Função |
|---|---|---|
| Cérebro operacional | **Hermes** | planeja, delega, executa skills, valida, relata, aprende, cria skills |
| Arquiteto de software | **Claude Code** | arquitetura, revisão ampla, refatoração grande |
| Engenheiro de código | **Codex** | tarefa fechada: bug, UI, script, teste |
| Departamentos | **Skills** | operações reais da empresa (voz, SDR, CRM, finanças, docs…) |
| Governança | **Autonomy Core** | decide o que roda sozinho e o que espera o humano; loga tudo |
| Aprovação | **Humano** | só ações sensíveis: dinheiro, comunicação externa real, produção, delete, chamada real |

**Regra de segurança central:** ação real na empresa acontece **só por skill via
`skill_runner`** — nunca direto por Claude Code ou Codex, que apenas produzem
artefatos (plano, código). Um único ponto de governança: o Autonomy Core.

---

## Como o Hermes opera a empresa (o loop)

`Planejar → Delegar → Executar → Validar → Relatar → Aprender → (criar skill)`

A cada passo o Hermes pergunta:
- é **operação da empresa**? → roda a **skill** pelo `skill_runner` (Autonomy Core decide o modo).
- preciso **pensar sistema / rever / refatorar grande**? → chama **Claude Code**.
- é **código fechado** (bug, UI, teste, script)? → chama **Codex**.
- a ação é **sensível** (dinheiro, envio real, produção, delete, chamada real)? → **para e pede gate humano**.

Tudo o mais flui sozinho. E o Hermes fecha o loop: se uma necessidade se repete,
ele **cria uma skill nova** (Claude Code desenha, Codex implementa, nasce com
`contract.json` e testes, `enabled:false` até validar).

### Exemplo ponta a ponta
"Prospectar 20 leads e preparar follow-up": scoring + enriquecimento rodam **sozinhos**
(read/medium) → Hermes valida a lista → o **envio real** da sequência é
`external_communication`, então roda em **dry-run** e **espera o Fernando aprovar** →
relatório: 20 leads, sequência pronta, aguardando aprovação. Zero dinheiro gasto, zero
mensagem real enviada sem "sim" — mas o trabalho pesado já está pronto.

---

## Estado real hoje (honesto)

O inventário cobre **duas frentes**:

| Frente | O que é | Nº | Estado |
|---|---|---|---|
| **Daemon governado** | skills ligadas no Autonomy Core (`GOVERNED_SKILLS.txt`) | **6** | live, enforcement em runtime |
| **Toolbelt nativo Nous** | skills do fork (claude-code, codex, github, creative, productivity…) | **71** | pass-through (não governado) |
| **Biblioteca Axtro (Wave-1)** | `~/Documents/Hermes Agent Axtro/` — departamentos de negócio | **52** | scaffolding: `ring 0`, `enabled:false`, **dry-run/prepare-only**, sem `risk_class` |

**Leitura:** o cérebro (Autonomy Core + skill_runner + logs) está **pronto e testado**
(35 testes verdes, red-team feito). As **6 skills governadas** já operam com trilhos.
As **52 skills de negócio** existem como catálogo Wave-1 — preparam ação real mas ainda
não executam (proibições estruturais em Stripe/GitHub/etc.). O toolbelt nativo (71) dá
capacidade imediata em engenharia, criativo e produtividade.

### O gap para "operar a empresa de verdade"
As 52 skills da biblioteca ainda **não** estão integradas ao Autonomy Core: vivem em
outra pasta, usam `autonomy_ring`+`write_policy` (não `risk_class`), e não estão em
`GOVERNED_SKILLS.txt`. Integrá-las é o próximo passo — e o [SKILL_MAP](../docs/HERMES_SKILL_MAP.md)
já traz a **classe de risco proposta** de cada uma (o campo a preencher).

---

## Governança — as regras que nunca quebram

Enforced em runtime pelo Autonomy Core (não é regra de papel):

🚫 não gastar sem aprovação · 🚫 não enviar comunicação externa real sem aprovação ·
🚫 não mexer em produção sem gate · 🚫 não expor secrets (fail-closed) · 🚫 não apagar
dados sem aprovação · 🚫 não fazer chamada real sem autorização · 🛑 kill switch global.

Gates: `HERMES_RING_GATE` (operacional) · `HERMES_HUMAN_APPROVAL` (sensível) · **token
fora-de-banda** (dinheiro) · `HERMES_KILL_SWITCH=on`. O red-team confirmou: todo caminho
**acidental** → nenhuma ação real; para dinheiro com grau adversarial, o token
fora-de-banda é o mecanismo (env-gate é a camada de acidente).

---

## Onde o Hermes já tem autonomia real (e onde espera o humano)

| Mais autonomia (roda sozinho) | Mais gate (espera humano) |
|---|---|
| Monitoring & Reports (read-only) | Finance (dinheiro → token fora-de-banda) |
| Análise de SDR/CRM/Marketing (score, rota, rascunho) | Voice AI (ligação/SMS real) |
| Engineering: plano, inspeção, teste local | Operations (provisão de acesso, registry, produção) |
| Documentation interna, criativos | Publicar/enviar/entregar externo · merge/deploy |

---

## Recomendações (próximos passos, em ordem)

1. **Dar `contract.json` ao `axtro-factory-monitor`** — hoje bloqueado por R1 (é a
   única governada sem contrato). Ganho imediato de monitoramento.
2. **Integrar a biblioteca por área, começando por Monitoring/Reports e SDR análise**
   (as de menor risco): atribuir `risk_class` (SKILL_MAP já propõe), adicionar em
   `GOVERNED_SKILLS.txt`, ligar `enabled:true` com testes. São as que dão mais
   autonomia com menos gate.
3. **Deixar Finance e Voice AI por último e sempre atrás de gate** — dinheiro via
   token fora-de-banda, telefonia via allowlist + aprovação.
4. **Padronizar o "criar skill nova"**: quando um padrão se repete, Hermes chama
   Claude Code (desenho) + Codex (código), gera contrato honesto, valida em dry-run,
   e só então liga. Assim os departamentos crescem sozinhos, dentro dos trilhos.

---

## Conclusão

O Hermes tem o cérebro (planejar/delegar/validar/relatar/aprender), a governança
(Autonomy Core, testado e red-teamed) e os braços (6 skills live + 52 no catálogo + 71
nativas). Ele **já opera** a empresa nas áreas read-only e de rascunho **sozinho**, e
**espera o Fernando** exatamente onde deve: dinheiro, comunicação externa real,
produção, delete, chamada real. O caminho para operar a empresa inteira é integrar a
biblioteca de 52 skills ao Autonomy Core, área por área, do menor risco ao maior —
sem nunca abrir mão dos gates. Poder de operar a empresa com inteligência, com
proteção mínima e inteligente.
