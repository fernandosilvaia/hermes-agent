---
name: axtro-factory-monitor
description: "Anel 0 da fábrica Axtro: briefing da manhã consolidado, detector de projeto parado, rastreio de prazos e vigia de segredo vazado nos ~20 repos. 100% leitura, entrega no Telegram."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
dependencies: []
metadata:
  hermes:
    tags: [Monitoring, Briefing, Git, Security, Productivity, AnelZero]
    related_skills: [google-workspace-axtro, ask-vps-hermes, project-status-auditor]
---

# Axtro Factory Monitor (Anel 0)

> **Sobreposição conhecida com `project-status-auditor`:** as duas fazem varredura de
> git nos repos da House. Use `axtro-factory-monitor` para o **briefing consolidado**
> (git + prazos + segredo vazado + lint interno + inbox, entregue no Telegram,
> agendado). Use `project-status-auditor` para um **raio-X só de git, rápido e
> minimalista**, pensado para alimentar o `daily-ceo-report` ou rodar via
> `ask-vps-hermes` quando o pedido vier da VPS. Não são a mesma coisa por acidente —
> ainda não foram consolidadas numa só; se for mexer nisso, avise antes de fundir.

Dá ao Hermes o "briefing da manhã" da software house: varre todos os repos com
git sob `01_CLIENTES/` e `02_PRODUTOS/`, detecta projeto parado, mudanças não
sincronizadas, prazos batendo e segredo possivelmente vazado — e entrega numa
mensagem única no Telegram.

**É o Anel 0 do plano de autonomia: 100% leitura, zero risco, zero gate.** Nunca
escreve em repo nenhum, nunca toca projeto de cliente, nunca gasta com aprovação.
Roda localmente no MacBook (onde os repos vivem), com as credenciais que já estão
no `.env` do hermes-agent (`TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`).

## Quando usar

| O usuário diz algo como… | Use |
|---|---|
| "me dá o briefing da manhã" / "como tá a fábrica?" | `briefing.py` |
| "quais projetos estão parados?" | `scan.py --stale-days 6` |
| "tem algum prazo batendo?" | `deadlines.py --window 14` |
| "vazou alguma chave nos commits?" | `secrets_scan.py` |
| "os projetos internos estão com lint/TS quebrado?" | `lint_check.py` |
| "tem email não lido importante?" / "triagem da caixa" | `inbox_triage.py` |
| "atualiza o estado vivo da empresa" / "o roteamento de agentes está consistente?" | `consolidate_state.py` |
| "ativa o briefing todo dia de manhã" | `install/install-launchd.sh` |

## Scripts (todos CLI, emitem JSON no stdout)

```bash
# Briefing consolidado (o principal)
python scripts/briefing.py               # monta e envia no Telegram
python scripts/briefing.py --dry-run     # só imprime, não envia
python scripts/briefing.py --llm         # narrativa via OpenRouter (Gemini Flash-Lite)

# Peças individuais
python scripts/scan.py --stale-days 6    # saúde de cada repo (git, stale, testes)
python scripts/secrets_scan.py           # vigia de segredo vazado (arquivos rastreados)
python scripts/deadlines.py --window 14  # prazos nos próximos N dias + vencidos recentes
python scripts/lint_check.py             # lint/typecheck/test dos projetos INTERNOS
python scripts/lint_check.py --notify    # idem, avisa no Telegram só se algo falhar
python scripts/inbox_triage.py           # triagem de axtro@axtroai.com (urgente/spam/rotina)
python scripts/inbox_triage.py --dry-run # idem, só imprime
python scripts/consolidate_state.py      # gera 03_AGENTES/ESTADO_VIVO.md (CLAUDE.md + roster + drift)
python scripts/consolidate_state.py --dry-run  # só o relatório de consistência, não escreve

# Entrega avulsa
echo "texto" | python scripts/telegram_send.py
```

## Agendamento (roda todo dia 07:00 America/New_York)

```bash
bash install/install-launchd.sh          # instala o LaunchAgent e carrega
bash install/install-launchd.sh --hour 8 # horário custom
launchctl kickstart gui/$(id -u)/com.axtroai.hermes.briefing  # testar agora
bash install/uninstall-launchd.sh        # remover
```

O fuso é o horário local do Mac. Este Mac está em America/New_York (Flórida),
que é o fuso oficial do Hermes — então 07:00 aqui = 07:00 na Flórida.

## Configuração (env, tudo opcional)

- `AXTRO_ROOT` — raiz da pasta AxtroAI (autodetectada por padrão).
- `AXTRO_STALE_DAYS` — limiar de "projeto parado" (padrão 6).
- `AXTRO_BRIEFING_MODEL` — modelo OpenRouter da narrativa (padrão `google/gemini-2.5-flash-lite`).
- Lê `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USERS`, `OPENROUTER_API_KEY` do
  `.env` do hermes-agent — nunca de arquivo de projeto, nunca hardcoded.

## Filosofia [SILENT]

Se não há nada digno de nota (nenhum repo com pendência, sem prazo, sem segredo),
o briefing manda um "tudo tranquilo" curto em vez de spam. Você só é incomodado
quando há algo real.

## Garantias de segurança

- **Somente leitura.** Usa apenas `git status/log/rev-list/grep` — nunca `commit`,
  `push`, `checkout`, `rm`. Não altera um byte de nenhum repo.
- **`lint_check.py` é escopo restrito a produtos internos** (`02_PRODUTOS/lab/*`,
  `llm-router`) — nunca toca `01_CLIENTES/`. Se faltar dependência (node_modules,
  ruff/pytest no venv), reporta o gap; nunca instala nada sozinho.
- **`inbox_triage.py` é 100% heurístico, local — nunca chama LLM externo.** Metadados de
  email são dados privados de terceiros; mandar isso pra uma API externa (OpenRouter etc.)
  cruzaria a mesma linha que a regra de LGPD do CLAUDE.md já proíbe para PII de cliente.
  Diferente do `briefing.py` (que só processa metadados de git), esta fica só com
  heurística — e nunca marca como lido, responde ou arquiva.
- **`consolidate_state.py` reproduz o CLAUDE.md verbatim** (nunca resumido/reescrito por
  LLM) — regras da empresa não podem sofrer drift de paráfrase. Escreve só em
  `03_AGENTES/ESTADO_VIVO.md`, local, versionado à parte deste repo.
- **Segredo mascarado.** O vigia nunca imprime a chave inteira — mostra `sk-abc…1234`.
  E ignora placeholders de documentação (upstream Nous, exemplos).
- **Sem dependência externa.** Stdlib pura (Python 3.9+). Não instala nada, não
  precisa de venv, não depende da VPS.
- **Degradação graciosa.** Se o LLM ou a rede falharem, entrega o briefing mecânico
  mesmo assim — nunca trava.
