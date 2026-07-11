---
name: dispatch-job
description: "Monta e (com o gate liberado) envia um job de código real para a fila do Control Tower (POST /api/hermes/jobs), pro MacBook Worker executar via Claude Code ou shell numa branch hermes/*. Use quando identificar uma tarefa de código bem definida que vale a pena delegar — um bug reportado, uma melhoria pequena — e alguém (humano ou o próprio agente, deliberadamente) decidir disparar. Nunca um gatilho automático."
version: 1.0.0
author: Axtro AI
license: MIT
platforms: [macos, linux]
dependencies: [requests]
metadata:
  hermes:
    tags: [Axtro, AgentOps, CTO, JobQueue, ControlTower]
    related_skills: [ask-vps-hermes, project-status-auditor]
---

# Dispatch Job

Monta um payload de `HermesJob` (o mesmo contrato que `src/lib/hermes-jobs.ts` no
Control Tower valida) e, só quando o gate liberar, faz o `POST /api/hermes/jobs`
autenticado (`HOUSE_API_URL` + `HOUSE_INGEST_TOKEN`, mesmo padrão do MacBook Worker,
`scripts/axtro-local-worker.mjs`). O job criado entra na fila; o Worker (rodando no
MacBook, a cada 5 min via launchd) puxa, executa numa branch `hermes/*` e abre PR.

Esta skill é a **CAPACIDADE** de disparar um job — não decide sozinha **quando**
disparar. Quem chama (um humano pedindo no chat, ou o agente durante uma conversa
onde o Fernando pediu algo específico) é quem decide. Não há cron, não há trigger
automático, não há varredura que chama isto sozinha.

## Quando usar

- Foi identificado um **bug real, reportado e reproduzível**, pequeno e bem definido
  (ex.: "POST /api/leads quebra com 500 quando falta um campo opcional").
- Uma **melhoria pequena e bem escopada** num dos dois repos permitidos (control-tower
  ou hermes-agent) — algo que caberia num PR de poucos arquivos.
- Alguém (humano ou o agente, deliberadamente, numa conversa) decidiu que vale a pena
  abrir um job pra isso.

## Quando NÃO usar

- Para **decidir sozinho, em background, sem ninguém ter pedido** — isto não é um
  gatilho automático. Se você (agente) está pensando em chamar isto num loop/cron sem
  supervisão, pare: isso é uma decisão de arquitetura futura, não desta skill.
- Para qualquer coisa de **risco alto** (banco de dados, autenticação, pagamento,
  deploy, produção, DNS, chave/segredo) **esperando que não precise de aprovação** — a
  skill FORÇA `requires_human_gate=true` nesses casos, você não consegue burlar isso
  passando `--requires-human-gate false`.
- Para repositórios fora da allowlist (`AXTRO_REPO_ALLOWLIST` — hoje só control-tower
  e hermes-agent) ou branches que não comecem com `hermes/`.
- Para pedir o executor `codex` — o CLI ainda não está instalado no MacBook Worker
  (ver `docs/hermes-final/IMPLEMENTATION_STATUS.md` no control-tower); a skill recusa.

## Como o gate humano fica preservado (ponta a ponta)

1. **Nesta skill (dispatch-job):** `classify_risk()` calcula o `requires_human_gate`
   EFETIVO — força `true` se a task menciona termo de risco alto, usa `true` como
   default se ninguém declarar nada, e só aceita `false` quando o chamador declara
   explicitamente E não há keyword de risco. "Vence o mais restritivo."
2. **No POST:** o payload sempre carrega esse `requires_human_gate` calculado — a
   skill não confia cegamente no que foi pedido.
3. **No Control Tower** (achado ao implementar esta skill, corrigido na mesma leva —
   ver PR do control-tower): `requires_human_gate=true` faz o job nascer
   `status="pending_approval"`, e o `claimNext()` do MacBook Worker **nunca** enxerga
   um job nesse status — só `"queued"`. Um job só sai de `pending_approval` via
   `POST /api/hermes/jobs/:id/approve`, que exige **sessão de Office admin ou Basic
   Auth** (`isHumanAuthorized`) — explicitamente **não** aceita o mesmo
   `HOUSE_INGEST_TOKEN` que esta skill usa pra criar o job. Isso impede o cenário
   óbvio de furo: o próprio daemon aprovando sozinho o job que ele mesmo abriu.

Ou seja: o gate não é "decorativo" — está fechado em três camadas independentes
(esta skill, o payload, e o servidor), e a camada final exige uma credencial que o
daemon **não possui**.

## Como chamar

### Como biblioteca (dentro do agente)

```python
import sys
sys.path.insert(0, "skills/operations/dispatch-job/scripts")
from dispatch_job import dispatch_job

result = dispatch_job(
    project_id="control-tower",
    repo_path="/Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower",
    branch="hermes/fix-null-check-leads-route",
    executor="claude-code",
    skill_id="pr_builder_interno",
    task=(
        "POST /api/leads quebra com 500 quando decisionMaker.email vem undefined "
        "mesmo depois da validação de schema — adicionar teste de regressão e "
        "corrigir o null-check em src/app/api/leads/route.ts"
    ),
    allowed_commands=["npm run test", "npm run typecheck", "npm run lint"],
    expected_outputs=["teste de regressão", "fix aplicado"],
    requires_human_gate=False,  # bug pequeno, bem definido, sem termo de risco
    dry_run=True,               # SEMPRE comece assim
)
print(result["note"])
```

### Como CLI

```bash
# dry-run (default — nunca toca rede)
python scripts/dispatch_job.py \
  --project-id control-tower \
  --repo-path /Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower \
  --branch hermes/fix-null-check-leads-route \
  --executor claude-code \
  --skill-id pr_builder_interno \
  --task "corrigir null-check em POST /api/leads (ver stack trace do erro)" \
  --allowed-commands "npm run test" "npm run typecheck" \
  --expected-outputs "teste de regressão" "fix aplicado" \
  --requires-human-gate false

# execução real (POST de verdade) — precisa dos DOIS gates + a credencial
HOUSE_API_URL=https://house.axtroai.com \
HOUSE_INGEST_TOKEN=... \
HERMES_ALLOW_EXECUTE=true \
DISPATCH_JOB_ENABLED=true \
python scripts/dispatch_job.py --execute \
  --project-id control-tower --repo-path ... --branch hermes/... \
  --executor claude-code --skill-id pr_builder_interno \
  --task "..." --allowed-commands "npm run test" --expected-outputs "fix aplicado"
```

## Exemplo de saída (dry-run, permitido)

```json
{
  "skill": "dispatch_job",
  "decision": "PERMITIDO",
  "dry_run": true,
  "would_execute": false,
  "payload": {
    "repo_path": "/Users/.../control-tower",
    "branch": "hermes/fix-null-check-leads-route",
    "requires_human_gate": false,
    "...": "..."
  },
  "risk": {"effective_gate": false, "forced": false, "matched_keywords": [], "reason": "..."},
  "blocked": false,
  "job": null,
  "note": "DRY-RUN — payload montado mas NÃO enviado. Para executar de verdade: --execute + HERMES_ALLOW_EXECUTE=true + DISPATCH_JOB_ENABLED=true. requires_human_gate efetivo: False (...)."
}
```

## Exemplo de saída (task de risco alto — gate forçado mesmo pedindo false)

```json
{
  "decision": "PERMITIDO",
  "payload": {"requires_human_gate": true, "...": "..."},
  "risk": {
    "effective_gate": true,
    "forced": true,
    "matched_keywords": ["migration", "banco de dados"],
    "reason": "task contém termo(s) de risco alto (banco de dados, migration) — requires_human_gate forçado para true, independente do que foi pedido"
  }
}
```

## Testando manualmente (dry-run) sem servidor real

Não há Control Tower rodando nesta sessão pra chamar de verdade, então a forma
correta de validar é:

```bash
# 1) roda a suíte inteira (49 testes, zero rede) — prova toda a política
python3 -m unittest discover -s skills/operations/dispatch-job/tests -p 'test_*.py' -v

# 2) roda a CLI manualmente em dry-run (também zero rede — _do_post só é chamado
#    se o gate liberar, e sem HERMES_ALLOW_EXECUTE/DISPATCH_JOB_ENABLED ele nunca libera)
python3 skills/operations/dispatch-job/scripts/dispatch_job.py \
  --project-id control-tower \
  --repo-path /Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower \
  --branch hermes/teste-manual \
  --executor claude-code --skill-id pr_builder_interno \
  --task "tarefa de teste, sem termo de risco" \
  --allowed-commands "npm run test" --expected-outputs "fix aplicado"
# -> decision=PERMITIDO, dry_run=true, would_execute=false, job=null

# 3) prova que o veto de risco funciona mesmo "tentando forçar" false + --execute
#    (ainda fica dry-run porque faltam as envs de gate — mas o payload que SERIA
#    enviado já mostra requires_human_gate=true)
python3 skills/operations/dispatch-job/scripts/dispatch_job.py --execute \
  --project-id control-tower \
  --repo-path /Users/fernandosilva/Developer/AxtroAI/00_CONTROL_TOWER/control-tower \
  --branch hermes/teste-risco \
  --executor claude-code --skill-id pr_builder_interno \
  --task "aplicar migration destrutiva no banco de produção" \
  --allowed-commands "npm run test" --expected-outputs "fix aplicado" \
  --requires-human-gate false
# -> dry_run continua true (faltam HERMES_ALLOW_EXECUTE/DISPATCH_JOB_ENABLED),
#    e mesmo se estivessem setadas, payload.requires_human_gate seria true de qualquer jeito

# 4) validação de contrato + governança (sem precisar do POST real)
python3 axtro/tools/validate_contracts.py
python3 -c "
import json, sys; sys.path.insert(0, 'axtro')
import contract_guard as cg
c = json.load(open('skills/operations/dispatch-job/contract.json'))
print(cg.evaluate(c, env={}, skill_id='dispatch_job'))   # allow_real=False (sem credencial/enabled)
"
```

Pra testar o POST real de verdade (fora desta sessão, com o Control Tower rodando
`npm run dev` local ou apontando pra `house.axtroai.com`), seria necessário: (a) as
duas envs de gate, (b) `HOUSE_INGEST_TOKEN` válido, (c) `--execute`. Nenhuma dessas
condições foi atendida nesta sessão de propósito — a skill nasce `enabled: false` e
o teste real fica pro Fernando rodar quando decidir ativar.

## Configuração

| Env / flag | Para quê | Padrão |
|---|---|---|
| `HOUSE_API_URL` | URL do Control Tower | `https://house.axtroai.com` |
| `HOUSE_INGEST_TOKEN` | credencial de máquina (mesma do worker) | obrigatória p/ POST real |
| `HERMES_ALLOW_EXECUTE` | gate global de execução | — (default: fechado) |
| `DISPATCH_JOB_ENABLED` | gate específico desta skill | — (default: fechado) |
| `AXTRO_REPO_ALLOWLIST` | repos permitidos (`:`-ou `,`-separados) | control-tower + hermes-agent |
| `CONTROL_TOWER_URL` | telemetria best-effort (pode repetir `HOUSE_API_URL`) | — |

## Limitações e cuidados

- O veto por keyword (`_HIGH_RISK_MARKERS`) é defesa-em-profundidade, não uma
  garantia completa — uma task de risco alto descrita sem nenhuma das palavras
  listadas passaria sem forçar o gate. A garantia DURA continua sendo o
  `requires_human_gate` explícito que quem chama declara com honestidade, e o fato
  de que o default (nada declarado) já é seguro (`true`).
- Esta skill NUNCA executa código — ela só cria o PEDIDO. Quem executa é o MacBook
  Worker, noutro processo, noutra hora (próxima checagem do launchd).
- `forbidden_commands` do payload sempre inclui os defaults do Control Tower
  (`git push origin main`, `rm -rf /`, `drop table`, etc.) união com o que o
  chamador passar — mas o Control Tower já une isso de novo no servidor
  (`createJob` em `src/lib/hermes-jobs.ts`); é redundância deliberada, não a única
  linha de defesa.
- `max_runtime_minutes`/`max_cost_usd` têm teto client-side (90min / US$10) — mesmo
  que o Control Tower tenha os seus próprios (o worker aplica um teto absoluto de
  30min e US$5 pro executor `claude-code`, independente do declarado).

## Testes

`tests/test_dispatch_policy.py` (38 testes) cobre a política pura: allowlist de
repo/branch/executor, campos obrigatórios, classificação de risco (veto por
keyword, default seguro, respeito à escolha explícita quando segura), montagem do
payload, e o gate triplo. `tests/test_dispatch_job_dryrun.py` (11 testes) prova o
fluxo ponta a ponta sem rede (com uma sentinela no lugar do POST real), incluindo a
CLI. Rode com `python3 -m unittest discover -s tests -p 'test_*.py'`.

## Autonomia

Anel 2 (`ação externa controlada` — cria um job que, se não gated, o Worker executa
sozinho). `risk`/`human_gates` declarados no `contract.json`. Nasce `enabled: false`,
`activation_stage: "staging"` — ativação em produção é ato humano (setar
`enabled: true` no contract + as duas envs de gate fora do daemon).
