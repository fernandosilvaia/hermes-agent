---
name: google-maps-geocode
description: "Geocodifica um endereço em texto pra lat/lng (e o inverso) via Google Maps Geocoding API. Usado como base pra outras skills imobiliárias (attom-property, rentcast-estimate) que aceitam coordenada."
version: 1.0.0
author: Hermes Agent
license: MIT
platforms: [macos, linux]
dependencies: [requests>=2.31.0]
metadata:
  hermes:
    tags: [RealEstate, Geocoding, GoogleMaps, ReadOnly]
    related_skills: [rentcast-estimate, attom-property]
---

# Google Maps Geocode

Converte um endereço em texto livre pra coordenada (`lat`/`lng`) e vice-versa, via
[Google Maps Geocoding API](https://developers.google.com/maps/documentation/geocoding).
Skill de apoio: várias APIs imobiliárias (ATTOM, Rentcast) aceitam ou preferem
lat/lng em vez de endereço em texto livre, e endereço digitado por humano costuma vir
incompleto/ambíguo — geocodificar primeiro reduz erro nas duas skills seguintes.

## Quando usar

| O usuário diz algo como... | Use |
|---|---|
| "onde fica 123 Main St, Boston MA" | `geocode.py --address "123 Main St, Boston, MA"` |
| "que endereço é esse lat/lng" | `geocode.py --lat 42.36 --lng -71.06` (reversa) |
| (internamente, antes de chamar attom-property/rentcast-estimate com endereço ambíguo) | geocodifica primeiro, passa lat/lng adiante |

## Autenticação

`GOOGLE_MAPS_API_KEY` — a chave própria do cliente (Google Cloud Console dele,
API "Geocoding API" habilitada), nunca uma chave da Axtro. Lida via
`agent.secret_scope.get_secret()` (nunca `os.environ` direto — ver Fase 1 do
hardening multi-tenant), passada como query param `key` na chamada.

## Uso

```bash
python3 scripts/geocode.py --address "1600 Amphitheatre Parkway, Mountain View, CA" --json
python3 scripts/geocode.py --lat 37.4224 --lng -122.0842 --json   # reversa
python3 scripts/geocode.py --address "endereço incompleto" --text  # resumo humano
```

Saída (`--json`):
```json
{
  "ok": true,
  "formatted_address": "1600 Amphitheatre Pkwy, Mountain View, CA 94043, USA",
  "lat": 37.4224764,
  "lng": -122.0842499,
  "place_id": "ChIJ2eUgeAK6j4ARbn5u_wAGqWA",
  "components": {"city": "Mountain View", "state": "CA", "postal_code": "94043", "country": "US"}
}
```

Endereço não encontrado (`ZERO_RESULTS`) devolve `{"ok": false, "status": "ZERO_RESULTS", ...}`
— nunca inventa coordenada aproximada.

## Governança (contract.json)

Anel 0 (leitura pura, determinística, sem ação externa) — nasce `enabled: false`,
`activation_stage: "staging"` como toda skill nova. Ativação em produção é ato humano.

## Testando manualmente (sem rede real)

```bash
python3 -m unittest discover -s skills/real-estate/google-maps-geocode/tests -p 'test_*.py' -v
python3 axtro/tools/validate_contracts.py
```

## Limitações

- Não faz autocomplete/sugestão de endereço — só geocodificação direta e reversa.
- Um endereço ambíguo (ex.: "Main St" sem cidade) pode devolver o primeiro resultado
  da Google, não necessariamente o pretendido — sempre mostra `formatted_address`
  de volta pra o humano confirmar visualmente.
