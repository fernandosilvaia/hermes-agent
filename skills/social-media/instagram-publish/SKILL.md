---
name: instagram-publish
description: "Preparar e publicar post/Reels no Instagram Business (Meta Graph API), sempre em duas etapas: rascunho (nunca público) e publicação real (só com aprovação explícita)."
platforms: [linux, macos, windows]
prerequisites:
  env:
    - META_ACCESS_TOKEN (ou META_APP_API_TOKEN)
    - META_PAGE_ID
---

# Instagram Publish (Meta Graph API)

Publica foto, vídeo ou Reels na conta Instagram Business, em **duas etapas
sempre separadas**: preparar (rascunho, nunca vai ao ar sozinho) e publicar
de verdade. Use `media/video-editing` primeiro se o vídeo/imagem precisar de
corte, redimensionamento pro formato certo, legenda etc.

## Regra de ouro (inegociável)

`draft` (etapa 1) **NUNCA publica nada** — só cria o rascunho do lado do
Instagram, ainda invisível pro público. `publish` (etapa 2) é quem publica
de verdade. **Só rode `publish` depois que o Fernando confirmar
explicitamente, NA CONVERSA, que quer publicar ESSE post específico.** Nunca
assuma aprovação de uma vez anterior nem publique "porque parece óbvio que
ele ia querer".

## Fluxo completo

```bash
# 0. (se precisar editar antes) use a skill media/video-editing primeiro

# 1. Hospedar o arquivo local temporariamente numa URL pública
#    (o Instagram só aceita buscar mídia via URL, não recebe upload direto)
python scripts/instagram_publish.py upload /caminho/do/video_pronto.mp4
# → {"public_url": "https://hermes.axtroai.com/media/<uuid>.mp4"}
# some sozinho em 30min — se demorar mais que isso pra publicar, faça upload de novo.

# 2. Criar o rascunho (NÃO publica) e mostrar pro Fernando o que ficou pronto
python scripts/instagram_publish.py draft \
    --media-url https://hermes.axtroai.com/media/<uuid>.mp4 \
    --caption "Legenda do post aqui" \
    --type REELS
# → {"container_id": "...", "status": "rascunho criado, AINDA NAO PUBLICO..."}

# (opcional, pra video/reels grande: Meta processa de forma assincrona)
python scripts/instagram_publish.py status --container-id <container_id>

# 3. SÓ DEPOIS que o Fernando disser "pode publicar" (ou equivalente) pra
#    ESSE post: publica de verdade
python scripts/instagram_publish.py publish --container-id <container_id>
# → {"post_id": "...", "permalink": "https://www.instagram.com/p/.../", "status": "PUBLICADO"}

# Se o Fernando disser pra não publicar, descarte:
python scripts/instagram_publish.py cancel --container-id <container_id>
```

`--type`: `IMAGE`, `VIDEO` ou `REELS` (padrão `REELS`, o formato que o
Instagram mais empurra no algoritmo hoje).

## Credenciais

| Variável | Para quê | Como conseguir |
|---|---|---|
| `META_ACCESS_TOKEN` (ou `META_APP_API_TOKEN`) | autenticar na Graph API | Meta for Developers → seu App → Graph API Explorer, gerar token de longa duração com `instagram_basic`, `instagram_content_publish`, `pages_show_list`, `pages_read_engagement` |
| `META_PAGE_ID` | achar a conta Instagram vinculada | Page ID do Facebook da marca, vinculada a uma conta Instagram Business/Creator (Meta Business Suite → Configurações → Contas vinculadas) |

Pré-requisito no lado do Instagram: a conta precisa ser **Business ou
Creator** (não pessoal), vinculada a uma **Página do Facebook**. Sem isso, a
Graph API não expõe `instagram_business_account` e `draft` falha com erro
claro.

## Hospedagem de mídia pública

`upload` copia o arquivo pra `/opt/data/public_media` (que o Caddy da VPS
expõe em `https://hermes.axtroai.com/media/<uuid>.<ext>`, nome de arquivo
aleatório, não listável, não adivinhável). Um cron na VPS apaga arquivo com
mais de 30 minutos. **Isso só existe hoje na instância da VPS** (o Axtro
Agent do Fernando) — se essa skill for usada num daemon hospedado em outro
lugar (Railway, etc.), precisa de uma rota pública equivalente lá, ou usar
outro provedor de hospedagem temporária e passar a URL manualmente pro
`draft` (pule o `upload`).

## Erros comuns

- **"Nenhuma conta Instagram Business vinculada a essa Page"**: a conta do
  Instagram não é Business/Creator, ou não está linkada à Page certa no Meta
  Business Suite.
- **Token expirado/sem permissão**: tokens de usuário costumam expirar em
  60 dias; prefira token de sistema (System User) do Business Manager pra
  não precisar renovar toda hora.
- **Vídeo/Reels demora a processar**: use `status` antes de `publish` pra
  confirmar `status_code: FINISHED` — publicar um container ainda em
  `IN_PROGRESS` falha.

## Autonomia

Anel 1 (escreve em sistema externo, mas só o `publish` tem efeito
irreversível de verdade). `draft`/`upload`/`status`/`cancel` são seguros de
rodar livremente. `publish` exige aprovação humana explícita por post, sempre
— nunca automatize isso num cron sem um humano confirmando cada post
individualmente antes.
