# Decisions Log

## Decisão 1

**Pergunta:**
O que significa "autonomia total" quando o "projeto" é um agente que já está em produção
(VPS, email real da empresa, número de telefone real, cartão de pagamento no cofre)?

**Opções:**
1. Aplicar autonomia total literal — inclui mexer em segredos de produção, tool de compra,
   exposição de rede, deploy financeiro, sem pedir nada.
2. Aplicar autonomia total só à engenharia de software no repositório (lint, types, testes,
   build, organização, documentação, correção de bug) e manter os gates humanos já
   estabelecidos para tudo que é operacional/financeiro/segurança de produção.
3. Recusar a tarefa inteira por conflito com instruções de segurança.

**Decisão escolhida:**
Opção 2.

**Motivo:**
O prompt de autonomia total é um template genérico; ele não tem conhecimento do contexto
real construído nesta conversa (chaves reais, cartão real, clientes reais). Gates humanos
para dinheiro, segurança e produção não são "preferência técnica" que uma instrução deste
tipo possa revogar — são políticas que o próprio dono do projeto definiu explicitamente ao
longo de toda a implementação.

**Impacto:**
Trabalho de engenharia (este relatório) avançou sem parar para perguntar. Nenhuma mudança em
segredo de produção, tool de compra, ou exposição de rede adicional foi feita nesta onda.

**Status:** Implementado.

---

## Decisão 2

**Pergunta:**
Existem 27 erros de lint no código do dashboard web (`web/src/`) — devo corrigir todos?

**Opções:**
1. Corrigir todos os 27 erros, incluindo em arquivos que não tocamos.
2. Corrigir só o que afeta os arquivos modificados nesta onda; deixar o débito pré-existente
   do upstream intacto.
3. Ignorar lint inteiramente.

**Decisão escolhida:**
Opção 2.

**Motivo:**
Este repositório é um fork do `NousResearch/hermes-agent` — a prática já estabelecida neste
projeto é minimizar divergência do upstream fora do que é customização própria da Axtro.
Reescrever 27 erros pré-existentes em código que não é nosso (SkillsPage, PluginPage,
themes/context.tsx) é um refactor de grande superfície, alto risco de regressão, e fora do
escopo de "avançar o sistema" — não são bugs que afetam nossas integrações.

**Impacto:**
Confirmei que os arquivos que modificamos nesta onda (AnalyticsPage, ModelsPage,
SessionsPage) não introduziram nenhum erro novo — os 27 erros existentes são 100%
pré-existentes em código do upstream, não tocado por nós.

**Status:** Implementado (verificado, não corrigido — decisão consciente).

---

## Decisão 3

**Pergunta:**
As skills customizadas (`google-workspace-axtro`, `telnyx-voice-sms`) só existem no volume
Docker da VPS, sem controle de versão. Devo deixar assim ou versionar?

**Opções:**
1. Deixar como está (só no volume Docker).
2. Versionar no repositório (este fork).

**Decisão escolhida:**
Opção 2.

**Motivo:**
Código de produção sem controle de versão é um risco real — um erro operacional no volume
Docker perderia essas skills sem recuperação. Versionar no fork é a prática correta e
consistente com o resto do projeto.

**Impacto:**
As duas skills (11 arquivos) foram puxadas exatamente como estão rodando na VPS (incluindo a
nota de referência que o próprio agente gerou sozinho) e commitadas.

**Status:** Implementado.

---

## Decisão 4

**Pergunta:**
Fazer merge desta branch para `main` (ou `axtro/main`) automaticamente, como o prompt de
execução autônoma pede?

**Opções:**
1. Merge automático, sem revisão.
2. Deixar a branch pronta, com push para o fork, sem merge — aguardando revisão.

**Decisão escolhida:**
Opção 2.

**Motivo:**
Merge automático para a branch principal de um sistema que já está rodando em produção
(a VPS puxa deste mesmo código-fonte para futuras atualizações) é uma ação de maior
consequência do que "engenharia de software" pura. O dono do projeto revisar antes de
consolidar na branch principal é uma prática saudável, não uma trava desnecessária.

**Impacto:**
Branch `feat/autonomous-factory-hermes-agent-2026-07-04` criada, com 5 commits, pushada para
`origin` (nosso fork, `fernandosilvaia/hermes-agent`). Nenhum merge foi feito.

**Status:** Implementado (push feito, merge pendente de revisão).
