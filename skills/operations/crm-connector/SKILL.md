---
name: crm-connector
description: "Conector REST generico e multi-conexao para qualquer CRM que o Fernando der acesso: registra credenciais (base URL + API key) e um mapa de operacoes nomeadas por conexao, depois chama essas operacoes. Leituras livres, escritas com gate de dry-run."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
dependencies: [requests>=2.31.0]
metadata:
  hermes:
    tags: [CRM, Integration, REST, Operations, HumanGate]
    related_skills: [dispatch-job, hermes-purchase]
---

# CRM Connector (REST generico)

Da ao Hermes a capacidade de ler e atualizar QUALQUER CRM que o Fernando decidir dar
acesso, sem precisar de uma skill nova a cada vez. Ele nao sabe de antemao o schema do
CRM, entao esta skill nao assume nada sobre "o que e um CRM": ela e a plumbing generica
(conexao nomeada + mapa pequeno de operacoes) mais o formato de config que um humano
preenche uma vez, por CRM.

Isso segue o mesmo padrao ja usado no Axtro Agent (tenant product, outro repo:
`00_CONTROL_TOWER/control-tower/src/lib/aurora-read.ts` e o tipo de integracao
`crm_rest` em `supabase/migrations/0030_org_integrations_connector_types.sql`): base_url +
api_key por conexao. Aqui a generalizacao vai um passo alem porque o Fernando precisa
de MULTIPLAS conexoes nomeadas (varios projetos/clientes ao longo do tempo) e de um
jeito de mapear as operacoes especificas de cada CRM sem editar codigo.

## Quando usar

| O usuario diz algo como... | Use |
|---|---|
| "conecta um CRM chamado X, essa e a URL, essa e a API key" | `manage_connection.py register` |
| "no CRM X, o endpoint de listar leads e Y, mapeia isso" | `manage_connection.py set-operation` |
| "quais CRMs estao conectados?" | `manage_connection.py list` |
| "lista os leads do CRM X" | `crm_call.py --connection X --operation list_leads` |
| "pega o lead 123 no CRM X" | `crm_call.py --connection X --operation get_lead --param id=123` |
| "muda o lead 123 pra 'ganho' no CRM X" | `crm_call.py --connection X --operation update_stage --param id=123 --param stage=won --execute` (so dispara com o gate liberado) |

## Como funciona (visao geral)

1. **Registrar uma conexao** (`manage_connection.py register`): nome, base_url, estilo
   de auth (header customizado tipo `apikey`, ou `Authorization: Bearer`) e a api_key.
   Guardado localmente, nunca no repo.
2. **Mapear operacoes** (`manage_connection.py set-operation`): um humano (o Fernando,
   ou o proprio agente seguindo instrucao dele) declara, uma vez por operacao, o metodo
   HTTP + path (com `{placeholders}`) + (para escritas) um template de body.
3. **Chamar operacoes** (`crm_call.py`): dado `--connection`, `--operation` e
   `--param chave=valor`, monta a URL/headers/body a partir do mapeamento salvo e faz a
   chamada, respeitando o gate de leitura/escrita abaixo. A skill NUNCA monta uma
   URL/metodo arbitrario que alguem peca na hora, so o que ja foi configurado.

## Onde as credenciais ficam

Mesma logica de armazenamento da skill bundled `google-workspace` (token/client-secret
como arquivo JSON dentro de `HERMES_HOME`, nunca hardcoded, nunca commitado): aqui o
arquivo guarda um DICIONARIO de conexoes nomeadas em vez de uma so.

- Caminho: `HERMES_HOME/crm_connector/connections.json` (padrao); pode ser sobrescrito
  com a env `CRM_CONNECTOR_STORE_PATH`.
- Escrito com permissao `0600` (so o dono le/escreve).
- `api_key` nunca aparece em claro em `list`/`show` (mascarado, so os ultimos 4
  caracteres) nem em nenhuma saida de `crm_call.py` (headers sempre redigidos nas
  previews de dry-run).

## Formato do config por conexao

```json
{
  "connections": {
    "<nome>": {
      "base_url": "https://api.exemplo.com",
      "auth": {
        "style": "header",
        "header_name": "apikey",
        "prefix": ""
      },
      "api_key": "sk_live_xxx",
      "operations": {
        "<nome_da_operacao>": {
          "method": "GET",
          "path": "/leads/{id}",
          "body_template": null
        }
      },
      "created_at": "...",
      "updated_at": "..."
    }
  }
}
```

- `auth.style`: `"header"` (nome de header configuravel via `auth.header_name`, valor
  = `auth.prefix` + api_key, prefix default vazio) ou `"bearer"` (atalho pra
  `Authorization: Bearer <api_key>`, mesmo estilo de auth usado pela Aurora Solar em
  `aurora-read.ts`; `auth.prefix` sobrescreve o `"Bearer "` default se precisar).
- `operations.<nome>.method`: `GET`, `HEAD`, `POST`, `PUT`, `PATCH` ou `DELETE`. **Este
  campo, sozinho, decide se a operacao e leitura ou escrita** (GET/HEAD = leitura,
  qualquer outro verbo = escrita) - nao existe jeito de configurar uma operacao PATCH
  pra ser tratada como leitura e pular o gate.
- `operations.<nome>.path`: path relativo ao `base_url`, com `{placeholder}` pra
  parametros (ex.: `/leads/{id}`). Cada placeholder precisa vir em `--param
  placeholder=valor` na hora da chamada; o valor e URL-encoded antes de entrar na URL
  final (fecha injecao via parametro).
- `operations.<nome>.body_template`: so pra escritas. Um objeto JSON onde qualquer
  string EXATAMENTE igual a `"{nome}"` vira o valor cru do parametro `nome` (tipo
  preservado); uma string que so CONTEM `{nome}` sofre interpolacao textual. `null`/
  ausente = sem body.

## Exemplo completo trabalhado: "Ecoloop CRM" hipotetico

Supondo que o Fernando diga: "conecta um CRM chamado Ecoloop, a URL base e
`https://api.ecoloopcrm.com`, autentica com header `apikey`, aqui esta a chave" e
depois "o endpoint de listar leads e GET /leads e o de mudar o estagio e PATCH
/leads/{id} com body `{\"stage\": \"...\"}`":

```bash
# 1) registrar a conexao (a api key pode vir por --api-key, --api-key-env ou
#    --api-key-stdin; ver manage_connection.py --help)
python scripts/manage_connection.py register \
  --name ecoloop \
  --base-url https://api.ecoloopcrm.com \
  --auth-style header --header-name apikey \
  --api-key sk_live_xxxxxxxx

# 2) mapear as operacoes (uma vez por operacao; pode adicionar mais depois)
python scripts/manage_connection.py set-operation \
  --name ecoloop --operation list_leads --method GET --path /leads

python scripts/manage_connection.py set-operation \
  --name ecoloop --operation get_lead --method GET --path /leads/{id}

python scripts/manage_connection.py set-operation \
  --name ecoloop --operation update_stage --method PATCH --path /leads/{id} \
  --body '{"stage": "{stage}"}'

# 3) ler (livre, chama a API de verdade na hora)
python scripts/crm_call.py --connection ecoloop --operation list_leads
python scripts/crm_call.py --connection ecoloop --operation get_lead --param id=123

# 4) escrever (dry-run por padrao; mostra o que FARIA sem tocar rede)
python scripts/crm_call.py --connection ecoloop --operation update_stage \
  --param id=123 --param stage=won
# -> {"dry_run": true, "kind": "write", "would_call": {"method": "PATCH",
#     "url": "https://api.ecoloopcrm.com/leads/123",
#     "headers": {"apikey": "***REDACTED***"}, "body": {"stage": "won"}}, ...}

# 5) escrever de verdade (precisa do gate triplo + --execute)
HERMES_ALLOW_EXECUTE=true CRM_CONNECTOR_ENABLED=true \
  python scripts/crm_call.py --connection ecoloop --operation update_stage \
  --param id=123 --param stage=won --execute
```

## Leitura vs escrita (gate de seguranca)

> **Leituras (GET/HEAD) sao livres.** `list_leads`/`get_lead` chamam a API de verdade
> assim que a conexao/operacao existirem, sem gate nenhum, contanto que voce nao passe
> `--dry-run` explicito (que so faz uma previa, sem rede). Mesmo padrao de
> `google-workspace-axtro`'s `gmail.py list`/`drive.py find`: leitura sempre autonoma.

> **Escritas (qualquer verbo != GET/HEAD) sao dry-run por padrao PERMANENTE.**
> `update_stage`/`move_pipeline`/create/delete so tem efeito real se, ao mesmo tempo:
> (a) `--dry-run` NAO foi passado, (b) `HERMES_ALLOW_EXECUTE=true`, (c)
> `CRM_CONNECTOR_ENABLED=true`. Faltando qualquer uma, devolve `{"dry_run": true,
> "would_call": {...}}` sem nenhum efeito real. `--dry-run` explicito sempre vence,
> mesmo com as duas envs setadas. Mesmo idioma exato de
> `skills/communication/telnyx-voice-sms/scripts/_send_policy.py` e
> `skills/operations/dispatch-job/scripts/_dispatch_policy.py`
> (`gate_allows_execute(dry_run_flag, env)`), replicado aqui em
> `scripts/_crm_policy.py`.

Essa distincao e decidida SOMENTE pelo metodo HTTP declarado na operacao
(`_crm_policy.infer_kind`): GET/HEAD = leitura, qualquer outro = escrita. Nao existe
campo de config (nem um suposto `"kind": "read"` numa operacao PATCH) que rebaixe uma
escrita pra leitura e pule o gate.

## Governanca (contract.json + chokepoint)

Esta e uma skill GOVERNADA (registrada em `axtro/GOVERNED_SKILLS.txt`). Nasce
`enabled: false`, `activation_stage: "staging"` como toda skill nova (regra de
nascimento do `axtro/SKILL_STANDARD.md`). Ativacao em producao (setar `enabled: true`
no contract + `HERMES_ALLOW_EXECUTE`/`CRM_CONNECTOR_ENABLED` fora do daemon) e ato
humano.

Como esta skill guarda credenciais num arquivo em vez de env var fixa (precisa suportar
MULTIPLAS conexoes nomeadas, o que uma unica env var nao permite), o campo
`credentials` do contrato fica vazio de proposito - a governanca real de escrita vive
no gate triplo (`_crm_policy.gate_allows_execute`) e no chokepoint
`axtro/dispatch_guard.py` (que intercepta a invocacao do script antes de qualquer
subprocess, igual toda outra skill governada deste repo, ver `axtro/contract_guard.py`
e `axtro/tests/test_dispatch_guard.py`).

## Testando manualmente (sem rede real)

```bash
# 1) suite completa da skill (mock de HTTP, zero rede real)
python3 -m unittest discover -s skills/operations/crm-connector/tests -p 'test_*.py' -v

# 2) validacao de contrato + registry
python3 axtro/tools/validate_contracts.py

# 3) prova de que o chokepoint de governanca reconhece esta skill (mesmo estilo
#    de prova do PR #10, contra o GOVERNED_SKILLS.txt e contract.json reais)
python3 -m unittest axtro.tests.test_dispatch_guard -v
```

## Limitacoes e cuidados

- A skill nunca inventa uma URL/metodo/CRM: so chama o que foi explicitamente mapeado
  em `manage_connection.py set-operation`. Pedir uma operacao nao mapeada devolve
  `{"blocked": true, "available_operations": [...]}` sem tocar rede.
- `--param` so aceita `chave=valor` como string; nao ha parsing automatico de tipo
  (json/int/bool) para manter a chamada previsivel, exceto quando o `body_template`
  usa `"{nome}"` sozinho (nesse caso o TIPO do parametro e preservado no body, so a
  representacao no CLI que e sempre string).
- Toda tentativa de escrita (dry-run, bloqueada ou real) vira uma linha append-only em
  `HERMES_HOME/crm_connector/audit.log` (sem api_key, sem body, sem response) - auditoria
  best-effort, nunca derruba a chamada principal se falhar ao escrever.
- Registrar/alterar uma conexao (`manage_connection.py`) e config local, nao gated pelo
  `--execute`/env duplo (mesma logica do `setup.py --client-secret` do
  `google-workspace`: guardar uma credencial localmente nao e, por si so, uma acao
  externa) - mas nunca imprime a api_key de volta em claro.
