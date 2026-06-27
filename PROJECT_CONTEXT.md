# PROJECT_CONTEXT — hermes-agent

> Gerado/atualizado automaticamente pela auditoria da Axtro AI Factory em 2026-06-27 08:21.> Use apenas como contexto operacional inicial. Campos marcados como "A confirmar" precisam de validacao humana.

## Identidade

| Campo | Valor |
|---|---|
| Nome | hermes-agent |
| Caminho | `lab/hermes-agent` |
| Status inferido | Laboratório/terceiro |
| Prioridade inicial | P3 |
| Stack provável | Vite, React, TypeScript, Python, Docker |

## Objetivo

A confirmar a partir de briefing/produto. Inferências abaixo foram feitas somente por arquivos existentes.

## Evidências encontradas

### Arquivos e marcadores técnicos
- `package.json`
- `package-lock.json`
- `pyproject.toml`
- `Dockerfile`
- `docker-compose.yml`
- `.github/workflows`

### Documentos relevantes
- README.md: Hermes Agent ☤
- AGENTS.md: Hermes Agent - Development Guide
- CONTEXTO_DO_PROJETO.md: CONTEXTO DO PROJETO — hermes-agent
- RISCOS_E_PENDENCIAS.md: RISCOS E PENDÊNCIAS — hermes-agent

### Componentes/subprojetos detectados
- `apps/bootstrap-installer`
- `apps/desktop`
- `apps/shared`
- `optional-skills/finance/dcf-model`
- `plugins/platforms/photon/sidecar`
- `scripts/whatsapp-bridge`
- `tests/e2e/matrix_xsign_bootstrap`
- `ui-tui`
- `ui-tui/packages/hermes-ink`
- `web`
- `website`

## Git

| Campo | Valor |
|---|---|
| Git local | Sim |
| Branch atual | `backup/imac-migration-20260627-0020` |
| Remote | `origin	https://github.com/NousResearch/hermes-agent (fetch)` |
| Estado | `?? CHECKLIST_PROXIMO_AGENTE.md
?? CONTEXTO_DO_PROJETO.md
?? RISCOS_E_PENDENCIAS.md
?? STATUS_MIGRACAO.md` |

## Variáveis de ambiente

Somente nomes de variáveis foram inferidos. Valores reais nao foram lidos nem copiados.

- `lab/hermes-agent/.envrc`: nomes nao inferidos
- `lab/hermes-agent/.env.example`: `BROWSERBASE_ADVANCED_STEALTH`, `BROWSERBASE_PROXIES`, `BROWSER_INACTIVITY_TIMEOUT`, `BROWSER_SESSION_TIMEOUT`, `IMAGE_TOOLS_DEBUG`, `MOA_TOOLS_DEBUG`, `TERMINAL_LIFETIME_SECONDS`, `TERMINAL_MODAL_IMAGE`, `TERMINAL_TIMEOUT`, `VISION_TOOLS_DEBUG`, `WEB_TOOLS_DEBUG`

## Comandos principais

- `lab/hermes-agent/package.json` (`hermes-agent`): `audit:fix:root`, `audit:fix:tui`, `audit:fix:web`, `audit:root`, `audit:tui`, `audit:web`, `install:desktop`, `install:root`, `install:tui`, `install:web`, `postinstall`
- `lab/hermes-agent/ui-tui/package.json` (`hermes-tui`): `build`, `dev`, `fix`, `fmt`, `lint`, `lint:fix`, `start`, `test`, `test:watch`, `typecheck`
- `lab/hermes-agent/ui-tui/packages/hermes-ink/package.json` (`@hermes/ink`): `build`
- `lab/hermes-agent/plugins/platforms/photon/sidecar/package.json` (`@hermes-agent/photon-sidecar`): `postinstall`, `start`
- `lab/hermes-agent/web/package.json` (`web`): `build`, `dev`, `lint`, `preview`, `test`, `typecheck`
- `lab/hermes-agent/website/package.json` (`website`): `build`, `clear`, `deploy`, `docusaurus`, `lint:diagrams`, `prebuild`, `prestart`, `serve`, `start`, `swizzle`, `typecheck`, `write-heading-ids`, `write-translations`
- `lab/hermes-agent/scripts/whatsapp-bridge/package.json` (`hermes-whatsapp-bridge`): `start`
- `lab/hermes-agent/apps/bootstrap-installer/package.json` (`@hermes/bootstrap-installer`): `build`, `dev`, `preview`, `tauri`, `tauri:build`, `tauri:build:debug`, `tauri:dev`, `typecheck`
- `lab/hermes-agent/apps/desktop/package.json` (`hermes`): `build`, `builder`, `dev`, `dev:electron`, `dev:fake-boot`, `dev:renderer`, `dist`, `dist:linux`, `dist:mac`, `dist:mac:dmg`, `dist:mac:zip`, `dist:win`, `dist:win:msi`, `dist:win:nsis`, `fix`, `fmt`, `lint`, `lint:fix`, `pack`, `postbuild`, `prebuilder`, `preview`, `profile:main`, `profile:main:cpu`, `start`, `test:desktop`, `test:desktop:all`, `test:desktop:dmg`, `test:desktop:existing`, `test:desktop:fresh`, `test:desktop:nsis`, `test:desktop:platforms`, `test:ui`, `typecheck`
- `lab/hermes-agent/apps/shared/package.json` (`@hermes/shared`): `typecheck`

## Funcionalidades principais

A confirmar. Consulte os documentos existentes listados acima e o codigo do projeto.

## Integrações

A confirmar. Sinais inferidos por dependencias/arquivos: Vite, React, TypeScript, Python, Docker.

## Riscos e pendências

- Mudanças locais pendentes
- PROJECT_CONTEXT.md ausente

## Próximos passos seguros

1. Confirmar objetivo e status real do projeto com Fernando.
2. Rodar verificações locais seguras ja declaradas nos scripts, sem deploy e sem chamadas pagas.
3. Completar este contexto com links de deploy, responsavel, ambiente e regras de negocio.
4. Corrigir primeiro itens P3 antes de novas features.

## Regras para agentes

- Nao ler nem imprimir valores de `.env`.
- Nao fazer push, deploy, merge ou migrations sem autorizacao explicita.
- Preservar mudancas locais existentes.
- Preferir correcoes pequenas, testadas e documentadas.
