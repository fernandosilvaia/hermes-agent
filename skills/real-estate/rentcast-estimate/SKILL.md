---
name: rentcast-estimate
description: "Estimativa de aluguel (rent estimate) e de valor de mercado (value estimate) de um imóvel por endereço ou lat/lng, via Rentcast AVM. Devolve faixa (low/high) e comparáveis, nunca um número único sem contexto."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
dependencies: [requests>=2.31.0]
metadata:
  hermes:
    tags: [RealEstate, Rentcast, AVM, ReadOnly]
    related_skills: [google-maps-geocode, attom-property]
---

# Rentcast Estimate

Estimativa automatizada (AVM — Automated Valuation Model) de **aluguel** e de
**valor de mercado** de um imóvel, via [Rentcast](https://developers.rentcast.io/).
Sempre devolve uma faixa (low/high) e os comparáveis usados, nunca um número único
sem contexto — a confiança da estimativa varia por região/tipo de imóvel.

## Quando usar

| O usuário diz algo como... | Use |
|---|---|
| "quanto esse imóvel aluga hoje em dia" | `rentcast_call.py --kind rent --address "123 Main St, Boston, MA 02101"` |
| "quanto vale essa casa no mercado" | `rentcast_call.py --kind value --address "..."` |
| "e se tiver 3 quartos e 1800 pés quadrados" | acrescenta `--bedrooms 3 --square-footage 1800` (refina os comparáveis) |

## Autenticação

`RENTCAST_API_KEY` — a chave própria do cliente (conta Rentcast dele), lida via
`agent.secret_scope.get_secret()`, enviada no header `X-Api-Key`.

## Uso

```bash
python3 scripts/rentcast_call.py --kind rent --address "123 Main St, Boston, MA 02101" --json
python3 scripts/rentcast_call.py --kind value --lat 42.3601 --lng -71.0589 --json
python3 scripts/rentcast_call.py --kind rent --address "..." --bedrooms 3 --bathrooms 2 --square-footage 1800 --json
```

Saída (`--json`, `--kind rent`):
```json
{
  "ok": true,
  "kind": "rent",
  "rent": 1620,
  "rent_range_low": 1550,
  "rent_range_high": 1690,
  "subject_property": {"formatted_address": "...", "bedrooms": 3, "bathrooms": 2, "square_footage": 1878},
  "comparables_count": 15
}
```

`--kind value` devolve `price`/`price_range_low`/`price_range_high` no mesmo formato.

## Governança (contract.json)

Anel 0 (leitura pura, determinística, sem ação externa) — nasce `enabled: false`,
`activation_stage: "staging"`. Ativação em produção é ato humano.

## Testando manualmente (sem rede real)

```bash
python3 -m unittest discover -s skills/real-estate/rentcast-estimate/tests -p 'test_*.py' -v
python3 axtro/tools/validate_contracts.py
```

## Limitações

- Precisa de `--address` OU (`--lat` + `--lng`) — nunca os dois omitidos.
- A estimativa é automatizada (AVM), não uma avaliação profissional — sempre
  apresentada como faixa + comparáveis, nunca como valor definitivo.
- Endereços fora da cobertura da Rentcast (a maioria dos EUA, não internacional)
  devolvem erro claro, não um valor aproximado.
