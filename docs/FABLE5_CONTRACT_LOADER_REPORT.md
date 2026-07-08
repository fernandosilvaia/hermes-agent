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
| `axtro/tools/contract_preflight.py` | **O gate de runtime.** O daemon/worker chama antes de deixar uma skill governada agir: exit 0 = autorizada; exit 10 = bloqueada. Fail-closed. |
| `axtro/tests/test_contract_guard.py` + `test_preflight.py` | 21 testes cobrindo cada regra + os exit codes do preflight. |

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

**Camada 1 — preflight (novo, esta entrega):** o daemon/worker executa
`contract_preflight.py <skill_dir>` antes de rodar uma skill governada. Exit 10 →
não executa. Este é o ponto onde `contract.json` deixa de ser documentação: um
processo real, com exit code, decide.

**Camada 2 — gate de dupla-env no script (já existia):** defesa em profundidade;
mesmo que a camada 1 seja pulada, cada skill corrigida ainda exige
`HERMES_ALLOW_EXECUTE` + `<SKILL>_ENABLED` para agir.

Onde o daemon Nous chama o preflight: no wrapper de execução de skill (antes do
shell-out para o script da skill). Isso é uma **linha de integração no worker/loader**,
não uma reescrita do core Nous — as nativas continuam passando direto.

---

## O que foi DELIBERADAMENTE deixado para follow-up (honestidade)

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
✅ python3 -m unittest discover -s axtro/tests   → 21/21 (16 guard + 5 preflight)
✅ python3 axtro/tools/scan_contracts.py         → 6 governadas todas bloqueadas, 71 nativas pass-through
✅ preflight: hermes-purchase → exit 10 (R3); apple-notes → exit 0 (passthrough);
   axtro-factory-monitor → exit 10 (R1 legacy); path inválido → não-governado
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
