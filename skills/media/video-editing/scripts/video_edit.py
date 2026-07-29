"""
video_edit.py — Edicao mecanica de video via ffmpeg (ja instalado no container).

Cobre as tarefas do dia a dia em cima de video que ja existe: cortar, juntar
clipes, redimensionar pra formato de rede social, legendar, extrair/trocar
audio, comprimir, tirar thumbnail, mudar velocidade e colocar marca d'agua.
Nao gera video novo com IA, so edita o que ja existe.

Uso como biblioteca:
    from video_edit import trim, concat, resize, convert, extract_audio, \
        add_audio, burn_subtitles, compress, thumbnail, speed, watermark, probe

Uso como CLI (um subcomando por operacao):
    python video_edit.py info video.mp4
    python video_edit.py trim video.mp4 out.mp4 --start 00:00:10 --end 00:00:25
    python video_edit.py concat out.mp4 clipe1.mp4 clipe2.mp4 clipe3.mp4
    python video_edit.py resize video.mp4 out.mp4 --preset reels
    python video_edit.py convert video.mov out.mp4
    python video_edit.py extract-audio video.mp4 out.mp3
    python video_edit.py add-audio video.mp4 musica.mp3 out.mp4 --mode mix --volume 0.3
    python video_edit.py subtitles video.mp4 legendas.srt out.mp4
    python video_edit.py compress video.mp4 out.mp4 --target-mb 16
    python video_edit.py thumbnail video.mp4 out.jpg --at 00:00:03
    python video_edit.py speed video.mp4 out.mp4 --factor 1.5
    python video_edit.py watermark video.mp4 logo.png out.mp4 --position bottom-right

Todas as operacoes rodam localmente via subprocess (nunca shell=True, args
sempre em lista), nunca sobem arquivo pra fora, nunca chamam API paga. So
leem/escrevem arquivo local. Erro real do ffmpeg (stderr) sempre sobe pro
chamador, nunca e escondido.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

PRESETS = {
    "reels": (1080, 1920),
    "tiktok": (1080, 1920),
    "stories": (1080, 1920),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
    "youtube": (1920, 1080),
}

_POSITIONS = {
    "bottom-right": "W-w-10:H-h-10",
    "bottom-left": "10:H-h-10",
    "top-right": "W-w-10:10",
    "top-left": "10:10",
    "center": "(W-w)/2:(H-h)/2",
}


def _check_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError(
            "ffmpeg/ffprobe nao encontrado no PATH. Deve vir instalado no container; "
            "se nao vier, instale com apt-get install ffmpeg."
        )


def _run(args: list) -> None:
    """Roda um comando (ffmpeg/ffprobe), sempre lista de args, nunca shell=True."""
    proc = subprocess.run(args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Comando falhou (exit {proc.returncode}): {' '.join(args)}\n{proc.stderr.strip()}"
        )


def _ensure_parent(path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)


def _parse_time(value: str) -> float:
    """Converte 'HH:MM:SS(.ms)' ou segundos puros ('12', '12.5') pra float segundos."""
    value = str(value).strip()
    if ":" not in value:
        return float(value)
    parts = [float(p) for p in value.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    h, m, s = parts[-3:]
    return h * 3600 + m * 60 + s


def probe(input_path: str) -> dict:
    """Metadados do arquivo: duracao, resolucao, codec, fps, tamanho, tem audio."""
    _check_ffmpeg()
    proc = subprocess.run(
        [
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", input_path,
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"ffprobe falhou em {input_path!r}: {proc.stderr.strip()}")
    data = json.loads(proc.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)
    out = {
        "path": input_path,
        "duration_seconds": float(fmt.get("duration", 0) or 0),
        "size_bytes": int(fmt.get("size", 0) or 0),
        "format": fmt.get("format_name"),
        "has_audio": audio_stream is not None,
    }
    if video_stream:
        out["width"] = video_stream.get("width")
        out["height"] = video_stream.get("height")
        out["video_codec"] = video_stream.get("codec_name")
        rate = video_stream.get("r_frame_rate", "0/1")
        try:
            n, d = rate.split("/")
            out["fps"] = round(float(n) / float(d), 2) if float(d) else None
        except (ValueError, ZeroDivisionError):
            out["fps"] = None
    if audio_stream:
        out["audio_codec"] = audio_stream.get("codec_name")
    return out


def trim(input_path: str, output_path: str, start: str, end: str = None,
          duration: str = None, fast: bool = False) -> dict:
    """Corta um trecho. start/end/duration aceitam HH:MM:SS ou segundos.
    start/end sao timestamps ABSOLUTOS no video original (ex.: start=10,
    end=25 corta os segundos 10 a 25, um clipe de 15s).

    fast=True usa stream copy (rapido, mas o corte alinha no keyframe mais
    proximo, pode nao ser exato ao frame). Padrao reencoda pra corte exato.
    """
    if not end and not duration:
        raise ValueError("Informe --end ou --duration.")
    _check_ffmpeg()
    _ensure_parent(output_path)
    if end:
        # Calcula a duracao em vez de usar -to: com -ss antes de -i, algumas
        # versoes do ffmpeg tratam -to como relativo ao ponto de seek (nao ao
        # timeline original), o que corta o trecho errado. Duracao explicita
        # (-t) e sempre inequivoca.
        clip_duration = _parse_time(end) - _parse_time(start)
        if clip_duration <= 0:
            raise ValueError(f"--end ({end}) precisa ser depois de --start ({start}).")
        duration = str(clip_duration)
    args = ["ffmpeg", "-y", "-ss", start, "-i", input_path, "-t", duration]
    if fast:
        args += ["-c", "copy"]
    else:
        args += ["-c:v", "libx264", "-c:a", "aac", "-preset", "fast"]
    args.append(output_path)
    _run(args)
    return {"output": output_path, "mode": "fast (stream copy)" if fast else "accurate (re-encode)"}


def concat(output_path: str, input_paths: list) -> dict:
    """Junta varios clipes em um so, na ordem dada. Reencoda pra tolerar
    clipes com codec/resolucao diferentes entre si."""
    if len(input_paths) < 2:
        raise ValueError("Precisa de pelo menos 2 arquivos pra concatenar.")
    _check_ffmpeg()
    _ensure_parent(output_path)
    args = ["ffmpeg", "-y"]
    for p in input_paths:
        args += ["-i", p]
    n = len(input_paths)
    filter_parts = "".join(f"[{i}:v:0][{i}:a:0]" for i in range(n))
    filter_complex = f"{filter_parts}concat=n={n}:v=1:a=1[outv][outa]"
    args += [
        "-filter_complex", filter_complex,
        "-map", "[outv]", "-map", "[outa]",
        "-c:v", "libx264", "-c:a", "aac", "-preset", "fast",
        output_path,
    ]
    _run(args)
    return {"output": output_path, "clips_joined": n}


def resize(input_path: str, output_path: str, preset: str = None,
           width: int = None, height: int = None) -> dict:
    """Redimensiona pro formato pedido, sem distorcer (cover + crop centralizado)."""
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"Preset {preset!r} desconhecido. Use: {', '.join(PRESETS)}")
        width, height = PRESETS[preset]
    if not width or not height:
        raise ValueError("Informe --preset ou --width/--height juntos.")
    _check_ffmpeg()
    _ensure_parent(output_path)
    vf = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", vf, "-c:v", "libx264", "-c:a", "aac", "-preset", "fast",
        output_path,
    ])
    return {"output": output_path, "width": width, "height": height}


def convert(input_path: str, output_path: str) -> dict:
    """Converte formato/container (mp4, mov, webm, gif...). Formato sai da
    extensao do output_path. GIF ganha paleta otimizada (2 passos) pra nao
    sair borrado."""
    _check_ffmpeg()
    _ensure_parent(output_path)
    if output_path.lower().endswith(".gif"):
        palette = str(Path(output_path).with_suffix(".palette.png"))
        _run([
            "ffmpeg", "-y", "-i", input_path,
            "-vf", "fps=15,scale=480:-1:flags=lanczos,palettegen",
            palette,
        ])
        _run([
            "ffmpeg", "-y", "-i", input_path, "-i", palette,
            "-filter_complex", "fps=15,scale=480:-1:flags=lanczos[x];[x][1:v]paletteuse",
            output_path,
        ])
        Path(palette).unlink(missing_ok=True)
    else:
        _run(["ffmpeg", "-y", "-i", input_path, output_path])
    return {"output": output_path}


def extract_audio(input_path: str, output_path: str) -> dict:
    """Extrai so o audio (mp3, wav, m4a... pela extensao do output)."""
    _check_ffmpeg()
    _ensure_parent(output_path)
    args = ["ffmpeg", "-y", "-i", input_path, "-vn"]
    if output_path.lower().endswith(".mp3"):
        args += ["-q:a", "2"]
    args.append(output_path)
    _run(args)
    return {"output": output_path}


def add_audio(video_path: str, audio_path: str, output_path: str,
               mode: str = "replace", volume: float = 1.0) -> dict:
    """mode='replace' troca o audio original pelo novo; mode='mix' mistura os
    dois (volume controla o volume do audio NOVO, 0.0-1.0+, o original fica
    em 1.0)."""
    if mode not in ("replace", "mix"):
        raise ValueError("mode deve ser 'replace' ou 'mix'.")
    _check_ffmpeg()
    _ensure_parent(output_path)
    if mode == "replace":
        _run([
            "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            output_path,
        ])
    else:
        filter_complex = (
            f"[1:a]volume={volume}[a1];[0:a][a1]amix=inputs=2:duration=first[aout]"
        )
        _run([
            "ffmpeg", "-y", "-i", video_path, "-i", audio_path,
            "-filter_complex", filter_complex,
            "-map", "0:v:0", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-shortest",
            output_path,
        ])
    return {"output": output_path, "mode": mode}


def burn_subtitles(input_path: str, srt_path: str, output_path: str) -> dict:
    """Grava a legenda direto na imagem do video (hardsub), a partir de um
    arquivo .srt. Nao da pra desligar depois, e legenda permanente."""
    _check_ffmpeg()
    _ensure_parent(output_path)
    srt_escaped = srt_path.replace("\\", "\\\\").replace(":", "\\:")
    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-vf", f"subtitles={srt_escaped}",
        "-c:a", "copy",
        output_path,
    ])
    return {"output": output_path}


def compress(input_path: str, output_path: str, target_mb: float = None,
             crf: int = 28) -> dict:
    """Reduz tamanho do arquivo. target_mb calcula o bitrate necessario pra
    caber nesse tamanho (prioriza bater o alvo); sem target_mb usa CRF (28 =
    bom equilibrio qualidade/tamanho, quanto maior o numero menor o arquivo)."""
    _check_ffmpeg()
    _ensure_parent(output_path)
    if target_mb:
        meta = probe(input_path)
        duration = meta["duration_seconds"] or 1
        target_bits = target_mb * 8 * 1024 * 1024
        audio_bitrate_bps = 128_000
        video_bitrate_bps = max(int(target_bits / duration) - audio_bitrate_bps, 100_000)
        _run([
            "ffmpeg", "-y", "-i", input_path,
            "-b:v", str(video_bitrate_bps), "-b:a", "128k",
            "-c:v", "libx264", "-preset", "fast",
            output_path,
        ])
        return {"output": output_path, "target_mb": target_mb,
                "video_bitrate_bps": video_bitrate_bps}
    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k",
        output_path,
    ])
    return {"output": output_path, "crf": crf}


def thumbnail(input_path: str, output_path: str, at: str = "00:00:01") -> dict:
    """Tira uma imagem parada de um instante do video (HH:MM:SS ou segundos)."""
    _check_ffmpeg()
    _ensure_parent(output_path)
    _run([
        "ffmpeg", "-y", "-ss", at, "-i", input_path,
        "-vframes", "1", "-q:v", "2",
        output_path,
    ])
    return {"output": output_path, "at": at}


def speed(input_path: str, output_path: str, factor: float) -> dict:
    """Muda a velocidade (2.0 = 2x mais rapido, 0.5 = metade da velocidade).
    Audio e video ficam sincronizados."""
    if factor <= 0:
        raise ValueError("factor precisa ser maior que 0.")
    _check_ffmpeg()
    _ensure_parent(output_path)
    video_filter = f"setpts={1/factor}*PTS"
    # atempo so aceita 0.5-2.0 por instancia; encadeia filtros pra fatores fora disso.
    atempo_filters = []
    remaining = factor
    while remaining > 2.0:
        atempo_filters.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        atempo_filters.append("atempo=0.5")
        remaining /= 0.5
    atempo_filters.append(f"atempo={remaining}")
    audio_filter = ",".join(atempo_filters)
    _run([
        "ffmpeg", "-y", "-i", input_path,
        "-filter:v", video_filter, "-filter:a", audio_filter,
        output_path,
    ])
    return {"output": output_path, "factor": factor}


def watermark(input_path: str, watermark_path: str, output_path: str,
              position: str = "bottom-right") -> dict:
    """Sobrepoe uma imagem (logo/marca d'agua) no video."""
    if position not in _POSITIONS:
        raise ValueError(f"position deve ser: {', '.join(_POSITIONS)}")
    _check_ffmpeg()
    _ensure_parent(output_path)
    _run([
        "ffmpeg", "-y", "-i", input_path, "-i", watermark_path,
        "-filter_complex", f"overlay={_POSITIONS[position]}",
        "-c:a", "copy",
        output_path,
    ])
    return {"output": output_path, "position": position}


def _cli():
    p = argparse.ArgumentParser(description="Edicao de video via ffmpeg (Hermes)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("info", help="Metadados do arquivo")
    s.add_argument("input")

    s = sub.add_parser("trim", help="Cortar um trecho")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--start", required=True, help="HH:MM:SS ou segundos")
    s.add_argument("--end", help="HH:MM:SS ou segundos")
    s.add_argument("--duration", help="duracao do corte, alternativa a --end")
    s.add_argument("--fast", action="store_true", help="stream copy, mais rapido, corte no keyframe mais proximo")

    s = sub.add_parser("concat", help="Juntar clipes em ordem")
    s.add_argument("output")
    s.add_argument("inputs", nargs="+")

    s = sub.add_parser("resize", help="Redimensionar (formato de rede social ou custom)")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--preset", choices=list(PRESETS))
    s.add_argument("--width", type=int)
    s.add_argument("--height", type=int)

    s = sub.add_parser("convert", help="Converter formato/container")
    s.add_argument("input")
    s.add_argument("output")

    s = sub.add_parser("extract-audio", help="Extrair so o audio")
    s.add_argument("input")
    s.add_argument("output")

    s = sub.add_parser("add-audio", help="Trocar ou misturar audio")
    s.add_argument("video")
    s.add_argument("audio")
    s.add_argument("output")
    s.add_argument("--mode", choices=["replace", "mix"], default="replace")
    s.add_argument("--volume", type=float, default=1.0, help="so pra mode=mix, volume do audio novo")

    s = sub.add_parser("subtitles", help="Gravar legenda .srt no video (hardsub)")
    s.add_argument("input")
    s.add_argument("srt")
    s.add_argument("output")

    s = sub.add_parser("compress", help="Reduzir tamanho do arquivo")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--target-mb", type=float)
    s.add_argument("--crf", type=int, default=28)

    s = sub.add_parser("thumbnail", help="Tirar uma imagem parada")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--at", default="00:00:01")

    s = sub.add_parser("speed", help="Mudar velocidade")
    s.add_argument("input")
    s.add_argument("output")
    s.add_argument("--factor", type=float, required=True)

    s = sub.add_parser("watermark", help="Sobrepor logo/marca d'agua")
    s.add_argument("input")
    s.add_argument("watermark_image")
    s.add_argument("output")
    s.add_argument("--position", choices=list(_POSITIONS), default="bottom-right")

    args = p.parse_args()

    try:
        if args.command == "info":
            out = probe(args.input)
        elif args.command == "trim":
            out = trim(args.input, args.output, args.start, args.end, args.duration, args.fast)
        elif args.command == "concat":
            out = concat(args.output, args.inputs)
        elif args.command == "resize":
            out = resize(args.input, args.output, args.preset, args.width, args.height)
        elif args.command == "convert":
            out = convert(args.input, args.output)
        elif args.command == "extract-audio":
            out = extract_audio(args.input, args.output)
        elif args.command == "add-audio":
            out = add_audio(args.video, args.audio, args.output, args.mode, args.volume)
        elif args.command == "subtitles":
            out = burn_subtitles(args.input, args.srt, args.output)
        elif args.command == "compress":
            out = compress(args.input, args.output, args.target_mb, args.crf)
        elif args.command == "thumbnail":
            out = thumbnail(args.input, args.output, args.at)
        elif args.command == "speed":
            out = speed(args.input, args.output, args.factor)
        elif args.command == "watermark":
            out = watermark(args.input, args.watermark_image, args.output, args.position)
        else:
            p.error("comando desconhecido")
            return
    except (RuntimeError, ValueError) as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False, indent=2))
        sys.exit(1)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    _cli()
