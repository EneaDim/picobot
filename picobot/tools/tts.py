from __future__ import annotations

import asyncio
import json
import re
import wave
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_ok


@dataclass(frozen=True)
class TTSResult:
    audio_path: str
    format: str
    voice_id: str
    backend: str
    ok: bool
    detail: str = ""


def _slug(text: str, fallback: str = "tts") -> str:
    value = re.sub(r"[^a-zA-Z0-9._-]+", "-", (text or "").strip().lower()).strip("-.")
    return value or fallback


def _tools_cfg(cfg):
    return getattr(cfg, "tools", None)


def _podcast_cfg(cfg):
    return getattr(cfg, "podcast", None)


def _resolve_piper_bin(cfg) -> str:
    tools = _tools_cfg(cfg)
    if tools is None:
        return ""
    for candidate in [
        getattr(tools, "piper_bin", ""),
        getattr(getattr(tools, "bins", None), "piper", ""),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _resolve_ffmpeg_bin(cfg) -> str:
    tools = _tools_cfg(cfg)
    if tools is None:
        return "ffmpeg"
    for candidate in [
        getattr(tools, "ffmpeg_bin", ""),
        getattr(getattr(tools, "bins", None), "ffmpeg", ""),
        "ffmpeg",
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return "ffmpeg"


def _voice_id_for_lang(cfg, lang: str) -> str:
    pcfg = _podcast_cfg(cfg)
    if pcfg is None:
        return ""
    try:
        voices = getattr(pcfg, "voices", None)
        if voices is None:
            return ""
        lang_block = getattr(voices, "en" if str(lang).lower().startswith("en") else "it", None)
        if lang_block is None:
            return ""
        narrator = getattr(lang_block, "narrator", None)
        if narrator is None:
            return ""
        return str(getattr(narrator, "voice_id", "") or "").strip()
    except Exception:
        return ""


def _model_for_lang(cfg, lang: str) -> str:
    tools = _tools_cfg(cfg)
    if tools is None:
        return ""
    if str(lang).lower().startswith("en"):
        for candidate in [
            getattr(tools, "piper_model_en", ""),
            getattr(getattr(tools, "models", None), "piper_en", ""),
        ]:
            value = str(candidate or "").strip()
            if value:
                return value
        return ""
    for candidate in [
        getattr(tools, "piper_model_it", ""),
        getattr(getattr(tools, "models", None), "piper_it", ""),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _write_placeholder_wav(path: Path, seconds: float = 0.4, sample_rate: int = 22050) -> None:
    nframes = max(1, int(seconds * sample_rate))
    silence = b"\x00\x00" * nframes
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(silence)


async def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return int(proc.returncode or 0), out_b.decode("utf-8", errors="replace"), err_b.decode("utf-8", errors="replace")


async def synthesize_speech(
    cfg,
    *,
    text: str,
    lang: str = "it",
    voice_id: str | None = None,
    output_dir: str | Path | None = None,
    output_stem: str = "speech",
) -> TTSResult:
    """
    Funzione riusabile anche fuori dal tool registry.
    """
    target_dir = Path(output_dir or getattr(getattr(cfg, "podcast", None), "output_dir", "outputs/podcasts")).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)

    stem = _slug(output_stem, fallback="speech")
    wav_path = target_dir / f"{stem}.wav"
    mp3_path = target_dir / f"{stem}.mp3"
    input_txt = target_dir / f"{stem}.txt"
    meta_path = target_dir / f"{stem}.meta.json"

    backend = str(getattr(getattr(cfg, "podcast", None), "tts_backend", "piper") or "piper").lower()
    chosen_voice = (voice_id or _voice_id_for_lang(cfg, lang)).strip()
    model_path = _model_for_lang(cfg, lang)
    piper_bin = _resolve_piper_bin(cfg)
    ffmpeg_bin = _resolve_ffmpeg_bin(cfg)

    input_txt.write_text((text or "").strip(), encoding="utf-8")

    meta = {
        "backend": backend,
        "voice_id": chosen_voice,
        "lang": lang,
        "model_path": model_path,
        "piper_bin": piper_bin,
    }

    if backend != "piper":
        _write_placeholder_wav(wav_path)
        meta["detail"] = f"unsupported backend: {backend}"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return TTSResult(
            audio_path=str(wav_path),
            format="wav",
            voice_id=chosen_voice,
            backend=backend,
            ok=False,
            detail=meta["detail"],
        )

    if not piper_bin or not Path(piper_bin).expanduser().exists():
        _write_placeholder_wav(wav_path)
        meta["detail"] = "piper binary not available"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return TTSResult(
            audio_path=str(wav_path),
            format="wav",
            voice_id=chosen_voice,
            backend=backend,
            ok=False,
            detail=meta["detail"],
        )

    if not model_path or not Path(model_path).expanduser().exists():
        _write_placeholder_wav(wav_path)
        meta["detail"] = "piper model not available"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return TTSResult(
            audio_path=str(wav_path),
            format="wav",
            voice_id=chosen_voice,
            backend=backend,
            ok=False,
            detail=meta["detail"],
        )

    cmd = [
        str(Path(piper_bin).expanduser()),
        "--model",
        str(Path(model_path).expanduser()),
        "--output_file",
        str(wav_path),
    ]

    exit_code, _so, err = await _run(cmd, cwd=target_dir)

    if exit_code != 0:
        _write_placeholder_wav(wav_path)
        meta["detail"] = f"piper failed: {err.strip()}"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return TTSResult(
            audio_path=str(wav_path),
            format="wav",
            voice_id=chosen_voice,
            backend=backend,
            ok=False,
            detail=meta["detail"],
        )

    audio_format = str(getattr(getattr(cfg, "podcast", None), "audio_format", "mp3") or "mp3").lower()

    if audio_format == "mp3":
        ffmpeg_path = Path(ffmpeg_bin).expanduser()
        ffmpeg_cmd = [
            str(ffmpeg_path) if ffmpeg_path.exists() else "ffmpeg",
            "-y",
            "-i",
            str(wav_path),
            str(mp3_path),
        ]
        ff_exit, _ffso, fferr = await _run(ffmpeg_cmd, cwd=target_dir)
        if ff_exit == 0 and mp3_path.exists():
            meta["detail"] = ""
            meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
            return TTSResult(
                audio_path=str(mp3_path),
                format="mp3",
                voice_id=chosen_voice,
                backend=backend,
                ok=True,
                detail="",
            )
        meta["detail"] = f"ffmpeg conversion failed: {fferr.strip()}"
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return TTSResult(
            audio_path=str(wav_path),
            format="wav",
            voice_id=chosen_voice,
            backend=backend,
            ok=True,
            detail=meta["detail"],
        )

    meta["detail"] = ""
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return TTSResult(
        audio_path=str(wav_path),
        format="wav",
        voice_id=chosen_voice,
        backend=backend,
        ok=True,
        detail="",
    )


class TTSArgs(BaseModel):
    text: str = Field(..., min_length=1)
    lang: str = Field(default="it")
    voice_id: str | None = None
    output_dir: str | None = None
    output_stem: str = Field(default="speech")


def make_tts_tool(cfg) -> ToolSpec:
    async def _handler(args: TTSArgs) -> dict:
        result = await synthesize_speech(
            cfg,
            text=args.text,
            lang=args.lang,
            voice_id=args.voice_id,
            output_dir=args.output_dir,
            output_stem=args.output_stem,
        )
        return tool_ok(
            {
                "audio_path": result.audio_path,
                "format": result.format,
                "voice_id": result.voice_id,
                "backend": result.backend,
                "ok": result.ok,
                "detail": result.detail,
            },
            language=args.lang,
        )

    return ToolSpec(
        name="tts",
        description="Local text-to-speech synthesis using configured local backend.",
        schema=TTSArgs,
        handler=_handler,
    )
