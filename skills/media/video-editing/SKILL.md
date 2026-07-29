---
name: video-editing
description: "Editar video que ja existe: cortar, juntar clipes, redimensionar pra Reels/TikTok, legendar, extrair/trocar audio, comprimir, thumbnail, velocidade, marca d'agua. Via ffmpeg (ja instalado)."
platforms: [linux, macos, windows]
prerequisites:
  commands: [ffmpeg, ffprobe]
---

# Edicao de Video (ffmpeg)

Edicao mecanica em cima de video que ja existe. Nao gera video novo com IA
(isso seria uma skill separada, tipo text-to-video) — aqui e sempre "pegue
esse arquivo e mexa nele": cortar, juntar, redimensionar, legendar, trocar
audio, comprimir, tirar print, mudar velocidade, colocar logo.

Roda tudo local via `ffmpeg`/`ffprobe`, ja vem instalado no container. Zero
custo de API externa, zero upload pra fora.

## Quando usar

| O usuario pede... | Comando |
|---|---|
| "corta esse video de tal hora até tal hora" | `trim --start --end` |
| "junta esses 3 clipes num só" | `concat` |
| "deixa esse video no formato de Reels/Stories/TikTok" | `resize --preset reels` |
| "converte esse .mov pra .mp4" (ou pra .gif) | `convert` |
| "tira só o áudio desse video" | `extract-audio` |
| "troca a música desse video" / "mistura essa música no video" | `add-audio --mode replace` / `--mode mix` |
| "coloca legenda nesse video" (a partir de um .srt) | `subtitles` |
| "esse video tá pesado demais, comprime" | `compress --target-mb N` |
| "tira uma imagem desse momento do video" | `thumbnail --at HH:MM:SS` |
| "acelera"/"desacelera esse video" | `speed --factor 1.5` |
| "coloca a logo no canto do video" | `watermark --position bottom-right` |

## Como chamar

```bash
python scripts/video_edit.py info video.mp4
python scripts/video_edit.py trim video.mp4 out.mp4 --start 00:00:10 --end 00:00:25
python scripts/video_edit.py concat out.mp4 clipe1.mp4 clipe2.mp4 clipe3.mp4
python scripts/video_edit.py resize video.mp4 out.mp4 --preset reels
python scripts/video_edit.py convert video.mov out.mp4
python scripts/video_edit.py extract-audio video.mp4 out.mp3
python scripts/video_edit.py add-audio video.mp4 musica.mp3 out.mp4 --mode mix --volume 0.3
python scripts/video_edit.py subtitles video.mp4 legendas.srt out.mp4
python scripts/video_edit.py compress video.mp4 out.mp4 --target-mb 16
python scripts/video_edit.py thumbnail video.mp4 out.jpg --at 00:00:03
python scripts/video_edit.py speed video.mp4 out.mp4 --factor 1.5
python scripts/video_edit.py watermark video.mp4 logo.png out.mp4 --position bottom-right
```

Toda operação imprime um JSON com o caminho de saída (e detalhes específicos
da operação). Erro real do ffmpeg sempre sobe no `stderr`/exceção, nunca é
escondido — se der erro, leia a mensagem antes de tentar de novo.

## Presets de redimensionamento (`resize --preset`)

| Preset | Resolução | Uso |
|---|---|---|
| `reels` / `tiktok` / `stories` | 1080x1920 (9:16) | Instagram Reels, TikTok, Stories |
| `square` | 1080x1080 (1:1) | Feed quadrado |
| `landscape` / `youtube` | 1920x1080 (16:9) | YouTube, apresentação |

O resize nunca distorce: dá zoom pra cobrir o formato alvo e corta o excesso
centralizado (`scale...increase` + `crop`), não espreme a imagem.

## Notas importantes

- **`trim` sem `--fast`** reencoda pra garantir corte exato no frame pedido
  (um pouco mais lento). Com `--fast` usa stream copy (rápido, mas o corte
  cai no keyframe mais próximo, pode não ser no segundo exato).
- **`concat`** sempre reencoda — tolera clipes com codec/resolução diferentes
  entre si, o que a concatenação por stream copy não tolera.
- **`convert` pra `.gif`** já gera paleta otimizada (2 passos) pra não sair
  borrado — GIF direto sem paleta fica feio.
- **`compress --target-mb`** calcula o bitrate necessário pra caber no
  tamanho pedido; sem `--target-mb` usa CRF (qualidade constante, tamanho
  variável, mais previsível visualmente).
- **`subtitles`** grava a legenda direto na imagem (hardsub), não dá pra tirar
  depois. Se o pedido for legenda "removível"/opcional, isso está fora do
  escopo desta skill (precisaria de track de legenda soft, mux separado).

## Autonomia

Anel 0. Só lê e escreve arquivo local, nunca chama API externa nem gasta
dinheiro. Segue as mesmas regras de escrita de arquivo do resto do agente
(nunca sobrescreve o `input` original, sempre escreve num `output` novo).
