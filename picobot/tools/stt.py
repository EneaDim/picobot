from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.paths import get_runtime_tool_bin, get_tool_model
from picobot.tools.terminal_tool import TerminalToolBase


@dataclass(frozen=True)
class STTResult:
    text: str
    language: str
    backend: str
    ok: bool
    detail: str = ""
    transcript_path: str = ""
    meta_path: str = ""


class STTArgs(BaseModel):
    audio_path: str = Field(..., min_length=1)
    lang: str = Field(default="auto")


def _local_executable_exists(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if "/" in raw or "\\" in raw or raw.startswith("."):
        return Path(raw).expanduser().exists()
    return shutil.which(raw) is not None


def _stage_audio_into_workspace(runner: TerminalToolBase, audio_path: str | Path) -> Path:
    src = Path(audio_path).expanduser().resolve()
    if not src.exists() or not src.is_file():
        raise RuntimeError(f"audio file not found: {src}")

    try:
        runner.resolve_workspace_path(src)
        return src
    except Exception:
        target_dir = runner.workspace_root / "inputs" / "stt" / uuid4().hex[:12]
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / src.name
        shutil.copy2(src, target)
        return target.resolve()


def _runtime_path(runner: TerminalToolBase, host_path: Path, *, purpose: str) -> str:
    if runner.backend == "docker":
        host_str = str(host_path)
        if host_str.startswith("/opt/picobot/"):
            return host_str
        try:
            return runner.map_host_path(host_path)
        except Exception as exc:
            raise RuntimeError(f"{purpose} must be inside workspace root for docker backend: {host_path}") from exc
    return str(host_path)


def _runtime_bin(runner: TerminalToolBase, value: str) -> str:
    raw = str(value or "").strip()
    if runner.backend == "docker":
        return Path(raw).name or raw
    return str(Path(raw).expanduser().resolve()) if ("/" in raw or "\\" in raw or raw.startswith(".")) else raw


def _normalize_lang(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return "auto"
    if raw.startswith("it"):
        return "it"
    if raw.startswith("en"):
        return "en"
    return raw


def _infer_lang_from_sidecar(audio_path: Path) -> str | None:
    candidates = [
        audio_path.with_suffix(".tts.meta.json"),
        audio_path.with_suffix(".stt.meta.json"),
        audio_path.with_suffix(".meta.json"),
    ]

    for candidate in candidates:
        try:
            if not candidate.exists():
                continue
            payload = json.loads(candidate.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                continue

            lang = (
                payload.get("language")
                or payload.get("lang")
                or payload.get("detected_language")
            )
            lang = _normalize_lang(lang)
            if lang != "auto":
                return lang
        except Exception:
            continue

    return None


async def transcribe_audio_file(
    cfg,
    *,
    audio_path: str | Path,
    lang: str = "auto",
) -> STTResult:
    backend_name = "whisper.cpp"

    cli = get_runtime_tool_bin(cfg, "whisper_cpp_cli", "whisper")

    model = str(getattr(getattr(getattr(cfg, "tools", None), "whisper", None), "model", "") or "").strip()
    if not model:
        model = str(get_tool_model(cfg, "whisper_cpp", "/opt/picobot/models/whisper/ggml-small.bin") or "").strip()

    runner = TerminalToolBase(
        cfg=cfg,
        allowed_bins=[cli or "whisper"],
        timeout_s=300,
        max_output_bytes=200_000,
    )

    if runner.backend == "local" and not _local_executable_exists(cli):
        return STTResult(
            text="",
            language=_normalize_lang(lang),
            backend=backend_name,
            ok=False,
            detail="whisper.cpp CLI not available",
        )

    model_path = Path(model).expanduser().resolve()

    if runner.backend != "docker":
        if not model_path.exists() or not model_path.is_file():
            return STTResult(
                text="",
                language=_normalize_lang(lang),
                backend=backend_name,
                ok=False,
                detail="whisper model not available",
            )

    try:
        staged_audio = _stage_audio_into_workspace(runner, audio_path)
        runtime_audio = _runtime_path(runner, staged_audio, purpose="audio input")
        runtime_model = _runtime_path(runner, model_path, purpose="whisper model")
    except Exception as exc:
        return STTResult(
            text="",
            language=_normalize_lang(lang),
            backend=backend_name,
            ok=False,
            detail=str(exc),
        )

    effective_lang = _normalize_lang(lang)
    if effective_lang == "auto":
        inferred_lang = _infer_lang_from_sidecar(staged_audio)
        if inferred_lang:
            effective_lang = inferred_lang

    transcript_txt = staged_audio.with_suffix(".txt")
    transcript_meta = staged_audio.with_suffix(".stt.meta.json")
    transcript_base = str(Path(runtime_audio).with_suffix(""))

    if transcript_txt.exists():
        transcript_txt.unlink()
    if transcript_meta.exists():
        transcript_meta.unlink()

    cmd = [
        _runtime_bin(runner, cli or "whisper"),
        "-m",
        runtime_model,
        "-f",
        runtime_audio,
        "-otxt",
        "-of",
        transcript_base,
    ]
    if effective_lang != "auto":
        cmd.extend(["-l", effective_lang])

    res = runner.run_cmd(cmd, prefix="[stt]", timeout_s=300)
    if res.returncode != 0:
        return STTResult(
            text="",
            language=effective_lang,
            backend=backend_name,
            ok=False,
            detail=(res.stderr or res.stdout or "whisper.cpp failed").strip(),
        )

    if not transcript_txt.exists():
        return STTResult(
            text="",
            language=effective_lang,
            backend=backend_name,
            ok=False,
            detail="transcript file not produced",
        )

    text = transcript_txt.read_text(encoding="utf-8", errors="replace").strip()
    transcript_meta.write_text(
        json.dumps(
            {
                "backend": runner.backend,
                "engine": backend_name,
                "audio_path": str(staged_audio),
                "language": effective_lang,
                "text_path": str(transcript_txt),
                "model_path": model,
                "runtime_cli": cli,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return STTResult(
        text=text,
        language=effective_lang,
        backend=runner.backend,
        ok=True,
        detail="",
        transcript_path=str(transcript_txt),
        meta_path=str(transcript_meta),
    )


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
                "transcript_path": result.transcript_path,
                "meta_path": result.meta_path,
            },
            language=result.language,
        )

    return ToolSpec(
        name="stt",
        description="Local speech-to-text transcription using the configured sandbox backend.",
        schema=STTArgs,
        handler=_handler,
    )
