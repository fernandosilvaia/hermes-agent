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
| "o que tenho na agenda essa semana?" | `calendar_events.py list` |

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
python scripts/gmail.py send --to fulano@x.com --subject "Oi" --body "Corpo do email"
python scripts/gmail.py list --max 10
python scripts/gmail.py search --query "from:cliente@x.com is:unread"
python scripts/gmail.py read --id <MESSAGE_ID>
python scripts/gmail.py mark-read --id <MESSAGE_ID>

# Drive
python scripts/drive.py list --max 20
python scripts/drive.py find --name "proposta"
python scripts/drive.py mkdir --name "Relatórios" --parent <FOLDER_ID>
python scripts/drive.py upload --path ./arquivo.pdf --parent <FOLDER_ID>
python scripts/drive.py share --id <FILE_ID> --email fulano@x.com --role writer

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
python scripts/calendar_events.py list --max 10
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
