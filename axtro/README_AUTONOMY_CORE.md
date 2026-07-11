# Hermes Autonomy Core — poder com trilhos

**Como o Fernando dá autonomia real ao Hermes sem que ele cause dano grave por acidente.**

A ideia é simples: o Hermes **age sozinho no que é seguro** e **pede aprovação só no
que é sensível**. Toda execução importante passa por um **executor oficial**, gera
**log + relatório**, e nada financeiro/externo/produção sai de verdade sem um gate
humano. Não é uma prisão — é um trilho.

---

## 1. Os dois eixos

Cada skill tem um `contract.json` que declara **em que anel de autonomia** ela opera
e **qual a classe de risco** dela. As duas coisas juntas decidem o que pode acontecer.

### Anéis de autonomia (o QUE a skill faz)

| Anel | O que é | Precisa de humano? |
|---|---|---|
| **Ring 0** | observar, ler, diagnosticar, relatar | não |
| **Ring 1** | criar/editar arquivos, prompts, docs, testes | não |
| **Ring 2** | executar skills internas seguras | gate operacional (`HERMES_RING_GATE`) |
| **Ring 3** | preparar mudança de produção, aprovar antes de aplicar | aprovação humana |
| **Ring 4** | execução autônoma avançada | **só se liberada no contrato** (`ring4_autonomous: true`) |

### Classes de risco (o QUANTO pode causar dano)

| Classe | Regra |
|---|---|
| `safe` | executa sozinho |
| `medium_risk` | executa sozinho **se tiver contrato E testes** |
| `high_risk` | preflight + log + dry-run quando possível (no máximo `staging`) |
| `production_sensitive` | **aprovação humana** ou gate explícito |
| `financial_sensitive` | **nunca** gasto/compra/cobrança real sem aprovação |
| `external_communication` | **nunca** msg/e-mail/ligação/SMS real sem aprovação |

Quando os dois eixos discordam, **vence o mais restritivo** (a segurança ganha da pressa).

---

## 2. O kill switch (parada de emergência)

Uma variável global desliga tudo, na hora, antes de qualquer decisão:

```bash
export HERMES_KILL_SWITCH=on     # qualquer execução → BLOQUEADA
```

Com o kill switch ligado, **nem a skill mais segura roda**. Para religar, remova a var.

---

## 3. Como o Hermes executa uma skill (executor oficial)

**Sempre** por `axtro/skill_runner.py`. Ele: (1) decide via `autonomy_core`, (2)
aplica o modo (dry-run/staging/production), (3) só então cria o processo do script,
(4) grava log e devolve relatório.

```bash
# via CLI
python3 axtro/skill_runner.py <dir-da-skill> <script.py> [args...]

# exit 0  → fez ação real (staging/production)
# exit 10 → bloqueada, ou rodou só em dry-run (nenhuma ação real)
```

```python
# via código (o worker do daemon chama assim)
import skill_runner
r = skill_runner.run_skill("axtro/skill_examples/safe-diagnostic", ["scripts/run.py"])
print(r.report)        # relatório humano
print(r.real_action)   # fez ação real?
```

Se a decisão for `blocked`/`killed`, **o subprocess do script nunca é criado**
(fail-closed). Se for `dry_run`, roda simulando (força `--dry-run`, sem gate de
execução). Se for `staging`/`production`, roda de verdade.

> **Defesa em profundidade (2 camadas).** O runner é a 1ª camada. Cada script
> sensível ainda tem o seu próprio gate de dupla-env (`HERMES_ALLOW_EXECUTE` +
> flag da skill). Mesmo que alguém rode o script **direto** (burlando o runner),
> a 2ª camada impede ação real sem os gates. Ação real efetiva = runner autoriza
> **E** gate no script.

**No caminho ao vivo do daemon** (o loop de tool-use do gateway decidindo, via a
tool genérica `terminal`, rodar o script de uma skill) o agente nunca chama
`skill_runner.py` diretamente — ele só executa um comando de shell. `axtro/dispatch_guard.py`
fecha esse gap: é chamado uma única vez, no topo de `tools/terminal_tool.terminal_tool()`,
antes de qualquer backend (local/docker/ssh/modal) ser escolhido. Se o comando invoca
diretamente o script de uma skill governada, ele passa pela mesma decisão do
`autonomy_core` (via `contract_preflight.preflight_decision`) antes que qualquer
subprocess exista — bloqueia se `blocked`/`killed`, força `--dry-run` se `dry_run`,
passa sem alteração se `staging`/`production`. Comandos que não invocam uma skill
governada (a esmagadora maioria) não são tocados.

---

## 4. O `contract.json` (exemplo)

Skill segura, roda sozinha (`axtro/skill_examples/safe-diagnostic/contract.json`):

```json
{
  "id": "safe-diagnostic",
  "enabled": true,
  "production_ready": true,
  "activation_stage": "production",
  "autonomy_ring": 0,
  "risk_class": "safe",
  "stop_conditions": ["erro inesperado", "output vazio"],
  "telemetry_events": ["diagnostic.run"],
  "credentials": [],
  "human_gates": [],
  "rollback": {"supported": false, "motivo": "read-only — nada a desfazer"}
}
```

| Campo | Para que serve |
|---|---|
| `enabled` | `false` → skill desligada, **não roda** (nem ação real). Ligar é o que ativa. |
| `production_ready` | `false` → no máximo `staging`, nunca `production`. |
| `autonomy_ring` | 0–4 (ver tabela). |
| `risk_class` | classe de risco (ver tabela). |
| `stop_conditions` | **vazio → bloqueia** (uma skill sem freio é perigosa). |
| `telemetry_events` | **vazio → bloqueia `production`** (sem telemetria, sem produção). |
| `credentials` | env vars que precisam existir; **ausente → bloqueia** (fail-closed). |
| `human_gates` | quais aprovações humanas a skill exige. |
| `rollback` | como desfazer, quando dá. |

---

## 5. Exemplos incluídos

| Skill | Classe | Sem gate | Com gate |
|---|---|---|---|
| `skill_examples/safe-diagnostic` | safe | roda (produção, read-only) | — |
| `skill_examples/charge-customer` | financial_sensitive | **dry-run** (nada cobrado) | staging só com `HERMES_HUMAN_APPROVAL` |
| `skill_examples/prepare-prod-change` | production_sensitive | **dry-run** (só plano) | staging só com `HERMES_HUMAN_APPROVAL` |

Rodar:
```bash
python3 axtro/skill_runner.py axtro/skill_examples/safe-diagnostic scripts/run.py
python3 axtro/skill_runner.py axtro/skill_examples/charge-customer scripts/charge.py
HERMES_HUMAN_APPROVAL=true python3 axtro/skill_runner.py axtro/skill_examples/prepare-prod-change scripts/prepare.py
```

---

## 6. Logs e relatório

Toda execução vira uma linha JSON em `axtro/logs/executions.jsonl` (dir criado em
runtime, ignorado pelo git; amostra versionada em `axtro/AUTONOMY_SAMPLE_LOG.jsonl`)
e um relatório curto:

```
[Hermes] skill=charge-customer · risco=financial_sensitive · ring=3
  🟡 DRY-RUN (simulado, nenhuma ação real)
  motivo: financial_sensitive: exige aprovação humana (HERMES_HUMAN_APPROVAL) → dry-run
  ⚠️  precisa de aprovação humana (HERMES_HUMAN_APPROVAL) para ação real
```

Timestamp em `America/New_York` (fuso do Hermes). Redirecione com `HERMES_EXEC_LOG=/caminho`.

---

## 7. As variáveis de controle (o humano seta FORA do daemon)

| Variável | Efeito |
|---|---|
| `HERMES_KILL_SWITCH=on` | para de emergência — bloqueia tudo |
| `HERMES_HUMAN_APPROVAL=true` | aprovação humana p/ classes sensíveis (prod/financeiro/externo) e ring ≥ 2 |
| `HERMES_RING_GATE=true` | gate operacional p/ ring ≥ 2 (skills não-sensíveis) |
| `HERMES_ALLOW_EXECUTE=true` | 2ª camada: gate de execução dentro do script (o runner **remove** essa var fora de produção) |

> ⚠️ Neste build de segurança, financeiro/externo/produção **nunca passam de
> `staging`**, mesmo com aprovação — produção real fica protegida. Ligar produção
> real é um passo humano futuro, separado.

---

## 8. Como o Fernando liga uma skill nova

1. Cria a skill com `contract.json` (copie um exemplo).
2. Declara `risk_class` e `autonomy_ring` honestos.
3. Adiciona o caminho em `axtro/GOVERNED_SKILLS.txt` (senão é tratada como nativa Nous → pass-through).
4. Enquanto testa: deixa `enabled: false` → só dry-run.
5. Quando confiar: `enabled: true`. Para classes sensíveis, a ação real só acontece
   com `HERMES_HUMAN_APPROVAL` setado por você, fora do daemon.
6. Kill switch sempre disponível se algo sair do trilho.

---

## 9. Provas (testes)

```bash
python3 -m unittest discover -s axtro/tests -p 'test_*.py'
```

`axtro/tests/test_autonomy_core.py` prova:
- ✅ skill segura roda
- ✅ skill sensível sem contrato bloqueia (fail-closed)
- ✅ production_sensitive exige gate (sem gate → dry-run; com gate → staging)
- ✅ kill switch bloqueia tudo
- ✅ execução direta de skill sensível não faz ação real (2ª camada)
- ✅ toda execução gera log + relatório

---

## 10. Peças do sistema

| Arquivo | Papel |
|---|---|
| `axtro/autonomy_core.py` | o cérebro: kill switch + anel + classe de risco + aprovação → decisão |
| `axtro/skill_runner.py` | o executor oficial: decide → aplica modo → spawna → loga |
| `axtro/dispatch_guard.py` | o gancho no caminho ao vivo: reconhece invocação direta de skill governada dentro de um comando de `terminal` e aplica a mesma decisão antes do subprocess existir |
| `axtro/exec_log.py` | log estruturado (JSONL) + relatório |
| `axtro/contract_guard.py` | regras base de contrato (validade, creds, stop, telemetry) |
| `axtro/tools/contract_preflight.py` | gate por exit code (CLI + preflight) |
| `axtro/tools/scan_contracts.py` | raio-X: estado de cada skill governada |
| `axtro/GOVERNED_SKILLS.txt` | allowlist do que a Axtro governa (o resto é nativa Nous) |
| `axtro/skill_examples/` | 3 skills de exemplo (segura, financeira, produção) |

Não é burocracia. É o mínimo para o Hermes construir, melhorar, testar e operar com
liberdade — sem poder quebrar nada grave por acidente.

---

## 11. Limites honestos (o que protege contra o quê)

Este sistema foi feito para o objetivo que o Fernando pediu: **impedir dano grave por
acidente**, dando autonomia. Fiz um red-team (5 ataques offline tentando fazer a
`charge-customer` cobrar de verdade — `CHARGED` é um arquivo local, proxy de cobrança):

| Ataque | Resultado |
|---|---|
| agente seta todos os gates via runner | 🟢 sem cobrança — runner rebaixa financeiro p/ `staging` e remove `HERMES_ALLOW_EXECUTE` |
| execução direta, env vazio (acidente) | 🟢 sem cobrança — gate fail-closed no script |
| contract adulterado p/ `risk_class=safe` | 🟢 sem cobrança — gate no script (2ª camada) barra mesmo com contrato mentiroso |
| skill sensível fora da allowlist + gates | 🔴→🟢 **vazava; corrigido** — pass-through agora também remove `HERMES_ALLOW_EXECUTE` |
| execução direta com os 3 gates setados | 🟡 cobra — **é o caminho REAL intencional** (um humano seta os 3 gates fora do daemon) |

**Contra ACIDENTE: forte.** Todo caminho acidental (skill desligada, sem aprovação,
env parcial, contrato mentiroso, skill nova esquecida fora da allowlist) → nenhuma
ação real. São camadas independentes: kill switch, decisão do core, e o gate
fail-closed dentro de cada script.

**Contra um AGENTE totalmente adversarial: os gates por variável de ambiente são a
camada de acidente, não de contenção adversarial.** Um agente que controla o shell
e seta deliberadamente os 3 gates por execução direta consegue ação real — porque
esse É o caminho humano intencional. Para dinheiro/comunicação com grau adversarial,
o mecanismo certo é o **token de aprovação fora-de-banda** (padrão da skill
`hermes-purchase`: token só vai pro Telegram, hash no ledger, verificação por
`hmac.compare_digest`). O env-gate previne acidente; o token contém adversário.

**Duas regras operacionais que decorrem disso:**
1. Toda skill Axtro sensível **precisa** estar em `GOVERNED_SKILLS.txt` — o que está
   fora é pass-through (não governado pelo core). A 2ª camada ainda protege contra
   acidente, mas a governança do core só vale para o que está na allowlist.
2. O `contract.json` é **confiável** (versionado, revisado no PR). Ele é fonte de
   verdade da decisão; adulterar contrato muda a decisão, mas a 2ª camada segue
   fail-closed contra acidente.
