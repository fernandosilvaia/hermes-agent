---
name: google-workspace-axtro
description: "Agir como funcionário no Google Workspace da Axtro: Gmail, Drive, Docs, Sheets, Slides e Calendar (via Service Account + Domain-Wide Delegation)."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [linux, macos, windows]
dependencies: [google-api-python-client>=2.100.0, google-auth>=2.23.0, google-auth-httplib2>=0.1.1]
metadata:
  hermes:
    tags: [GoogleWorkspace, Email, Drive, Docs, Sheets, Slides, Calendar, Productivity]
    related_skills: [github-auth]
---

> ⚠️ **Não confundir com a skill bundled `google-workspace`** (Nous Research, OAuth de usuário
> com `google_token.json`). Esta skill (`google-workspace-axtro`) é a versão própria da Axtro,
> via Service Account + Domain-Wide Delegation, sem fluxo de consentimento manual — é a que
> deve ser usada por padrão neste ambiente. Prefira sempre esta.

# Google Workspace (Axtro)

Dá ao Hermes a capacidade de agir como um funcionário dentro do Google Workspace da
Axtro, impersonando a conta **axtro@axtroai.com** via Service Account + Domain-Wide
Delegation. Cobre Gmail, Drive, Docs, Sheets, Slides e Calendar.

## Quando usar

Gatilhos em linguagem natural e o script correspondente:

| O usuário diz algo como… | Use |
|---|---|
| "manda um email pra fulano avisando X" | `gmail.py send` |
| "chegou algum email novo do cliente Y?" / "resume minha caixa" | `gmail.py list` / `gmail.py search` |
| "lê esse email pra mim" | `gmail.py read` |
| "lista os arquivos da pasta X" / "acha o arquivo proposta" | `drive.py list` / `drive.py find` |
| "cria uma pasta Relatórios" / "sobe esse arquivo pro Drive" | `drive.py mkdir` / `drive.py upload` |
| "compartilha esse arquivo com fulano@x.com" | `drive.py share` |
| "cria um doc com a ata dessa reunião" | `docs.py create` |
| "cria uma planilha de controle de gastos" | `sheets.py create` |
| "adiciona uma linha na planilha de gastos" | `sheets.py append` |
| "monta uma apresentação com esses tópicos" | `slides.py create` + `slides.py add` |
| "agenda uma reunião com o cliente terça 15h" | `calendar_events.py create` |
| "o que tenho hoje?" / briefing diário | `calendar_events.py today` |
| "o que tenho na agenda essa semana?" | `calendar_events.py range --days 7` |
| "o que vem por aí?" (sem filtro de dia) | `calendar_events.py list` |

## Autenticação (já configurada)

Nada a gerar aqui. As credenciais chegam por variável de ambiente, injetadas pelo cofre
em runtime. O módulo `scripts/auth.py` lê:

- `GOOGLE_SERVICE_ACCOUNT_KEY_JSON` — **string** com o JSON inteiro da chave (o código faz
  `json.loads()`; não é caminho de arquivo).
- `GOOGLE_SERVICE_ACCOUNT_EMAIL`, `GOOGLE_CLIENT_ID` — opcionais, informativos.
- Conta impersonada fixa: `axtro@axtroai.com` (sobrescrevível por `GOOGLE_IMPERSONATED_USER`).

**Teste de fumaça** (rode primeiro para confirmar que a auth funciona):

```bash
python scripts/auth.py
# → "[auth] OK — autenticação funcionando" + o email impersonado
```

Se faltar a variável, o erro é explícito ("rode através do cofre") — nunca falha em silêncio.

## Como chamar

Todos os scripts funcionam como **CLI** (jeito recomendado para o agente shell-out) e como
**biblioteca Python**. Cada CLI imprime JSON no stdout.

```bash
# Gmail
# send é DRY-RUN por padrão e BLOQUEIA destinatários externos (mesmo gate do drive share,
# ver "Segurança" abaixo): externo exige --approve-external + domínio em
# GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS, e a API só é chamada com --execute + as 2 envs.
python scripts/gmail.py send --to colega@axtroai.com --subject "Oi" --body "Corpo do email"
python scripts/gmail.py list --max 10
python scripts/gmail.py search --query "from:cliente@x.com is:unread"
python scripts/gmail.py read --id <MESSAGE_ID>
python scripts/gmail.py mark-read --id <MESSAGE_ID>

# Drive
python scripts/drive.py list --max 20
python scripts/drive.py find --name "proposta"
python scripts/drive.py mkdir --name "Relatórios" --parent <FOLDER_ID>
python scripts/drive.py upload --path ./arquivo.pdf --parent <FOLDER_ID>
# share é DRY-RUN por padrão e BLOQUEIA externos (ver "Segurança do share" abaixo).
# O gate de ambiente (2 envs) vale para CLI E biblioteca: share_file(dry_run=False) sem
# as envs também cai em dry-run (fail-closed).
python scripts/drive.py share --id <FILE_ID> --email colega@axtroai.com --role writer
# externo exige --approve-external E o domínio na env GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS:
python scripts/drive.py share --id <FILE_ID> --email parceiro@outro.com --approve-external --execute

# Docs
python scripts/docs.py create --title "Ata" --body "Texto..." --parent <FOLDER_ID>
python scripts/docs.py create --title "Relatório" --body-file ./texto.md --markdown
python scripts/docs.py read --id <DOC_ID>
python scripts/docs.py insert --id <DOC_ID> --text "Novo parágrafo"

# Sheets
python scripts/sheets.py create --title "Controle de gastos"
python scripts/sheets.py read --id <SHEET_ID> --range "Página1!A1:D10"
python scripts/sheets.py write --id <SHEET_ID> --range "Página1!A1" --values '[["Data","Valor"]]'
python scripts/sheets.py append --id <SHEET_ID> --range "Página1!A1" --values '["01/07","200"]'

# Slides
python scripts/slides.py create --title "Pitch Axtro"
python scripts/slides.py add --id <PRES_ID> --title "Problema" --body "Texto do corpo"
python scripts/slides.py read --id <PRES_ID>

# Calendar
python scripts/calendar_events.py create --summary "Reunião" \
    --start "2026-07-10T15:00:00" --end "2026-07-10T16:00:00" \
    --tz "America/Sao_Paulo" --attendees "a@x.com,b@y.com"
python scripts/calendar_events.py today                # agenda de hoje (nunca desliza pra amanhã se hoje está vazio)
python scripts/calendar_events.py range --days 7        # próximos 7 dias
python scripts/calendar_events.py list --max 10         # próximos N eventos, sem limite de dia
python scripts/calendar_events.py cancel --id <EVENT_ID>
```

## Tratamento de erro esperado

- **Credencial ausente/ inválida** → `WorkspaceAuthError` com mensagem clara (rodar via cofre;
  ou a env não é JSON válido). Não continue; peça para o usuário conferir o cofre.
- **Escopo insuficiente** (`HttpError 403 insufficientPermissions`) → o escopo não foi
  autorizado no admin do Workspace para essa API. Reportar qual serviço falhou.
- **Quota excedida / rate limit** (`HttpError 429` ou `403 rateLimitExceeded`) → esperar e
  tentar de novo mais tarde; não entrar em loop.
- **Arquivo/ID inexistente** (`HttpError 404`) → confirmar o ID; para Drive, buscar por nome
  antes com `drive.py find`.

## 🔒 Segurança de `share`, `send` e `create` (P0 — canal de exfiltração fechado)

Num daemon 24/7 que lê emails/Telegram não-confiáveis, `drive.py share` era um canal
de exfiltração: um prompt-injection podia mandar compartilhar um arquivo corporativo
(até `role=writer`) com **qualquer** email externo, e o escopo do Drive é total. Fechado
assim (lógica pura e testável em `scripts/_share_policy.py`):

**1. Allowlist de domínio (`evaluate_share`).** Por padrão só o próprio domínio da
empresa (`axtroai.com`) é "interno". Destinatário externo é **BLOQUEADO** sem aprovação
explícita; `role=writer` para externo é bloqueado mesmo com aprovação implícita. Amplie a
allowlist interna só via env `GOOGLE_WORKSPACE_SHARE_ALLOWED_DOMAINS` (csv de domínios).

**1b. `--approve-external` NÃO é gate humano sozinho (anti-exfiltração).** A flag
`--approve-external` / `approve_external` é setável pelo PRÓPRIO agente — logo, um
prompt-injection também consegue setá-la. Por isso ela sozinha **não** libera um domínio
arbitrário. Para um destino externo valer, o domínio precisa estar na env
`GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS` (csv de domínios de parceiros pré-aprovados),
que **só o operador humano seta fora de banda**. Vazia por padrão → **nenhum** domínio
externo é destino válido, nem com `--approve-external` e nem com as envs de execução
ligadas. Isso fecha o vetor "auto-aprovar e exfiltrar para `attacker@evil-corp.com`".

**2. Gate de dry-run (default PERMANENTE).** A chamada real à API do Drive só acontece se
**todas** forem verdadeiras ao mesmo tempo:
- o flag `--dry-run` **não** foi passado **e** `--execute` foi passado; **e**
- env `HERMES_ALLOW_EXECUTE == "true"`; **e**
- env `GOOGLE_WORKSPACE_AXTRO_ENABLED == "true"`.

Faltando qualquer uma → **dry-run**: retorna um dict `{"dry_run": true, "would_share": {…}}`
descrevendo o que faria, sem efeito real. `--dry-run` explícito **sempre vence** (o humano
sempre pode forçar o modo seguro). Compartilhar com externo exige também `--approve-external`
(gate humano).

```bash
# Interno, mas ainda dry-run (default) — só descreve, não compartilha:
python scripts/drive.py share --id <FILE_ID> --email colega@axtroai.com
# → {"shared": false, "dry_run": true, "would_share": {...}, "gate": {...}}

# Externo sem aprovação — BLOQUEADO, nem chega na API:
python scripts/drive.py share --id <FILE_ID> --email x@gmail.com --execute
# → {"shared": false, "blocked": true, "verdict": {"decision":"BLOQUEADO", ...}}

# Ação real (interno): precisa das DUAS envs ligadas + --execute:
HERMES_ALLOW_EXECUTE=true GOOGLE_WORKSPACE_AXTRO_ENABLED=true \
  python scripts/drive.py share --id <FILE_ID> --email colega@axtroai.com --role writer --execute

# Ação real com externo aprovado por humano — o domínio do parceiro TEM que estar
# na env de parceiros (setada fora de banda pelo operador); --approve-external sozinho não basta:
HERMES_ALLOW_EXECUTE=true GOOGLE_WORKSPACE_AXTRO_ENABLED=true \
  GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS=outro.com \
  python scripts/drive.py share --id <FILE_ID> --email parceiro@outro.com --approve-external --execute
```

Testes provando o furo fechado (rodam no `python3` do sistema, sem rede/credencial):

```bash
python3 -m unittest discover -s tests -v
```

### ⚠️ Risco residual conhecido: escopo Drive total (não reduzir agora)

`auth.py` usa o escopo **`https://www.googleapis.com/auth/drive`** (Drive inteiro), não o
mais estrito `drive.file` (só arquivos criados/abertos pela app). Isso é um risco residual
**aceito conscientemente**: reduzir para `drive.file` **quebraria `list`/`find`** — que leem
o Drive corporativo e rodam em produção hoje. Portanto **não reduza o escopo agora** (quebra
produção). Recomendação registrada: reavaliar uma **re-autorização** no admin do Google
Workspace (escopos por serviço mais estreitos, ou uma segunda service account só-leitura para
`list`/`find`) numa janela de manutenção com gate humano. Enquanto o escopo for total, a
guarda-corpo do `share` acima é a mitigação principal do vetor de exfiltração.

### ✅ Canais irmãos fechados: `gmail.py send` e `calendar_events.py create`

Enviar email e convidar attendee (que dispara `sendUpdates="all"`) exfiltram dado
corporativo tão bem quanto `drive.py share`. Os dois recebem **o mesmo padrão** acima,
pelo mesmo `scripts/_share_policy.py`:

- **dry-run por padrão + gate de dupla-env.** `send_email`/`create_event` são
  `dry_run=True` por padrão e só chamam a API com `--execute` **e** `HERMES_ALLOW_EXECUTE=true`
  **e** `GOOGLE_WORKSPACE_AXTRO_ENABLED=true` (`resolve_execution`). Vale para CLI **e**
  biblioteca (fail-closed); criar evento sem attendees ainda respeita o gate por ser mutação.
- **allowlist de destinatário externo.** Toda a lista `to`+`cc`+`bcc` (e os attendees do
  evento) passa por `evaluate_recipients` **antes** da API: destinatário externo ao domínio
  da empresa é **BLOQUEADO**, e `--approve-external` sozinho **não** basta — o domínio precisa
  estar em `GOOGLE_WORKSPACE_EXTERNAL_ALLOWED_DOMAINS` (setada fora de banda por um humano).
- **leituras seguem autônomas.** `gmail list`/`search`/`read`/`mark-read` e as leituras de
  agenda (`today`/`range`/`list`) não são mutação e continuam livres.

Provado por `tests/test_comms_gate.py` (pure + wiring por stub, sem rede/credencial):
destinatário/attendee externo → **0 chamadas de API**; PERMITIDO porém dry-run → **0
chamadas**; PERMITIDO + gate aberto → **exatamente 1 chamada**.

### ⚠️ Risco residual conhecido: sem confirmação humana por-requisição

Mesmo com a allowlist de parceiros, um domínio parceiro liberado permite que o agente
compartilhe/mande para **qualquer** endereço daquele domínio sem um humano confirmar aquela
requisição específica. O fechamento robusto pede uma aprovação **fora de banda** por
requisição (ex.: confirmação do dono via Telegram com token que o agente não pode forjar).
A allowlist de parceiros reduz o raio, mas não substitui essa confirmação. P0-restante.

## ⚠️ Ações irreversíveis — confirmar sempre

Estas ações **apagam ou removem dados de forma irreversível** e exigem confirmação explícita
do usuário na conversa antes de executar (o Hermes já tem política de aprovação manual para
ações arriscadas — respeite-a aqui):

- **Apagar email permanentemente** (esta skill só marca como lido / lista; não implementa
  delete justamente por isso — se um dia for adicionado, é ação de confirmação obrigatória).
- **Cancelar evento** (`calendar_events.py cancel`) — some da agenda de todos os convidados.
- **Deletar/mover arquivos do Drive** — a skill faz upload, cria e compartilha, mas **não**
  deleta arquivos; qualquer delete futuro é ação de confirmação obrigatória.

Regra prática: **criar, ler, enviar e organizar** pode ser autônomo dentro dos gates da
empresa; **apagar/cancelar** sempre pergunta antes.
