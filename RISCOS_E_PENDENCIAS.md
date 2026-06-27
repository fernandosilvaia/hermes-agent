# RISCOS E PENDÊNCIAS — hermes-agent

> Atualizado em: 2026-06-27

---

## Riscos Bloqueantes (impedem uso em produção)

| # | Risco | Impacto | Status |
|---|-------|---------|--------|
| R1 | **.env ausente** — sem API keys configuradas, o agente não consegue chamar nenhum LLM | Total — agente não funciona | Pendente |
| R2 | **Remote git aponta para NousResearch** — qualquer `git push` acidental vai para o upstream externo | Exposição de customizações Axtro ou rejeição por falta de permissão | Pendente |
| R3 | **Python venv não instalado** — `import hermes_cli` falha, nenhum comando `hermes` disponível | Total — agente não inicia | Pendente |
| R4 | **Python 3.9.6 é o padrão do sistema** — incompatível com o requisito >=3.11 do projeto | Build e imports falham se venv não for criado com 3.11 explicitamente | Pendente |

---

## Riscos Médios

| # | Risco | Impacto | Status |
|---|-------|---------|--------|
| R5 | **node_modules ausentes** — TUI e dashboard web não funcionam | UI indisponível; CLI Python ainda funciona | Pendente |
| R6 | **Branch backup, não main** — a branch `backup/imac-migration-20260627-0020` contém 1 commit a mais que o upstream; sem PR ou merge, pode ser esquecida | Perda de contexto ou conflito futuro | Pendente |
| R7 | **Sem fork Axtro no GitHub** — customizações ficam apenas local; sem backup remoto próprio | Risco de perda se MacBook falhar | Pendente |
| R8 | **Extras lazy-installed** — deps como `anthropic`, `telegram`, `discord` são instaladas sob demanda no primeiro uso; ambientes sem internet ou pip restrito vão falhar silenciosamente | Features opcionais indisponíveis em ambiente restrito | A monitorar |
| R9 | **Builds de frontend ausentes** (`hermes_cli/web_dist/`, `hermes_cli/tui_dist/`) — não confirmado se foram gerados; `hermes dashboard` pode não funcionar sem o build | Dashboard indisponível | A verificar |

---

## Riscos Baixos

| # | Risco | Impacto | Status |
|---|-------|---------|--------|
| R10 | **`.envrc` usa `use flake`** — requer Nix + direnv para funcionar automaticamente; sem Nix no MacBook, o .envrc é ignorado | Apenas conveniência afetada; setup manual funciona | Informacional |
| R11 | **Projeto é upstream externo (Nous Research)** — updates do upstream podem conflitar com customizações Axtro se feitas diretamente no repo | Manutenção de longo prazo mais complexa | A planejar |
| R12 | **Sem testes de integração configurados localmente** — os testes de integração requerem API keys reais e serviços externos | Cobertura de testes limitada sem ambiente completo | A planejar |

---

## Problemas de Segurança

| Problema | Detalhe | Mitigação |
|----------|---------|-----------|
| Secrets em .env plaintext | Padrão do projeto — `SUDO_PASSWORD`, API keys ficam em arquivo texto | Nunca commitar .env; usar Railway secrets/env vars no deploy |
| `GATEWAY_ALLOW_ALL_USERS=true` | Se ativado, qualquer pessoa pode usar o bot | Manter `false` (default) em produção; usar allowlists por usuário |
| Supply-chain: deps exact-pinned | O projeto adotou pins exatos após ataque `mistralai 2.4.6` (Mai/2026) | Ao atualizar deps, verificar changelogs; regenerar `uv.lock` |
| CVE-2026-48710 (Starlette BadHost) | Mitigado via pin `starlette==1.0.1` | Manter pin; não downgrade |
| CVE-2026-34450/34452 (anthropic SDK) | Mitigado via pin `anthropic==0.87.0` | Manter pin atualizado |
| Browserbase: dados de navegação | O agente pode navegar em sites com dados sensíveis via Browserbase | Só ativar se necessário; revisar permissões de uso |
| GitHub App Private Key | `GITHUB_APP_PRIVATE_KEY_PATH` — se configurado, proteger o arquivo da chave | Permissões 600 no arquivo; nunca commitar |

---

## Problemas de Deploy

| Problema | Detalhe | Solução |
|----------|---------|---------|
| Railway sem variáveis configuradas | O `railway.json` está pronto, mas sem env vars no painel Railway o deploy vai falhar na inicialização | Configurar vars no painel Railway antes do primeiro deploy |
| Healthcheck timeout 600s | `healthcheckTimeout: 600` pode mascarar falhas de inicialização lentas | Monitorar logs de deploy; verificar `/health` endpoint |
| Volumes de estado | Hermes salva estado em `~/.hermes/` e logs em `logs/` — no Railway, esses dados são efêmeros sem volume persistente | Configurar volume Railway montado em `/opt/data` (padrão do Dockerfile) |
| Docker build multi-arch | Dockerfile usa `TARGETARCH` para BuildKit multi-arch; build local simples pode não funcionar em M-series Mac sem emulação | Usar `docker buildx build --platform linux/amd64` para build de produção |

---

## Problemas de Banco / Migrations

| Problema | Detalhe |
|----------|---------|
| Sem banco relacional central | O projeto não usa PostgreSQL/MySQL no core; estado é baseado em arquivos |
| SQLite (Matrix/aiosqlite) | O extra `matrix` usa SQLite para armazenar estado de criptografia E2E — sem migration formal |
| AsyncPG (Matrix) | O extra `matrix` suporta PostgreSQL via asyncpg — configuração manual |
| Sem ORM / migration system | Não há Alembic ou Django migrations — mudanças de schema são manuais |

---

## Problemas de Autenticação

| Problema | Detalhe |
|----------|---------|
| Gateway auth por allowlist | Cada plataforma (Telegram, Slack, etc.) tem sua própria allowlist de user IDs — precisa ser populada manualmente no .env |
| GitHub App JWT | Se usar bot identity do Skills Hub, precisa de `GITHUB_APP_ID`, `GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_APP_INSTALLATION_ID` |
| Modal auth | Usa CLI auth via `modal setup` — não tem variável de env; precisa de sessão interativa para configurar |
| Google Chat | Usa Service Account JSON — arquivo de chave externo, não env var simples |

---

## Problemas de .env

| Problema | Detalhe |
|----------|---------|
| **.env ausente** | O arquivo não existe — apenas .env.example. Bloqueante. |
| Muitas vars opcionais | .env.example tem ~100 variáveis comentadas — pode confundir na hora de preencher |
| Vars movidas para config.yaml | `LLM_MODEL` não é mais lido do .env (agora em `~/.hermes/config.yaml`); documentação pode estar desatualizada |
| `TERMINAL_MODAL_IMAGE` com valor padrão | .env.example já tem `TERMINAL_MODAL_IMAGE=nikolaik/python-nodejs:python3.11-nodejs20` preenchido — é seguro |

---

## Problemas de Dependências

| Problema | Detalhe |
|----------|---------|
| Python 3.9.6 no sistema | MacBook tem 3.9.6 como padrão; incompatível. Usar `uv venv --python 3.11` explicitamente |
| node_modules ausentes | `npm install` precisa ser rodado na raiz (workspace) |
| matrix extra incompatível com macOS moderno | `python-olm` (dep do extra matrix) requer compilação nativa — sem `libolm` no macOS pode falhar |
| voice extra (faster-whisper) | Depende de `ctranslate2` e `onnxruntime` — wheels wheel-only; pode falhar em arm64 |
| Extras lazy-installed em produção | Primeiro uso de feature que lazy-instala pode demorar ou falhar; considerar pré-instalação no Dockerfile |

---

## Pendências de Produto

| Pendência | Prioridade |
|-----------|------------|
| Definir quais skills/ferramentas serão usadas pela Axtro | Alta |
| Customizar prompt/persona do agente para contexto Axtro | Alta |
| Definir plataformas de mensageria para integrar (Telegram? Slack?) | Média |
| Avaliar se features de self-improvement devem ser habilitadas | Média |
| Definir se usa Honcho (modelagem de usuário cross-sessão) | Baixa |
| Avaliar features de cron scheduling para casos Axtro | Baixa |

---

## Pendências de Negócio

| Pendência | Prioridade |
|-----------|------------|
| Decisão: uso interno vs produto para cliente | Alta |
| Criar fork no GitHub (organização Axtro) | Alta |
| Definir estratégia de manutenção (sync com upstream ou freeze) | Alta |
| Definir responsável técnico pelo projeto | Média |
| Documentar qual cliente/projeto vai usar este agente (se aplicável) | Média |
| Avaliar licença MIT para customizações comerciais | Baixa |

---

## Tabela de Prioridade de Correção

| Prioridade | Item | Responsável | Estimativa |
|------------|------|-------------|------------|
| P0 — Hoje | Criar .env com API key de LLM | Fernando | 15 min |
| P0 — Hoje | Instalar venv Python 3.11 e deps | Agente (após .env) | 20 min |
| P0 — Hoje | Definir fork vs uso direto | Fernando | 5 min |
| P1 — Esta semana | Instalar node_modules (UI) | Agente | 10 min |
| P1 — Esta semana | Criar fork Axtro no GitHub | Fernando | 15 min |
| P1 — Esta semana | Testar funcionamento básico | Agente | 30 min |
| P2 — Próximas semanas | Configurar Railway com vars | Fernando | 30 min |
| P2 — Próximas semanas | Definir customizações Axtro | Fernando + Agente | TBD |
| P3 — Backlog | Sync strategy com upstream | Equipe técnica | TBD |
| P3 — Backlog | Avaliação de matrix extra no macOS | Agente | 2h |
