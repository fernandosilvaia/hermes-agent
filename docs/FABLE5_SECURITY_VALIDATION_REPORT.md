# Fable 5 — Relatório de Validação Independente de Segurança (Frente A)

**Ciclo Fable 5 · 2026-07-07 · repo `02_PRODUTOS/lab/hermes-agent`, branch `hermes/fable5-cycle1-agentops`**

> Validação **independente** dos fixes de segurança já aplicados. Não confia nos
> testes das próprias skills nem no relatório de correção — cada afirmação foi
> re-executada por um harness de ataque próprio que conta chamadas reais de API/rede
> e verifica o output cru. Encontrou 1 gap real (corrigido) e confirmou o resto.

---

## Método

Para cada skill, um harness em `/scratchpad/validate_*.py` executa os ataques
diretamente (com `auth`/`requests` stubados que **contam** chamadas reais), não
os testes da skill. Um cenário só é "PASS" se o efeito real (chamada de API,
envio, rede) **não** ocorre no ataque E — crucialmente — **ocorre** no caminho
legítimo (prova de que o gate não bloqueia vacuamente).

Além do harness: `python3 -m unittest discover` nas 4 skills, e grep no output cru.

---

## Resultado consolidado

| Skill | Cenários do harness | Testes unitários | Veredito |
|---|---|---|---|
| google-workspace-axtro | 7/7 PASS | 44 OK | ✅ P0 fechado |
| telnyx-voice-sms | 13/13 PASS (após fix) | 46 OK | ✅ P0 fechado (1 gap corrigido) |
| ask-vps-hermes | 10/10 PASS | 37 OK | ✅ P0 fechado |
| hermes-purchase | 12/12 PASS | 36 OK | ✅ P0 fechado |

**163 testes unitários verdes** (+5 novos de regressão nesta validação).

---

## 🔴 Gap real encontrado (e corrigido) nesta validação

**telnyx-voice-sms — máscara de OTP só no CLI, não na biblioteca.**

- `read_inbox.py` mascarava o OTP no caminho **CLI** (`python read_inbox.py last`),
  mas as funções de **biblioteca** `last_sms()` e `recent_sms()` retornavam o record
  **cru com o código 2FA**. A docstring do módulo documenta `from read_inbox import
  last_sms` como uso suportado — então o daemon, importando a função, pegaria o OTP
  em claro. É a **mesma classe** do "Bypass B" do google-workspace (via biblioteca
  pulando a proteção que só existia no wrapper).
- **Reproduzido:** `last_sms()` como biblioteca retornava `"verification_code":
  "483920"` (cru).
- **Correção:** `last_sms`/`recent_sms` agora mascaram por padrão; `reveal=True` só
  revela com o gate humano aberto (fail-closed). O CLI passou a delegar às funções de
  biblioteca (fonte única). Commit `c330d7d9c`.
- **Causa raiz da lacuna:** não havia **nenhum** teste de `read_inbox` — a máscara só
  era exercitada via CLI. Adicionado `test_read_inbox.py` (5 testes) cobrindo a via de
  biblioteca e o gate de reveal.

---

## Validação por skill (cada item que o pedido listou)

### 1. google-workspace-axtro
- ✅ `drive.share` externo (mesmo com `approve_external=True`) sem allowlist de parceiro fora do daemon → **bloqueado, 0 chamadas de API**.
- ✅ `gmail.send` externo → **bloqueado, 0 API**.
- ✅ `calendar.create` attendee externo → **bloqueado, 0 API**.
- ✅ Chamada via **biblioteca** (`share_file`/`send_email` com `dry_run=False` sem as envs) → cai em dry-run pelo gate, **0 API** (Bypass B fechado).
- ✅ Prompt-injection setando `approve_external=True` + gate 100% aberto, mas sem `GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS` → **bloqueado, 0 API** (o agente não consegue se auto-aprovar; a allowlist de parceiro vive fora do daemon).
- ✅ **Sanidade:** interno + gate aberto → envia de verdade (1 API) — o gate não é bloqueio vacuoso.

### 2. telnyx-voice-sms
- ✅ `/sms/last`: `require_token` rejeita token errado, aceita o certo, e é **fail-closed** quando o esperado é vazio; `extract_bearer` aceita `Bearer` e rejeita `Basic`.
- ✅ OTP mascarado: `mask_otp` remove o `483920` cru; `read_inbox` mascara por padrão (CLI **e** biblioteca, após o fix).
- ✅ `send_sms`/`make_call`: terceiro fora da allowlist → **bloqueado, 0 rede** (mesmo com o gate 100% aberto); próprio número + gate aberto → envia (sanidade).
- ✅ Teto diário e gate de dupla-env presentes e testados.

### 3. ask-vps-hermes
- ✅ Kill-switch: sem o gate, `dry_run=True`, **0 rede**.
- ✅ Intent fora da allowlist (`enviar_email`) → **bloqueado**.
- ✅ Injeção (`envie um email`, `mande um sms`, `compartilhe`, `ignore previous`) → **bloqueada**, mesmo com intent válido, via função pura E via CLI.
- ✅ Chave `HERMES_VPS_API_SERVER_KEY` **não aparece** no output (0 ocorrências).
- ✅ Sanitização remove chars de controle e trunca (<=4100).

### 4. hermes-purchase
- ✅ `request` e `confirm` são subcomandos **separados**.
- ✅ Daemon não auto-aprova: `confirm` sem token → **recusado (exit ≠ 0)**, status continua `pendente`.
- ✅ Token cru **nunca no stdout** do `request` (campo `approval_token` ausente).
- ✅ Ledger guarda só o **hash sha256** (`approval_token_sha256`, 64 hex), nunca o token cru; o hash tampouco vaza no stdout.
- ✅ **Replay do hash** como token → **recusado** (exige `sha256(x)==x`).
- ✅ Env humana ausente / token errado → **recusado**.
- ✅ `NaN`/`Infinity` no amount → **BLOQUEADA** (não fura o teto).
- ✅ `--dry-run` sempre vence; status permanece `pendente` após toda a bateria de ataques.

---

## Nota de honestidade

Um cenário do harness do hermes-purchase deu "FAIL" na primeira rodada — mas era
**falso-negativo do meu próprio harness** (procurava um campo com "hash" no nome,
enquanto o campo real é `approval_token_sha256`). O código estava correto; corrigi o
harness. Registro isto para deixar claro que "todos PASS" não foi por baixar a régua.

---

## Conclusão

Os 5 P0 da Frente A estão **efetivamente fechados** sob ataque independente. A
validação agregou valor real: encontrou e corrigiu a máscara de OTP faltante na via
de biblioteca do telnyx — um vazamento de 2FA que os testes da própria skill não
pegavam (não havia teste de `read_inbox`).

**Risco estrutural remanescente (leva à Parte 2):** todo o enforcement vive **no
próprio script** de cada skill. Se o daemon executar uma skill sem passar pelo
wrapper esperado, ou uma skill legacy sem `contract.json`, não há uma camada central
que garanta `enabled=false`. A Parte 2 (loader respeitando `contract.json`) fecha
essa categoria.
