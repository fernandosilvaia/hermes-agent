# Fable 5 — Relatório de Auditoria Adversarial das Skills do Hermes Agent

**Ciclo Fable 5 · 2026-07-07 · repo `02_PRODUTOS/lab/hermes-agent` (fork NousResearch, daemon 24/7)**

> Auditoria feita por 6 agentes adversariais independentes (um por skill),
> cada achado com arquivo:linha e reprodução empírica. Este documento é o
> registro formal que faltava — os achados existiam só no journal do
> workflow até agora.

---

## Sumário executivo

| Skill | P0 | P1 | contract.json | tests/ | CLI --dry-run | Veredito |
|---|---|---|---|---|---|---|
| project-status-auditor | 0 | 4 | ⚠️ incompleto | ✅ | ❌ | Corrigir P1 antes do cron |
| telnyx-voice-sms | **2** | 6 | ❌ ausente | ❌ | ❌ | **NÃO production-ready** |
| ask-vps-hermes | **2** | 5 | ❌ ausente | ❌ | ❌ | **Bloquear até fix** |
| hermes-purchase | **1** | 6 | ❌ ausente | parcial | ❌ | **NÃO production-ready** |
| google-workspace-axtro | **2** | 6 | ❌ ausente | ❌ | ❌ | **Já roda em prod SEM gate** |
| axtro-factory-monitor | 2* | 6 | ❌ ausente | ✅ | parcial | *P0 já corrigidos em ciclo anterior |

**Tema transversal:** 5 das 6 skills **não tinham `contract.json`** — num
daemon autônomo 24/7, isso significa **zero kill-switch declarativo, zero
teto de custo formal, zero `enabled=false`**. A segurança dessas skills
vivia inteiramente como prosa no SKILL.md, dependendo da disciplina do LLM
— não é enforcement. Skills de **comunicação externa** (google-workspace,
telnyx) e a **ponte** (ask-vps) têm superfície de prompt-injection real,
porque o daemon processa conteúdo não-confiável (Telegram, emails).

---

## P0 por skill (segurança — os que exigem correção antes de qualquer ativação)

### telnyx-voice-sms — 2 P0

1. **Vazamento de OTP/2FA por endpoint público sem auth** — `webhook_server.py:331-342`.
   `GET /sms/last` retorna o último SMS incluindo `verification_code` (código
   2FA extraído). O servidor sobe em `0.0.0.0` atrás de Caddy HTTPS público.
   Qualquer um que descubra a URL lê os códigos de verificação de contas da
   empresa — vazamento direto de segredo operacional.

2. **SMS/ligação para qualquer número sem gate** — `make_call.py:24-26`,
   `send_sms.py`. Ações de mundo real (E.164 arbitrário) sem `--dry-run`, sem
   allowlist de destino, sem rate-limit, sem teto de custo. A regra
   "confirmar antes de ligar para terceiros" existe **só como comentário**.
   Num daemon 24/7, nada no código impede execução direta (exposição TCPA +
   custo Telnyx ilimitado).

### ask-vps-hermes — 2 P0

1. **Ativa por default sem kill-switch** — o loader do daemon
   (`agent/skill_utils.py`) descobre skills só por SKILL.md, não conhece
   `contract.json`. Sem `enabled=false`, a skill entra em produção no momento
   em que o arquivo existe — e encaminha ações de efeito real (email via
   Google Workspace, SMS/ligação via Telnyx) sem gate local.

2. **Ponte de prompt-injection para credenciais da empresa** — `ask_vps.py:36-49`.
   Encaminha texto **arbitrário** como instrução direta ao Hermes da VPS (que
   detém Google Workspace + Telnyx) sem allowlist, sem sanitização, sem
   confirmação. Conteúdo injetado num email/Telegram lido pelo daemon local
   pode ser relayado como comando de ação ao agente da VPS. A única defesa
   citada é confiança transitiva nos "gates dele" (SKILL.md:47-48) — não
   verificável nem garantida por esta skill.

### google-workspace-axtro — 2 P0

1. **Produção sem gate, poder de comunicação externa** — a skill já executou
   em produção no daemon (`references/gmail-unread-count.md:26` mostra run
   real em `/opt/data/skills/...` no VPS com dados reais da inbox) SEM
   `contract.json`, sem `enabled=false`, sem `autonomy_ring`. Tem
   `gmail.py:44` (send), `drive.py:80-83` (share), `calendar_events.py:75-77`
   (insert com `sendUpdates="all"` que emaila convidados externos). Toda a
   contenção é prosa no SKILL.md.

2. **Canal de exfiltração autônomo** — `drive.py:74-84`. `share` concede até
   `role=writer` a **qualquer** email externo, e o SKILL.md:136-137 classifica
   compartilhar como ação autônoma. Com Domain-Wide Delegation e escopo Drive
   **total** (`auth.py:31`, `https://www.googleapis.com/auth/drive` completo,
   não `drive.file`), um prompt-injection num email lido pelo daemon pode
   compartilhar qualquer arquivo do Drive corporativo para fora, sem gate.

### hermes-purchase — 1 P0

1. **Gate humano é convenção, não enforcement** — `request_purchase.py:97-117`.
   `confirm --status aprovada` é o **mesmo CLI** que o daemon usa para
   `request`. Nada prova que um humano aprovou (sem token, sem canal separado,
   sem verificação de origem). Num daemon 24/7, o agente pode se auto-aprovar
   e liberar o teto mensal sozinho — exatamente a invariante que o SKILL.md
   declara garantir.

### axtro-factory-monitor — 2 P0 (JÁ CORRIGIDOS em ciclo anterior)

1. Falha total dos coletores virava "✅ Tudo tranquilo, sem segredo vazado"
   (`briefing.py:109-113`) — falsa garantia de segurança.
2. Vigia de segredo era código morto — `'token'` em `VALUE_PLACEHOLDER_WORDS`
   suprimia todo `TOKEN=segredo-real`.

**Nota:** ambos já haviam sido corrigidos numa sessão anterior (registrado na
memória do projeto). Reaparecem aqui porque a auditoria os re-encontrou —
não são débito aberto.

---

## P1 consolidado (funcional/contrato — corrigir antes de produção)

- **`contract.json` ausente em 5 skills** — sem kill-switch, teto, autonomy_ring.
- **`tests/` ausente** em telnyx-voice-sms, ask-vps-hermes, google-workspace-axtro.
- **Bypass por NaN (hermes-purchase)** — `--amount nan` passa por todos os blockers como `PODE_PERGUNTAR`; se aprovado, `month_to_date_spent` vira NaN e o teto mensal nunca mais dispara (fail-open permanente).
- **Ledger sem lock/atomicidade (hermes-purchase)** — `_rewrite` reescreve o ledger inteiro sem `flock`/`os.replace`; crash trunca o livro-caixa; linha corrompida é pulada silenciosamente → gasto some da soma → teto reseta.
- **`TELNYX_VERIFY_SIGNATURE=false` desliga toda a validação silenciosamente** (telnyx) — atacante injeta `message.received` forjado com OTP falso.
- **Escopo Drive total** (google-workspace) — `docs/sheets/slides` pedem `auth/drive` completo só pra mover arquivo; `drive.file` bastaria; amplifica o raio de dano da chave DWD.
- **`find_repos` só desce 1 nível** (project-status-auditor) — repos aninhados como o próprio daemon nunca aparecem; `total==0` vira "Tudo limpo" (falso sucesso).
- **Custo sem teto** (ask-vps) — cada chamada dispara execução completa do LLM na VPS sem `max_daily_cost_usd`, sem rate-limit.

---

## Riscos transversais

1. **Prompt-injection → ação externa.** O daemon lê Telegram/email
   (conteúdo não-confiável) e tem skills que enviam email, compartilham Drive,
   mandam SMS. Sem gate mecânico, uma instrução injetada vira ação real.
2. **Gate-como-prosa.** Toda a contenção das skills sensíveis está no texto
   do SKILL.md, que só o LLM "lê e obedece" — não é enforcement.
3. **Sem kill-switch declarativo.** O loader não conhece `contract.json`, então
   `enabled=false` sozinho não desliga a skill no runtime atual — precisa
   também de enforcement no próprio script (o que os fixes deste ciclo fazem
   via gate de dupla-env no código).

---

## Fila de correção priorizada (ordem aplicada no ciclo)

| Ordem | Skill | Ação | Corrigível no repo? |
|---|---|---|---|
| 1 | google-workspace-axtro | Bloquear `drive.share` externo + allowlist + dry-run + contract | ✅ (fix aplicado — ver SECURITY_FIX_REPORT) |
| 2 | telnyx-voice-sms | Auth no `/sms/last` + máscara OTP + gate/allowlist/teto em send/call | ✅ |
| 3 | ask-vps-hermes | Kill-switch + allowlist de intent + sanitização + envelope | ✅ |
| 4 | hermes-purchase | Enforcement real do gate (token fora do daemon) + NaN + audit log | ✅ |

Os P1 de integridade que não são P0 mas são perigosos num daemon financeiro
(NaN, ledger sem lock) foram incluídos no fix de `hermes-purchase`. Os P1
restantes (escopo Drive, `find_repos`, custo ask-vps) estão listados como
risco residual no `SECURITY_FIX_REPORT.md`.

## Veredito por skill

- **project-status-auditor:** pode ir a staging após corrigir os 4 P1 (nenhum P0). Já tem contract corrigido neste ciclo.
- **telnyx-voice-sms / ask-vps-hermes / google-workspace-axtro / hermes-purchase:** `enabled=false` obrigatório até os P0 fecharem — o que este ciclo faz. Depois: staging, nunca produção sem revisão humana explícita por causa do poder de ação externa/financeira.
