# CHECKLIST PARA O PRÓXIMO AGENTE — hermes-agent

> Este arquivo guia o próximo agente ou sessão a retomar o trabalho sem perder contexto.

---

## O que Ler Primeiro (Ordem)

1. **Este arquivo** (CHECKLIST_PROXIMO_AGENTE.md) — contexto rápido
2. **RISCOS_E_PENDENCIAS.md** — o que pode dar errado e o que está bloqueado
3. **STATUS_MIGRACAO.md** — o que foi feito e o que falta
4. **CONTEXTO_DO_PROJETO.md** — contexto técnico completo
5. **README.md** — documentação oficial upstream (para entender o produto)
6. **.env.example** — lista de todas as variáveis disponíveis (sem valores)
7. **pyproject.toml** — deps exatas e extras disponíveis

---

## Comandos Iniciais Seguros (copiar e colar)

Estes comandos são seguros para executar sem confirmação do Fernando:

```bash
# Verificar estado atual do projeto
cd /Users/fernandosilva/Developer/AxtroAI/00_INBOX_MIGRACAO/do-imac/software-house/lab/hermes-agent

# Verificar Python disponível
python3.11 --version
uv --version
node --version

# Verificar se .env foi criado
ls -la .env 2>/dev/null && echo "ENV EXISTE" || echo "ENV AUSENTE"

# Verificar se venv existe
ls -la .venv 2>/dev/null && echo "VENV EXISTE" || echo "VENV AUSENTE"

# Verificar node_modules
ls node_modules 2>/dev/null && echo "NODE_MODULES OK" || echo "NODE_MODULES AUSENTE"

# Verificar git status
git status && git log --oneline -5
```

---

## Ordem das Tarefas

### Fase 1 — Setup obrigatório (BLOQUEADO sem Fernando)
- [ ] Fernando cria .env com chaves reais (ver .env.example)
- [ ] Fernando decide: usar direto (upstream) ou criar fork Axtro?

### Fase 2 — Setup de ambiente (pode fazer o agente após .env existir)
- [ ] `uv venv --python 3.11 .venv`
- [ ] `source .venv/bin/activate`
- [ ] `uv pip install -e ".[all,dev]"`
- [ ] `npm install` (ou `npm run install:web && npm run install:tui`)

### Fase 3 — Validação
- [ ] `hermes --help` funciona
- [ ] `python -c "import hermes_cli; print('OK')"` sem erro
- [ ] `hermes setup` configura provider
- [ ] `hermes` abre TUI e responde

### Fase 4 — Deploy (somente se for usar em produção)
- [ ] Criar repo no GitHub (fork Axtro)
- [ ] Configurar variáveis no Railway
- [ ] `railway up` ou push para branch conectada ao Railway

---

## O que Validar Antes de Mexer no Código

1. Confirmar que .env existe e tem pelo menos um LLM provider
2. Confirmar que .venv está ativado (`which python` deve apontar para `.venv/bin/python`)
3. Confirmar que git remote é o correto (não fazer push para NousResearch)
4. Confirmar branch — se for trabalhar com customizações, criar branch própria a partir de `main`

```bash
# Validações rápidas
cat .env | grep -v "^#" | grep -v "^$" | wc -l  # conta linhas com valores
which python  # deve ser .venv/bin/python se venv ativo
git remote -v  # verificar para onde aponta
git branch  # confirmar branch atual
```

---

## O que Perguntar ao Fernando Antes de Executar

1. **"Quer criar um fork Axtro no GitHub ou usar o repositório upstream diretamente?"** — Isso define se podemos fazer customizações e push.

2. **"Qual API key de LLM vou usar como padrão? OpenRouter, Anthropic ou outra?"** — Necessário para criar o .env e testar.

3. **"Este projeto é para uso interno da Axtro, para um cliente específico ou para avaliação?"** — Define o nível de customização e deploy necessário.

4. **"Devo instalar os extras de mensageria (Telegram, Slack) agora ou só o core?"** — Afeta o tamanho da instalação e deps necessárias.

5. **"Tem alguma personalização do iMac que estava em andamento que não foi comittada?"** — O commit de backup é WIP, pode ter mudanças locais perdidas.

---

## O que Pode Ser Feito Automaticamente (sem confirmação)

- Ler qualquer arquivo do projeto (exceto .env preenchido)
- Criar/editar arquivos de documentação (.md)
- Rodar `git status`, `git log`, `git diff`
- Instalar dependências Python e Node (se .env não for necessário para o passo)
- Rodar testes que não precisam de API keys (`pytest -m "not integration"`)
- Verificar sintaxe e imports Python

---

## Como Continuar sem Perder Contexto

Este projeto usa o padrão Axtro de documentação em 4 arquivos. Ao retomar:

1. Ler este checklist primeiro
2. Marcar itens concluídos com `[x]`
3. Atualizar STATUS_MIGRACAO.md com o que foi feito
4. Atualizar RISCOS_E_PENDENCIAS.md se novos riscos forem descobertos

O estado do agente hermes fica em `~/.hermes/` (fora do repo), então não há estado de sessão dentro do projeto para verificar.

---

## Prompt Sugerido para o Próximo Agente Iniciar

Copie e cole este prompt ao iniciar uma nova sessão para este projeto:

---

```
Você está retomando o trabalho no projeto hermes-agent da Axtro AI.

Caminho: /Users/fernandosilva/Developer/AxtroAI/00_INBOX_MIGRACAO/do-imac/software-house/lab/hermes-agent

Este é um fork do hermes-agent do Nous Research (MIT), sendo avaliado/usado pela Axtro AI.
O projeto veio do iMac como backup em 2026-06-27.

ESTADO ATUAL:
- .env AUSENTE (precisa ser criado com API keys)
- .venv AUSENTE (precisa instalar dependências Python 3.11)
- node_modules AUSENTE (precisa npm install)
- Git remote aponta para NousResearch (upstream), não para Axtro
- Branch: backup/imac-migration-20260627-0020

LEIA ANTES DE AGIR:
1. CHECKLIST_PROXIMO_AGENTE.md (este arquivo)
2. RISCOS_E_PENDENCIAS.md
3. STATUS_MIGRACAO.md

REGRAS:
- Nunca ler/expor valores de .env ou secrets
- Nunca fazer push para origin (NousResearch)
- Nunca rodar deploy em produção sem confirmação do Fernando

Comece verificando o estado atual do ambiente e me diga o que está pronto e o que falta.
```
