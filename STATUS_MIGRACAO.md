# STATUS DE MIGRAÇÃO — hermes-agent

> Atualizado em: 2026-06-27 | Branch: backup/imac-migration-20260627-0020

---

## Origem

- **Veio do iMac?** Sim — o commit mais recente tem mensagem `chore: WIP backup before iMac migration`, indicando que foi feito backup do iMac antes da migração.
- **Commit de backup:** `501dd15 chore: WIP backup before iMac migration`

---

## Paths Antigos do iMac Encontrados

| Tipo | Detalhe |
|------|---------|
| Username antigo (`fernandosilva`) | **Nenhuma referência encontrada** nos arquivos .md, .yaml, .json, .toml, .txt rastreados |
| Paths absolutos `/Users/fernando*` antigos | Nenhum encontrado nos arquivos de config e docs |
| `.envrc` | Usa `watch_file` e `use flake` — sem paths absolutos do usuário |

**Conclusão:** Não foram encontradas referências hardcoded ao usuário antigo do iMac nos arquivos de configuração e documentação. O projeto é relativamente portável a nível de código.

---

## Paths Quebrados

| Item | Status |
|------|--------|
| `.venv` | **Ausente** — venv não foi incluído no backup (correto) |
| `node_modules` | **Ausente** — não foram incluídos no backup (correto) |
| `.env` | **Ausente** — não foi incluído no backup (correto por segurança) |
| `hermes_cli/web_dist/` | Provavelmente ausente (build artifact) — verificar |
| `hermes_cli/tui_dist/` | Provavelmente ausente (build artifact) — verificar |

---

## Dependências Faltando

| Dependência | Status | Ação Necessária |
|-------------|--------|----------------|
| Python venv (.venv) | Ausente | `uv venv --python 3.11 .venv` |
| Pacotes Python | Ausentes | `uv pip install -e ".[all]"` |
| node_modules (raiz) | Ausentes | `npm install` |
| node_modules (web/) | Ausentes | `npm run install:web` |
| node_modules (ui-tui/) | Ausentes | `npm run install:tui` |
| Python 3.11 | Disponível via brew/pyenv | Verificar: `python3.11 --version` |
| uv | Disponível em `/opt/homebrew/bin/uv` | OK |
| Node.js | Verificar versão | `node --version` (precisa >=20) |

---

## Git

| Item | Status |
|------|--------|
| Integridade do repo | OK — `git status` limpo |
| Branch atual | `backup/imac-migration-20260627-0020` — branch de backup, não main |
| Branch main | Existe localmente (`main`) |
| Remote `origin` | Aponta para `https://github.com/NousResearch/hermes-agent` (upstream externo) |
| Fork Axtro | **Ausente** — não existe repositório próprio da Axtro para este projeto |
| Commits locais além do upstream | 1 commit de backup (`501dd15`) que não existe no upstream |

**Risco:** Não temos remote próprio. Se quisermos trabalhar com customizações, precisamos criar fork.

---

## Python Local

- Python padrão do sistema: **3.9.6** (MacBook) — **incompatível** com hermes-agent (requer >=3.11)
- Python 3.11 disponível: **Sim** (`python3.11` encontrado)
- uv: instalado em `/opt/homebrew/bin/uv 0.11.25` — consegue baixar Python 3.11 automaticamente se necessário

---

## Projeto Roda no MacBook?

**Ainda não testado.** Baseado na inspeção:

- O código fonte está completo e íntegro
- Python 3.11 está disponível
- uv está instalado e funcional
- As dependências só precisam ser instaladas (`uv pip install`)
- Sem .env = sem API keys = agente vai iniciar mas não consegue chamar nenhum LLM

**Estimativa:** Com 30–60 minutos de setup, o projeto provavelmente roda localmente.

---

## O que Foi Corrigido Agora

- Nenhuma correção de código foi feita (não havia erros de path hardcoded para corrigir)
- Criados arquivos de documentação de handoff (CONTEXTO_DO_PROJETO.md, STATUS_MIGRACAO.md, CHECKLIST_PROXIMO_AGENTE.md, RISCOS_E_PENDENCIAS.md)

---

## O que Ainda Precisa Ser Corrigido

| Item | Prioridade | Responsável |
|------|------------|-------------|
| Criar .env com chaves reais | Alta | Fernando (manual) |
| Instalar venv Python 3.11 | Alta | Agente ou Fernando |
| Instalar node_modules | Alta | Agente ou Fernando |
| Criar fork Axtro no GitHub | Alta | Fernando (decisão de negócio) |
| Definir estratégia: uso direto vs customização | Alta | Fernando |
| Verificar se build dos frontends está presente | Média | Agente |
| Configurar Railway (variáveis de ambiente) | Média | Fernando |
| Testar funcionamento básico do agente | Média | Agente após .env |

---

## Comandos Já Executados

Nenhum comando de instalação foi executado. Apenas leitura e inspeção do projeto.

---

## Comandos que Precisam Ser Executados Manualmente pelo Fernando

Os comandos abaixo exigem decisão humana (criação de .env, escolha de API keys) ou acesso a serviços externos:

```bash
# 1. Copiar template de .env e preencher com chaves reais
cd /Users/fernandosilva/Developer/AxtroAI/00_INBOX_MIGRACAO/do-imac/software-house/lab/hermes-agent
cp .env.example .env
# Abrir .env e preencher pelo menos OPENROUTER_API_KEY

# 2. Criar fork no GitHub (via interface web ou gh CLI)
gh repo fork NousResearch/hermes-agent --org <nome-org-axtro> --clone=false
# Depois atualizar remote:
git remote set-url origin https://github.com/<org-axtro>/hermes-agent

# 3. Instalar ambiente Python (pode ser feito por agente também)
uv venv --python 3.11 .venv
source .venv/bin/activate
uv pip install -e ".[all,dev]"

# 4. Instalar dependências Node
npm install

# 5. Configurar provider e testar
hermes setup
```
