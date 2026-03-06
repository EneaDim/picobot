from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str
    backend: str
    ok: bool
    detail: str = ""


def _tools_cfg(cfg):
    return getattr(cfg, "tools", None)


def _resolve_whisper_cli(cfg) -> str:
    tools = _tools_cfg(cfg)
    if tools is None:
        return ""
    for candidate in [
        getattr(tools, "whisper_cpp_cli", ""),
        getattr(getattr(tools, "bins", None), "whisper_cpp_cli", ""),
        getattr(tools, "whisper_cpp_main_path", ""),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


def _resolve_whisper_model(cfg) -> str:
    tools = _tools_cfg(cfg)
    if tools is None:
        return ""
    for candidate in [
        getattr(tools, "whisper_model", ""),
        getattr(getattr(tools, "models", None), "whisper_cpp", ""),
    ]:
        value = str(candidate or "").strip()
        if value:
            return value
    return ""


async def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd) if cwd else None,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out_b, err_b = await proc.communicate()
    return int(proc.returncode or 0), out_b.decode("utf-8", errors="replace"), err_b.decode("utf-8", errors="replace")


async def transcribe_audio_file(
    cfg,
    *,
    audio_path: str | Path,
    lang: str = "auto",
) -> STTResult:
    """
    Funzione riusabile fuori dal tool registry.
    """
    backend = "whisper.cpp"
    cli = _resolve_whisper_cli(cfg)
    model = _resolve_whisper_model(cfg)
    audio = Path(audio_path).expanduser().resolve()

    if not audio.exists() or not audio.is_file():
        return STTResult(
            text="",
            language=lang,
            backend=backend,
            ok=False,
            detail=f"audio file not found: {audio}",
        )

    if not cli or not Path(cli).expanduser().exists():
        return STTResult(
            text="",
            language=lang,
            backend=backend,
            ok=False,
            detail="whisper.cpp CLI not available",
        )

    if not model or not Path(model).expanduser().exists():
        return STTResult(
            text="",
            language=lang,
            backend=backend,
            ok=False,
            detail="whisper model not available",
        )

    cmd = [
        str(Path(cli).expanduser()),
        "-m",
        str(Path(model).expanduser()),
        "-f",
        str(audio),
        "-otxt",
        "-of",
        str(audio.with_suffix("")),
    ]

    if lang and str(lang).lower() != "auto":
        cmd.extend(["-l", str(lang)])

    exit_code, stdout, stderr = await _run(cmd, cwd=audio.parent)
    if exit_code != 0:
        return STTResult(
            text="",
            language=lang,
            backend=backend,
            ok=False,
            detail=stderr.strip() or stdout.strip() or "whisper.cpp failed",
        )

    txt_out = audio.with_suffix(".txt")
    if not txt_out.exists():
        return STTResult(
            text="",
            language=lang,
            backend=backend,
            ok=False,
            detail="transcript file not produced",
        )

    text = txt_out.read_text(encoding="utf-8", errors="replace").strip()

    meta = {
        "backend": backend,
        "audio_path": str(audio),
        "language": lang,
        "text_path": str(txt_out),
    }
    audio.with_suffix(".stt.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return STTResult(
        text=text,
        language=lang,
        backend=backend,
        ok=True,
        detail="",
    )


class STTArgs(BaseModel):
    audio_path: str = Field(..., min_length=1)
    lang: str = Field(default="auto")


def make_stt_tool(cfg) -> ToolSpec:
    async def _handler(args: STTArgs) -> dict:
        result = await transcribe_audio_file(
            cfg,
            audio_path=args.audio_path,
            lang=args.lang,
        )
        if not result.ok:
            return tool_error(result.detail or "stt failed")

        return tool_ok(
            {
                "text": result.text,
                "language": result.language,
                "backend": result.backend,
                "detail": result.detail,
            },
            language=result.language,
        )

    return ToolSpec(
        name="stt",
        description="Local speech-to-text transcription using configured local backend.",
        schema=STTArgs,
        handler=_handler,
    )
