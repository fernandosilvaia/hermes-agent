---
name: attom-property
description: "Dados de propriedade via ATTOM Data — detalhe completo (lote, construção, quartos/banheiros), resumo rápido (snapshot) ou avaliação automatizada (AVM), por endereço."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
dependencies: [requests>=2.31.0]
metadata:
  hermes:
    tags: [RealEstate, ATTOM, PropertyData, AVM, ReadOnly]
    related_skills: [google-maps-geocode, rentcast-estimate]
---

# ATTOM Property Data

Dados de propriedade via [ATTOM Data API](https://api.developer.attomdata.com/docs) —
três níveis de detalhe, escolhidos por `--kind`:

- **`detail`** — características completas (tamanho do lote, tipo de construção,
  quartos, banheiros, ano de construção).
- **`snapshot`** — resumo rápido (endereço, tipo de imóvel, características básicas)
  pra exibição/triagem rápida.
- **`avm`** — avaliação automatizada (AVM) com score de confiança, sem precisar de
  todas as características do imóvel.

## Quando usar

| O usuário diz algo como... | Use |
|---|---|
| "me dá os detalhes completos desse imóvel" | `attom_call.py --kind detail --address1 "..." --address2 "..."` |
| "resumo rápido desse endereço" | `attom_call.py --kind snapshot --address1 "..." --address2 "..."` |
| "qual a avaliação automática desse imóvel" | `attom_call.py --kind avm --address1 "..." --address2 "..."` |

## Autenticação

`ATTOM_API_KEY` — a chave própria do cliente (conta ATTOM dele), lida via
`agent.secret_scope.get_secret()`, enviada no header `APIKey`.

## Uso

```bash
python3 scripts/attom_call.py --kind detail \
  --address1 "468 Sequoia Dr" --address2 "Smyrna, DE 19977" --json

python3 scripts/attom_call.py --kind avm \
  --address1 "468 Sequoia Dr" --address2 "Smyrna, DE 19977" --json
```

`--address1` é a rua (número + nome); `--address2` é cidade + estado + CEP — a ATTOM
exige os dois campos separados (não um endereço único em texto livre).

Saída (`--json`):
```json
{
  "ok": true,
  "kind": "detail",
  "property": { ... dados brutos da ATTOM, já sem o wrapper "status" ... }
}
```

Erro (endereço não encontrado, `status.code` != 0):
```json
{"ok": false, "kind": "detail", "status_code": 400, "attom_status": {"code": 400, "msg": "SuccessWithoutResult"}}
```

## Governança (contract.json)

Anel 0 (leitura pura, determinística, sem ação externa) — nasce `enabled: false`,
`activation_stage: "staging"`. Ativação em produção é ato humano.

## Testando manualmente (sem rede real)

```bash
python3 -m unittest discover -s skills/real-estate/attom-property/tests -p 'test_*.py' -v
python3 axtro/tools/validate_contracts.py
```

## Limitações

- Exige `address1` + `address2` separados — nunca infere a divisão de um endereço
  único (evita erro de parsing silencioso; use `google-maps-geocode` antes se o
  endereço vier em texto livre ambíguo).
- Cobertura só EUA. `status.code=400`/"SuccessWithoutResult" é resultado válido
  (endereço bem formado, sem dado disponível), reportado como `ok: false`, não como
  exceção — o chamador decide o que fazer.
