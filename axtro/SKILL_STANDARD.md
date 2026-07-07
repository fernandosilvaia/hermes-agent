# Padrão Premium de Skill Axtro
**Toda skill da Axtro Hermes Skill Library segue este padrão. Sem exceção. · v1 (ciclo Fable 5, 2026-07-07)**

## Estrutura obrigatória

```
skills/<categoria>/<skill-name>/
  SKILL.md          ← frontmatter YAML do Hermes + doc humana (quando usar, quando NÃO usar, exemplos, falhas)
  contract.json     ← contrato de governança (ver axtro/CONTRACT_SCHEMA.json)
  scripts/*.py      ← CLI com --json, --text e --dry-run quando aplicável; stdlib-first
  tests/test_*.py   ← unittest (padrão do repo), sem rede, doubles para tudo que é externo
```

## Regras de nascimento (não-negociáveis)

1. **`enabled: false`** — ativação é ato humano registrado, nunca default.
2. **`production_ready: false`** — só vira `true` após checklist + revisão adversarial.
3. **`activation_stage: "scaffold"` ou `"staging"`** — nunca nasce `production`.
4. **`stop_conditions` com ≥1 item** — o que faz a skill PARAR, escrito antes do que ela faz.
5. **`telemetry_events` com ≥1 item** — formato `skill_id.evento`.
6. **`max_daily_cost_usd`** — 0 se determinística; >0 obrigatório se usa LLM (I6).
7. **`credentials` são NOMES de env var** — valor real nunca aparece em arquivo nenhum (I4).
8. **Anel ≥2 exige `human_gates`** (I3). Anel 4 não é contratável — é proibição, não configuração.

## Validação

```bash
python3 axtro/tools/validate_contracts.py          # texto
python3 axtro/tools/validate_contracts.py --json   # máquina
```

O validador aplica o schema + invariantes I1–I6 (ver docstring da ferramenta).
**Exit 1 = registry quebrado = não faça merge.**

## CLI padrão dos scripts

```
--json     saída JSON estruturada (contrato de máquina)
--text     resumo humano, formatado pra Telegram
--dry-run  mostra o que FARIA sem executar nenhum efeito; skills 100% read-only
           aceitam a flag como no-op documentado
```

Falha degrada com segurança: erro em um item vira flag no relatório e a varredura
continua; falha de rede/credencial vira mensagem clara, nunca stack trace silencioso;
LLM indisponível → fallback mecânico quando existir.

## Roteamento de modelo

| Modelo | Uso |
|---|---|
| `none` | script determinístico (preferir sempre que possível) |
| `haiku` | triagem, resumo, status, classificação barata |
| `sonnet` | implementação, análise média, APIs sensíveis controladas |
| `opus` | arquitetura crítica, decisão sem rollback fácil, revisão final |
| `claude-code` / `codex` | código pesado no repo / scripts e refactors mecânicos |

Regra: o mais barato que resolve; subir de modelo **antes** da tarefa ficar perigosa.

## Anéis de autonomia (resumo operacional)

- **0** leitura/relatório/triagem — livre.
- **1** branch `hermes/*`, PR interno, dry-run, build, MVP com dados simulados — livre com limite.
- **2** ação externa controlada (SMS a lead consentido, Stripe restrito, merge interno com checks verdes) — exige `human_gates` declarados.
- **3** gasto alto, produção de cliente, migration destrutiva, DNS — sempre humano.
- **4** proibido por definição (secret em log, wallet, cruzar dados de clientes, desligar auditoria). Não existe contrato de anel 4.

## Ciclo de vida

```
scaffold → staging → production
   │           │          │
 estrutura   dry-run     gate humano explícito +
 completa    e testes    production_ready=true +
             verdes      registro de quem ativou
```

## Exemplo canônico

`skills/operations/project-status-auditor/` — anel 0, zero credencial, 11 testes,
contract completo. Use como referência ao criar skill nova.
