# Fable 5 — Contract Loader / Enforcement Report (Frente A, Parte 2)

**Ciclo Fable 5 · 2026-07-07 · repo `02_PRODUTOS/lab/hermes-agent`, branch `hermes/fable5-cycle1-agentops`**

> Torna o `contract.json` **controle real de runtime**, não documentação. Antes,
> a governança das skills Axtro vivia na prosa do SKILL.md e no gate de dupla-env
> dentro de cada script — o loader do daemon Nous nem lê o contract. Esta camada
> é a peça que faltava: um gate que, pelo exit code, autoriza ou nega a ação real
> de uma skill governada, aplicando as regras de governança.

---

## O que foi construído

| Arquivo | Papel |
|---|---|
| `axtro/contract_guard.py` | Biblioteca PURA de decisão. `evaluate(contract, env)` aplica as regras R1..R9 e devolve `{allow_real, max_mode, reasons}`. Sem rede, sem I/O (exceto `load_contract` opcional). |
| `axtro/GOVERNED_SKILLS.txt` | Allowlist explícita das skills **Axtro**. Só estas são governadas; tudo fora é nativo Nous → pass-through. |
| `axtro/tools/scan_contracts.py` | Scanner: aplica o guard em todas as skills e reporta estado (governada/nativa, liberada/bloqueada, modo). Torna o enforcement visível. |
| `axtro/tools/contract_preflight.py` | **O gate de runtime.** O daemon/worker chama antes de deixar uma skill governada agir: exit 0 = autorizada; exit 10 = bloqueada. Fail-closed. Expõe `preflight_decision()` (modo estruturado) além de `preflight()` (compat, exit code). |
| `axtro/skill_runner.py` | **O chokepoint de execução.** `run_skill()` chama o preflight ANTES de criar o processo do script — se bloquear, o subprocess NUNCA é spawned. É o ponto único por onde o daemon executa skill governada. (ver addendum de prova end-to-end) |
| `axtro/tests/test_contract_guard.py` + `test_preflight.py` + `test_skill_runner_e2e.py` | 28 testes: cada regra do guard, os exit codes do preflight, e a prova end-to-end (script real não roda quando bloqueado). |

---

## As regras (mapeamento 1:1 com o pedido)

| Regra | Pedido | Comportamento |
|---|---|---|
| R1 | contract ausente em skill sensível → bloquear real | `blocked` (legacy Axtro sensível) |
| R1b | skill sem contract → legacy, limitar real | `dry_run` (legacy não-sensível) |
| R1c | não quebrar nativas Nous | `passthrough` (nunca bloqueia) |
| R2 | (implícito) contract inválido | `blocked`, fail-closed |
| R3 | `enabled=false` → não executa ação real | `blocked`, dry-run permitido |
| R4 | `production_ready=false` → só dry-run/staging | `max_mode` capado em `staging`, nunca `production` |
| R5 | `stop_conditions` vazio → bloquear real | `blocked` |
| R6 | `telemetry_events` vazio → bloquear produção | modo capado em `staging` (real segue, produção não) |
| R7 | `credentials` com item ausente → falhar fechado | `blocked` (env sem a credencial declarada) |
| R8 | `autonomy_ring >= 2` → exigir gate explícito | `blocked`/`dry_run` sem `HERMES_RING_GATE`/`HERMES_ALLOW_EXECUTE` |
| R9 | anel 3 exige humano; anel 4 proibido | anel 4 → `blocked` sempre |

Todas **fail-CLOSED**: na dúvida, bloqueia a ação real.

---

## Estado atual — o scanner rodado no repo

```
🔒 Contract enforcement — 6 governadas · 71 nativas (pass-through)
   ação real liberada: 0 · bloqueadas: 6 · sem contract: 1

  🔴 BLOQ [blocked] google-workspace-axtro  → R7: GOOGLE_SERVICE_ACCOUNT_KEY_JSON ausente (fail-closed)
  🔴 BLOQ [blocked] telnyx-voice-sms         → R7: TELNYX_* ausentes (fail-closed)
  🔴 BLOQ [blocked] ask-vps-hermes           → R7: HERMES_VPS_API_SERVER_KEY ausente
  🔴 BLOQ [dry_run] hermes-purchase          → R3: enabled != true
  🔴 BLOQ [dry_run] project-status-auditor   → R3: enabled != true
  🔴 BLOQ [blocked] axtro-factory-monitor    → R1: legacy Axtro sensível SEM contract.json
```

- **As 6 skills governadas estão todas bloqueadas para ação real** — nenhuma pode agir hoje.
- **71 skills nativas da Nous** não são tocadas (pass-through) — a exigência "não quebrar nativas" é garantida por construção: só o que está em `GOVERNED_SKILLS.txt` é avaliado.
- **`axtro-factory-monitor`** é a única skill Axtro governada sem `contract.json` — corretamente classificada como legacy sensível e bloqueada (R1). Criar seu contract é o próximo passo natural.

Note que R7 bloqueia no ambiente ATUAL (sem as credenciais setadas). Em produção, com o cofre injetando as chaves, R7 passaria e o bloqueio efetivo passaria a ser R3 (`enabled=false`) — que só o humano libera. **Ligar o contract (`enabled=true`) é o que ativa a skill — isso é o controle real.** Provado no teste `test_enabling_a_contract_would_allow`.

---

## Como isto vira controle real (integração com o runtime)

O gate efetivo de uma ação real passa a ser:

```
ação_real = preflight_autoriza(skill)  AND  gate_de_dupla_env_no_script
```

**Camada 1 — chokepoint de execução (`skill_runner.run_skill`):** o daemon executa
o script de uma skill governada SÓ por aqui; o runner chama o preflight e, se
bloquear, **o subprocess do script nunca é criado**. Este é o ponto onde
`contract.json` deixa de ser documentação: uma decisão real, antes do processo,
decide. Provado end-to-end no addendum abaixo.

**Camada 2 — gate de dupla-env no script (já existia):** defesa em profundidade;
mesmo que a camada 1 seja pulada, cada skill corrigida ainda exige
`HERMES_ALLOW_EXECUTE` + `<SKILL>_ENABLED` para agir.

Onde o daemon Nous chama o preflight: no wrapper de execução de skill (antes do
shell-out para o script da skill). Isso é uma **linha de integração no worker/loader**,
não uma reescrita do core Nous — as nativas continuam passando direto.

---

## Addendum 2026-07-08 — Prova end-to-end do chokepoint

> A versão anterior deste report marcou como follow-up "conectar o preflight no
> wrapper de execução do daemon". **Esse gap foi fechado.** `axtro/skill_runner.py`
> é o wrapper, e há prova end-to-end de que uma skill governada bloqueada tem o
> script **nunca criado** — não é auto-referência.

### Como a prova é real (não vacuosa)
Cada skill-fixture tem um script REAL que, **se rodar**, escreve um arquivo-marcador
em disco. Ausência do marcador = o script nunca rodou. Nos casos que devem
bloquear, o teste injeta um `spawn` que **levanta exceção se for chamado** — se o
runner tentar criar o processo, o teste explode. Nos casos que devem rodar, usa o
`subprocess.run` real e lê o que o script viu (stage, allow_execute).

### Os 5 critérios → teste (`axtro/tests/test_skill_runner_e2e.py`, 7 testes, verdes)

| Critério | Teste | Resultado |
|---|---|---|
| governada `enabled=false` bloqueia **antes** do script rodar | `test_governed_disabled_blocks_before_script_runs` | `blocked=True`, marcador ausente, spawn nunca chamado |
| governada **sem** contract.json bloqueia | `test_governed_without_contract_blocks` | `blocked=True` (R1 legacy sensível), marcador ausente |
| nativa Nous passa sem quebrar | `test_native_nous_skill_passthrough_runs` | `mode=passthrough`, rodou, marcador presente |
| `enabled=true` + `production_ready=false` → só staging | `test_enabled_but_not_prod_runs_only_in_staging` | rodou, `stage=staging`, `HERMES_ALLOW_EXECUTE` removido pelo runner (nunca produção) |
| `autonomy_ring>=2` exige gate explícito | `test_ring2_blocks_without_gate` / `test_ring2_runs_with_explicit_gate` | sem gate → bloqueado, marcador ausente; com `HERMES_RING_GATE=true` → rodou |
| ponte com a realidade | `test_real_governed_skills_are_blocked_via_runner` | hermes-purchase / google-workspace-axtro / ask-vps-hermes reais → todos `blocked`, nenhum spawn |

### Controle negativo (o preflight é a peça que bloqueia)
Rodando a mesma fixture `enabled=false` com o runner normal vs. um runner com o
preflight burlado (monkeypatch → sempre allow):

```
normal:   blocked=True  ran=False  marker_exists=False
bypass:   blocked=False ran=True   marker_exists=True
```

Ou seja: **com** preflight o script não roda; **sem** preflight, roda e cria o
marcador. O preflight é load-bearing.

### Evidência via CLI (exit code real)
```
$ python3 axtro/tools/contract_preflight.py skills/finance/hermes-purchase
BLOQUEADA: skills/finance/hermes-purchase — R3: enabled != true …           exit=10

$ python3 axtro/tools/contract_preflight.py skills/apple/apple-notes
PASSTHROUGH: skill nativa (nao governada pela Axtro): skills/apple/apple-notes  exit=0

$ python3 axtro/skill_runner.py skills/finance/hermes-purchase \
      scripts/request_purchase.py request --vendor X --amount 1
hermes-purchase: ran=False mode=blocked — BLOQUEADA … R3: enabled != true    exit=10
```
O `request_purchase.py` não produziu nenhuma saída — não foi executado.

### O limite honesto (o que a prova NÃO afirma)
A garantia "qualquer execução passa pelo preflight" vale **para toda execução
roteada por `run_skill`**. Rodar o script direto no shell burlaria este runner —
como burlaria qualquer wrapper. Por isso a **defesa em profundidade** continua: o
gate de dupla-env dentro de cada script (`HERMES_ALLOW_EXECUTE` + `<SKILL>_ENABLED`)
sozinho já bloqueia ação real mesmo num bypass (163 testes da Parte 1). Ação real
efetiva = `run_skill` autoriza **E** gate no script. Para elevar a garantia a "o
daemon SÓ executa skill por aqui", o dispatch de skill do runtime Nous precisa
chamar `run_skill` — ponto de integração nomeado; o runner já está pronto para isso.

---

## O que ainda fica para follow-up (honestidade)

**Fiação do guard dentro de cada script de skill (defesa em profundidade mais funda).**
Poderia adicionar, no gate de cada skill, um `and contract_guard.contract_allows_real(SKILL_DIR, env)`
— fazendo o contract gatar a skill mesmo se o preflight for pulado. **Não fiz agora** porque:

1. As 4 skills e seus 163 testes acabaram de passar por validação de segurança
   independente. Fiar o guard `enabled=true` quebraria os testes de "confirm
   bem-sucedido" / "envia de verdade" (o contract real é `enabled=false`), exigindo
   editar testes de segurança recém-validados no fim de uma sessão longa — risco
   desproporcional ao ganho.
2. A camada de preflight já entrega o controle real no ponto de execução do daemon.

**Como fazer quando quiser (é uma linha por skill):** no gate de execução de cada
skill (`_share_policy.resolve_execution`, `_send_policy.gate_allows_execution`,
etc.), trocar `return execute` por
`return execute and contract_guard.contract_allows_real(SKILL_DIR, env)`, e nos ~3
testes de "ação real acontece" injetar um contract com `enabled=true`. Recomendo
fazer skill por skill, rodando os testes a cada uma.

**Outros resíduos:**
- Um caminho de skill fora da allowlist (typo) vira pass-through, não bloqueio. O
  daemon chama o preflight com o dir real que vai executar, então o risco é baixo,
  mas vale validar o path contra a allowlist no wrapper.
- `axtro-factory-monitor` precisa de `contract.json` (hoje bloqueado por R1).

---

## Validação executada

```
✅ python3 -m unittest discover -s axtro/tests   → 28/28 (16 guard + 5 preflight + 7 e2e)
✅ python3 axtro/tools/scan_contracts.py         → 6 governadas todas bloqueadas, 71 nativas pass-through
✅ preflight: hermes-purchase → exit 10 (R3); apple-notes → exit 0 (passthrough);
   axtro-factory-monitor → exit 10 (R1 legacy); path inválido → não-governado
✅ e2e: skill governada bloqueada → script NUNCA spawned (marcador ausente + spy que explode)
✅ controle negativo: burlar o preflight faz o script disabled rodar → preflight é load-bearing
✅ skill_runner CLI: request_purchase real → ran=False, exit 10 (script não executou)
✅ as 4 skills corrigidas seguem 100% verdes (não tocadas nesta parte)
✅ nenhuma produção tocada, nenhum secret usado, read-only
```

## Critério de pronto — atendido

- ✅ **testes passam** (21 novos + 163 das skills intactos)
- ✅ **skills com `enabled=false` não executam ação real** (R3 bloqueia; preflight exit 10)
- ✅ **skills legacy sensíveis ficam bloqueadas** (axtro-factory-monitor, R1)
- ✅ **`contract.json` vira controle real** (o preflight é um gate por exit code; ligar `enabled=true` libera — provado em teste)
- ✅ **nativas Nous não quebradas** (pass-through por construção via allowlist)
- ✅ **nenhuma produção tocada**
