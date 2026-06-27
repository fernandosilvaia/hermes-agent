# CONTEXTO DO PROJETO — hermes-agent

> Documentação de handoff gerada em 2026-06-27 pela Axtro AI Factory.

---

## Resumo para entender em 5 minutos

**hermes-agent** é um agente de IA auto-aprendiz desenvolvido pelo **Nous Research** (organização externa, MIT license). Ele cria skills a partir da experiência, as melhora durante o uso e roda em qualquer lugar — local, Docker, SSH, Modal, Railway. Tem TUI (terminal), gateway de mensageria (Telegram, Slack, Discord, WhatsApp) e dashboard web. O projeto está aqui como **uso/integração pela Axtro** — não foi desenvolvido pela Axtro do zero.

**Situação atual:** o projeto veio do iMac como backup de trabalho. `.env` ausente, dependências não instaladas, remote git aponta para o fork upstream (NousResearch), não para um repo Axtro. Precisa de configuração inicial antes de rodar.

---

## Nome e Objetivo

- **Nome:** hermes-agent
- **Versão:** 0.17.0 (Python) / 1.0.0 (Node workspace)
- **Objetivo:** Agente de IA auto-aprendiz com loop de aprendizado fechado — cria e melhora skills autonomamente, roda com qualquer LLM provider, oferece interface TUI, gateway de mensageria multi-plataforma e deploy serverless.
- **Licença:** MIT (Nous Research)
- **Site upstream:** https://hermes-agent.nousresearch.com/

## Visão de Negócio (contexto Axtro)

O hermes-agent está sendo avaliado/usado pela Axtro AI como infraestrutura de agente para clientes. Pode servir como base para customizações de agentes autônomos nos projetos de transformação operacional da Axtro.

---

## Status Atual

| Item | Status |
|------|--------|
| Código fonte | Completo (fork do upstream) |
| Dependências Python (.venv) | Ausentes — precisam ser instaladas |
| Dependências Node (node_modules) | Ausentes — precisam ser instaladas |
| .env | Ausente — apenas .env.example existe |
| Git remote | Aponta para NousResearch (não Axtro) |
| Branch | backup/imac-migration-20260627-0020 |
| Deploy Railway | Configurado no railway.json — não testado localmente |
| Progresso estimado | ~20% (código presente, ambiente não configurado) |

---

## Stack Completa

### Backend (Python)
- **Linguagem:** Python 3.11 (requerido; 3.11–3.13, <3.14)
- **Gerenciador de pacotes:** uv (recomendado) ou pip
- **Framework principal:** Agente autônomo customizado (sem Django/Flask)
- **API web:** FastAPI + Uvicorn (para dashboard e gateway)
- **CLI:** python-fire + prompt_toolkit (TUI interativa)
- **LLM providers suportados:** OpenRouter, NovitaAI, Google/Gemini, Ollama, OpenAI, Anthropic (via extra), MiniMax, Kimi/Moonshot, HuggingFace, Bedrock (AWS), Azure
- **Scheduler:** croniter (built-in)
- **Mensageria:** Telegram, Slack, Discord, WhatsApp (Baileys), Microsoft Teams, Matrix, WeChat
- **Banco:** Sem banco central — usa arquivos locais + SQLite opcional (Matrix/aiosqlite)
- **Auth:** Gateway tem allowlist de users por plataforma
- **Logging:** hermes_logging.py com rotação de arquivo

### Frontend / UI
- **TUI:** ui-tui (React + Node.js, pasta separada)
- **Dashboard web:** web/ (React + Vite + TypeScript)
- **Desktop app:** apps/desktop/
- **Framework UI:** React (workspace npm)
- **Node.js:** >=20.0.0 requerido

### Deploy
- **Docker:** Dockerfile presente (Debian 13 Trixie + Python 3.13 + Node 22)
- **Docker Compose:** docker-compose.yml e docker-compose.windows.yml
- **Railway:** railway.json configurado (builder: DOCKERFILE, start: `gateway run`)
- **Serverless:** Suporte a Modal e Daytona como backends de terminal
- **Nix:** flake.nix presente (ambiente reproduzível)

---

## Integrações Externas

| Serviço | Uso | Variável de Ambiente |
|---------|-----|---------------------|
| OpenRouter | LLM provider primário (200+ modelos) | `OPENROUTER_API_KEY` |
| Anthropic | LLM provider opcional (Claude) | via extra `anthropic` + provider config |
| Google/Gemini | LLM provider | `GOOGLE_API_KEY` / `GEMINI_API_KEY` |
| OpenAI | LLM provider + Whisper STT + TTS | `VOICE_TOOLS_OPENAI_KEY` |
| Exa | Busca web AI-native | `EXA_API_KEY` |
| Firecrawl | Web scraping | `FIRECRAWL_API_KEY` |
| Parallel.ai | Busca web | `PARALLEL_API_KEY` |
| FAL.ai | Geração de imagens | `FAL_KEY` |
| Browserbase | Automação de browser remota | `BROWSERBASE_API_KEY`, `BROWSERBASE_PROJECT_ID` |
| Telegram | Gateway de mensagens | `TELEGRAM_BOT_TOKEN` |
| Slack | Gateway de mensagens | `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN` |
| Discord | Gateway de mensagens | via extra messaging |
| WhatsApp | Gateway via Baileys | `WHATSAPP_ENABLED` |
| GitHub | Skills Hub (rate limit) | `GITHUB_TOKEN` |
| Groq | STT Whisper cloud | `GROQ_API_KEY` |
| ElevenLabs | TTS premium | `ELEVENLABS_API_KEY` |
| Honcho | Modelagem de usuário cross-sessão | `HONCHO_API_KEY` |
| AWS Bedrock | LLM provider | via extra `bedrock` |
| Azure | LLM + identidade | via extra `azure-identity` |
| Modal | Backend de terminal serverless | auth via CLI (`modal setup`) |
| Novita.ai | LLM provider | `NOVITA_API_KEY` |
| Hugging Face | LLM via inference providers | `HF_TOKEN` |

---

## Estrutura de Pastas

```
hermes-agent/
├── agent/              # Runtime do agente — loop, adapters de LLM, context engine
├── tools/              # Todas as ferramentas disponíveis ao agente (browser, terminal, etc.)
├── gateway/            # Gateway de mensageria multi-plataforma (Telegram, Slack, Discord...)
├── hermes_cli/         # CLI interativa e setup wizard
├── tui_gateway/        # Gateway TUI (terminal UI)
├── ui-tui/             # Frontend React da TUI (npm workspace)
├── web/                # Dashboard web (React + Vite)
├── apps/               # Aplicativos adicionais (desktop, bootstrap-installer)
├── skills/             # Skills built-in (apple, computer-use, github, media, etc.)
├── optional-skills/    # Skills opcionais (blockchain, produtividade, ML, etc.)
├── plugins/            # Plugins (browser, cron, dashboard, kanban, memory...)
├── optional-mcps/      # Catálogo de MCPs opcionais (linear, n8n)
├── providers/          # Adapters de providers LLM
├── cron/               # Scheduler de crons
├── acp_adapter/        # ACP (Agent Communication Protocol) adapter
├── acp_registry/       # Registro ACP
├── tests/              # Testes automatizados (pytest)
├── docs/               # Documentação técnica
├── website/            # Docs/site público
├── docker/             # Scripts de container (s6-overlay, entrypoints)
├── scripts/            # Scripts de instalação e utilitários
├── locales/            # i18n (YAML)
├── hermes_constants.py # Constantes globais
├── hermes_state.py     # Estado global do agente
├── hermes_logging.py   # Logging centralizado
├── run_agent.py        # Entrypoint principal
├── cli.py              # CLI alternativa
├── pyproject.toml      # Metadados e deps Python
├── package.json        # Workspace npm raiz
├── Dockerfile          # Build para deploy
├── railway.json        # Config de deploy Railway
├── setup-hermes.sh     # Script de setup para dev
└── .env.example        # Template de variáveis de ambiente
```

---

## Scripts Disponíveis (npm)

```json
"install:root"     // npm install --workspaces=false
"install:web"      // npm install --workspace web
"install:tui"      // npm install --workspace ui-tui
"install:desktop"  // npm install --workspace apps/desktop
"audit:root"       // npm audit --workspaces=false
"audit:web"        // npm audit --workspace web
"audit:tui"        // npm audit --workspace ui-tui
```

Scripts Python (via `hermes` CLI ou direto):
```bash
hermes              # CLI interativa principal
hermes-agent        # run_agent.py direto
hermes setup        # wizard de configuração
hermes model        # mudar modelo LLM
hermes tools        # gerenciar ferramentas/extras
gateway run         # iniciar gateway de mensageria (usado no Railway)
```

---

## Como Rodar Localmente (Passo a Passo)

### Pré-requisitos
- Python 3.11 (disponível em `/usr/local/bin/python3.11` ou via pyenv/asdf)
- uv instalado (`/opt/homebrew/bin/uv` no MacBook)
- Node.js >=20.0.0
- Git

### 1. Configurar ambiente Python

```bash
cd /Users/fernandosilva/Developer/AxtroAI/00_INBOX_MIGRACAO/do-imac/software-house/lab/hermes-agent

# Criar venv com Python 3.11
uv venv --python 3.11 .venv

# Ativar venv
source .venv/bin/activate

# Instalar dependências principais
uv pip install -e ".[all]"

# Para desenvolvimento:
uv pip install -e ".[all,dev]"

# Alternativa: usar setup-hermes.sh
./setup-hermes.sh
```

### 2. Configurar .env

```bash
cp .env.example .env
# Editar .env e preencher pelo menos OPENROUTER_API_KEY (ou outro provider)
```

### 3. Instalar dependências Node.js (para TUI/dashboard)

```bash
npm install
# ou por workspace:
npm run install:web
npm run install:tui
```

### 4. Rodar o agente

```bash
# CLI interativa
hermes

# Ou via Python direto
python run_agent.py

# Gateway (Telegram/Slack/etc)
python -m gateway run
```

---

## Como Rodar Testes

```bash
# Ativar venv
source .venv/bin/activate

# Rodar testes unitários (sem testes de integração)
pytest

# Rodar um teste específico
pytest tests/agent/test_context_engine.py

# Testes de integração (requerem API keys reais)
pytest -m integration
```

---

## Como Fazer Build

### Docker (recomendado para deploy)

```bash
# Build da imagem
docker build -t hermes-agent .

# Ou com docker-compose
docker-compose up --build
```

### Build dos frontends

```bash
# Dashboard web
cd web && npm run build

# TUI
cd ui-tui && npm run build
```

---

## Como Fazer Deploy (Railway)

O deploy é via Dockerfile. O `railway.json` configura:
- Builder: DOCKERFILE
- Start command: `gateway run`
- Health check: `/health`

```bash
# Via Railway CLI (sem expor secrets)
railway up

# Variáveis de ambiente devem ser configuradas no painel Railway
# NÃO commitar .env no repositório
```

---

## Variáveis de Ambiente Necessárias (apenas nomes)

### LLM Provider (mínimo um obrigatório)
- `OPENROUTER_API_KEY`
- `GOOGLE_API_KEY` / `GEMINI_API_KEY`
- `NOVITA_API_KEY`
- `OLLAMA_API_KEY`
- `HF_TOKEN`

### Ferramentas (opcionais)
- `EXA_API_KEY`
- `FIRECRAWL_API_KEY`
- `PARALLEL_API_KEY`
- `FAL_KEY`
- `BROWSERBASE_API_KEY`
- `BROWSERBASE_PROJECT_ID`
- `VOICE_TOOLS_OPENAI_KEY`
- `GROQ_API_KEY`
- `ELEVENLABS_API_KEY`
- `HONCHO_API_KEY`
- `GITHUB_TOKEN`

### Mensageria (conforme plataformas usadas)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_ALLOWED_USERS`
- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`
- `WHATSAPP_ENABLED`

### Terminal
- `TERMINAL_TIMEOUT` (default: 60)
- `TERMINAL_LIFETIME_SECONDS` (default: 300)
- `BROWSER_SESSION_TIMEOUT` (default: 300)

### Debug
- `WEB_TOOLS_DEBUG`
- `VISION_TOOLS_DEBUG`
- `MOA_TOOLS_DEBUG`
- `IMAGE_TOOLS_DEBUG`

---

## Pontos Críticos

1. **Python 3.11 obrigatório** — o sistema tem 3.9.6 como padrão, mas 3.11 está disponível via pyenv/homebrew. uv gerencia isso automaticamente se configurado corretamente.
2. **Remote git errado** — aponta para NousResearch. Para customizações Axtro, criar fork em repositório próprio.
3. **Sem banco de dados central** — estado em arquivos locais. Para deploy cloud (Railway), configurar volumes persistentes ou usar backends compatíveis.
4. **Extras lazy-installed** — muitas deps são instaladas sob demanda no primeiro uso (ex: anthropic, telegram, discord). Isso pode falhar em ambientes sem internet ou pip.
5. **s6-overlay no Docker** — supervisão de processos complexa no container; não tentar substituir por abordagem simples sem entender a arquitetura.

---

## Riscos de Segurança Conhecidos

- `.env` com chaves em plaintext — nunca commitar
- `SUDO_PASSWORD` pode ser armazenada em plaintext no .env
- `GATEWAY_ALLOW_ALL_USERS=true` abre o bot para qualquer pessoa
- Supply-chain: projeto já sofreu ataque via `mistralai 2.4.6` (registrado nos comentários do pyproject.toml); todas as deps são exact-pinned
- Starlette CVE-2026-48710 (BadHost) — mitigado nas versões pinadas
- Browserbase pode expor dados de navegação se mal configurado

---

## Bugs Conhecidos (upstream)

- pydantic-core 2.41.5 causava segfault em threads não-main (corrigido no pin atual 2.46.4)
- Log rotation no Windows falhava com PermissionError (corrigido com concurrent-log-handler)
- `os.kill(pid, 0)` silencioso no Windows — documentado no CONTRIBUTING.md
- `RotatingFileHandler` incompatível com múltiplos processos no Windows

---

## Dívidas Técnicas

- Node.js workspaces não instalados (node_modules ausente)
- Python venv não criado (precisa bootstrap inicial)
- Python padrão do sistema (3.9.6) incompatível — exige uso explícito do 3.11
- Remote git aponta para upstream externo, não para repositório Axtro
- Branch de trabalho é um backup, não main

---

## Próximas Tarefas Recomendadas

1. Criar fork do repositório em conta Axtro no GitHub
2. Configurar remote para apontar para fork Axtro
3. Criar .env a partir do .env.example
4. Instalar dependências Python com `uv venv --python 3.11 .venv && source .venv/bin/activate && uv pip install -e ".[all]"`
5. Instalar dependências Node.js com `npm install`
6. Rodar `hermes setup` para configurar provider e preferências
7. Testar funcionamento básico com `hermes`
8. Definir estratégia de customização (fork vs uso direto)

---

## O que NÃO Fazer

- Nunca fazer push para `origin` (NousResearch) — não temos permissão e contaminaria o upstream
- Não rodar `uv pip install` com Python 3.9 — as deps requerem >=3.11
- Não expor `SUDO_PASSWORD` ou `BROWSERBASE_API_KEY` em logs ou commits
- Não usar `GATEWAY_ALLOW_ALL_USERS=true` em produção sem entender as implicações
- Não modificar `uv.lock` manualmente — regenerar com `uv lock`
- Não commitar `.env` preenchido

---

## Como Validar se Está Funcionando

```bash
# 1. Verificar instalação Python
source .venv/bin/activate
python -c "import hermes_cli; print('OK')"

# 2. Verificar CLI
hermes --help

# 3. Testar com um provider configurado
hermes  # deve abrir TUI

# 4. Verificar gateway (se configurado)
python -m gateway run --help

# 5. Verificar dashboard web
cd web && npm run dev  # abre em localhost
```
