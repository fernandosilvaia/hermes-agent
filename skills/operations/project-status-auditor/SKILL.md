---
name: project-status-auditor
description: "Raio-X read-only dos repositórios da House: branch, mudanças não commitadas, commits não pushados, projetos parados. Use quando perguntarem 'como estão os projetos?', 'o que está parado?', 'tem coisa não pushada?', ou num cron diário."
version: 1.0.0
author: Axtro AI
license: MIT
platforms: [macos, linux]
dependencies: []
metadata:
  hermes:
    tags: [Axtro, AgentOps, Git, CTO, Projetos]
    related_skills: [daily-ceo-report, axtro-factory-monitor]
---

# Project Status Auditor

> **Sobreposição conhecida com `axtro-factory-monitor`:** ambas varrem git dos repos da
> House. Esta skill é o raio-X **minimalista e rápido** (só git, pensado pra alimentar o
> `daily-ceo-report` ou ser chamado via `ask-vps-hermes` quando o pedido vem da VPS). A
> `axtro-factory-monitor` é o **briefing consolidado** (git + prazos + segredo vazado +
> lint + inbox), agendado, entregue no Telegram. Ainda não foram fundidas — se for mexer,
> avise antes.

Varre os repositórios da House e reporta o estado de cada um **sem tocar em nada** — só
lê o git local. É os "olhos" do Axtro Agent sobre a produção: quais projetos estão sujos,
com trabalho não pushado, parados há dias, ou fora de uma branch. Anel 0, zero credencial.

Roda no **MacBook** (é onde os repos vivem, em `01_CLIENTES/`, `02_PRODUTOS/`, etc.). A
instância da VPS não tem os repos — se precisar do status pela VPS, ela pede via a ponte
`ask-vps-hermes` pro Mac rodar isto.

## Quando usar

- "como estão os projetos?" / "me dá o status geral"
- "o que está parado?" / "tem projeto sem commit faz tempo?"
- "tem coisa não pushada?" / "algum repo sujo?"
- Cron diário, alimentando o `daily-ceo-report` com a seção de projetos.

## Quando NÃO usar

- Para **agir** (commitar, pushar, criar branch, abrir PR) — isto é só leitura. Ação é outra
  skill, de anel maior (ex.: um futuro `pr-builder`, com gate).
- Para rodar testes/lint pesado — v1 lê metadados do git; rodar suíte é Fase 2 (mais custo,
  ainda read-only mas mais lento).

## Como chamar

```bash
python scripts/project_status_auditor.py            # JSON completo
python scripts/project_status_auditor.py --text     # resumo pro Telegram
python scripts/project_status_auditor.py --attention # só o que pede atenção
python scripts/project_status_auditor.py --root ~/Developer/AxtroAI/01_CLIENTES
python scripts/project_status_auditor.py --stale-days 10
```

Exemplo de saída em texto:

```
🗂️ Status dos projetos
4 repos · 3 pedem atenção
✅ OK: projeto-limpo
• projeto-parado [master] (184d) — 💤 parado 🔌 sem_upstream
• projeto-sujo — ✏️ uncommitted 🔌 sem_upstream
• projeto-ahead ↑1 — ⬆️ nao_pushado
```

### Cron diário (opcional)

```
30 7 * * *  cd .../project-status-auditor/scripts && \
            python project_status_auditor.py --text --attention
```

## Sinalizações

| Flag | Significa |
|---|---|
| `uncommitted` | working tree sujo (mudança não commitada) |
| `nao_pushado` | commits locais à frente do remoto (↑N) |
| `parado` | sem commit há mais de `--stale-days` (padrão 7) |
| `sem_upstream` | branch sem remoto configurado |
| `detached_head` | HEAD solto, não está numa branch |
| `erro` | git falhou / não é repo |

## Configuração

| Env / flag | Para quê | Padrão |
|---|---|---|
| `PROJECTS_ROOTS` / `--root` | raízes a varrer (`:`-separadas no env) | `01_CLIENTES`, `02_PRODUTOS`, `00_CONTROL_TOWER` |
| `PROJECTS_STALE_DAYS` / `--stale-days` | dias sem commit pra marcar "parado" | 7 |
| `OBSERVABILITY_URL` / `OBSERVABILITY_TOKEN` / `OBSERVABILITY_TELEMETRY_PATH` | telemetria | — |

Cada raiz pode ser um repo, ou uma pasta que contém repos como subpastas (o caso da House).

## Limitações e cuidados

- Só olha o estado **local** do git — não faz `fetch`, então `behind` reflete o último
  `fetch` que você fez, não o remoto ao vivo (de propósito: `fetch` seria escrita de rede e
  deixaria de ser leitura pura barata).
- Não roda testes nem lint (Fase 2).
- Telemetria é best-effort e só carrega `requests` se `OBSERVABILITY_URL` existir — a skill
  não tem dependência obrigatória nenhuma.

## Testes

`tests/test_project_status_auditor.py` cobre: cada flag isolada (uncommitted, nao_pushado,
sem_upstream, parado, detached_head, erro), repo limpo sem flags, descoberta de repos e o
formato de texto. Rode com `python -m unittest discover -s tests` ou `pytest tests/`.

## Autonomia

Anel 0. Leitura pura do git local, zero credencial, não toca cliente, não escreve, não
gasta. Seguro pra cron 24/7.
