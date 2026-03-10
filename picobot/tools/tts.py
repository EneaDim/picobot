from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.paths import get_runtime_tool_bin, sibling_lib_dirs
from picobot.tools.terminal_tool import TerminalToolBase


class TTSArgs(BaseModel):
    text: str = Field(..., min_length=1)
    lang: str = Field(default="it")
    voice_id: str | None = Field(default=None)
    output_path: str | None = Field(default=None)


def _default_voice_for_lang(cfg, lang: str) -> str:
    piper_cfg = getattr(getattr(cfg, "tools", None), "piper", None)
    mapping = getattr(piper_cfg, "default_voice_by_lang", {}) or {}
    key = "it" if (lang or "").lower().startswith("it") else "en"
    voice = str(mapping.get(key) or "").strip()
    if voice:
        return voice
    return "it_IT-paola-medium" if key == "it" else "en_US-lessac-medium"


def _pick_model(cfg, lang: str, voice_id: str | None = None) -> str:
    explicit_voice = str(voice_id or "").strip()
    if explicit_voice:
        return f"/opt/picobot/models/piper/{explicit_voice}.onnx"

    fallback_voice = _default_voice_for_lang(cfg, lang)
    return f"/opt/picobot/models/piper/{fallback_voice}.onnx"


def _default_output_dir(runner: TerminalToolBase) -> Path:
    out_dir = (runner.workspace_root / "outputs" / "tts").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _build_output_path(
    runner: TerminalToolBase,
    *,
    lang: str,
    output_path: str | None = None,
    output_dir: str | None = None,
    file_stem: str | None = None,
    audio_format: str | None = None,
) -> Path:
    if str(output_path or "").strip():
        target = runner.resolve_workspace_path(str(output_path))
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    ext = "wav"
    requested_ext = str(audio_format or "").strip().lower()
    if requested_ext == "wav":
        ext = "wav"

    if str(output_dir or "").strip():
        out_dir = runner.resolve_workspace_path(str(output_dir))
        out_dir.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = _default_output_dir(runner)

    stem = str(file_stem or "").strip()
    if not stem:
        suffix = "it" if (lang or "").lower().startswith("it") else "en"
        stem = f"tts_output_{suffix}_{uuid4().hex[:8]}"

    return (out_dir / f"{stem}.{ext}").resolve()


def _build_piper_env(piper_bin: str) -> dict[str, str]:
    env: dict[str, str] = {}

    lib_dirs = sibling_lib_dirs(piper_bin)
    if lib_dirs:
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs)

    piper_path = Path(piper_bin).expanduser().resolve()
    espeak_data = piper_path.parent.parent / "espeak-ng-data"
    if espeak_data.exists() and espeak_data.is_dir():
        env["ESPEAK_DATA_PATH"] = str(espeak_data.resolve())

    return env


def _local_executable_exists(value: str) -> bool:
    raw = str(value or "").strip()
    if not raw:
        return False
    if "/" in raw or "\\" in raw or raw.startswith("."):
        return Path(raw).expanduser().exists()
    return shutil.which(raw) is not None


def _runtime_path(runner: TerminalToolBase, host_path: Path, *, purpose: str) -> str:
    if runner.backend == "docker":
        # Nel backend docker il modello vive nel runtime container e non va mappato dal workspace host.
        host_str = str(host_path)
        if host_str.startswith("/opt/picobot/"):
            return host_str
        try:
            return runner.map_host_path(host_path)
        except Exception as exc:
            raise RuntimeError(
                f"{purpose} must be inside workspace root for docker backend: {host_path}"
            ) from exc
    return str(host_path)


def _runtime_bin(runner: TerminalToolBase, value: str) -> str:
    raw = str(value or "").strip()
    if runner.backend == "docker":
        return Path(raw).name or raw
    return str(Path(raw).expanduser().resolve()) if ("/" in raw or "\\" in raw or raw.startswith(".")) else raw


def synthesize_speech(
    cfg,
    text: str,
    *,
    lang: str = "it",
    voice_id: str | None = None,
    output_path: str | None = None,
    output_dir: str | None = None,
    file_stem: str | None = None,
    audio_format: str | None = None,
    **_: object,
) -> str:
    if not str(text or "").strip():
        raise ValueError("text is empty")

    piper_bin = get_runtime_tool_bin(cfg, "piper", "piper")
    model_path = _pick_model(cfg, lang, voice_id=voice_id)

    runner = TerminalToolBase(
        cfg=cfg,
        allowed_bins=[piper_bin or "piper"],
        timeout_s=180,
        max_output_bytes=120_000,
    )

    if runner.backend == "local" and not _local_executable_exists(piper_bin):
        raise RuntimeError("piper binary not configured")

    model_path_obj = Path(model_path).expanduser().resolve()
    if runner.backend != "docker" and not model_path_obj.exists():
        raise RuntimeError(f"piper model not found: {model_path_obj}")

    final_output = _build_output_path(
        runner,
        lang=lang,
        output_path=output_path,
        output_dir=output_dir,
        file_stem=file_stem,
        audio_format=audio_format,
    )
    final_output.parent.mkdir(parents=True, exist_ok=True)

    runtime_model = _runtime_path(runner, model_path_obj, purpose="piper model")
    runtime_output = _runtime_path(runner, final_output, purpose="tts output")

    env: dict[str, str] = {}
    raw_bin = str(piper_bin or "").strip()
    if runner.backend == "local" and raw_bin and ("/" in raw_bin or "\\" in raw_bin or raw_bin.startswith(".")):
        env.update(_build_piper_env(raw_bin))

    merged_env = dict(os.environ)
    merged_env.update(env)

    res = runner.run_cmd(
        [
            _runtime_bin(runner, piper_bin or "piper"),
            "--model",
            runtime_model,
            "--output_file",
            runtime_output,
        ],
        prefix="[tts]",
        timeout_s=120,
        input_bytes=(str(text).rstrip() + "\n").encode("utf-8"),
        env=merged_env,
    )

    if res.returncode != 0:
        err = (res.stderr or res.stdout or "tts failed").strip()

        if "libpiper_phonemize.so" in err or "error while loading shared libraries" in err:
            raise RuntimeError(
                "Piper runtime incompleto: mancano librerie condivise richieste o non sono nel LD_LIBRARY_PATH del bundle tool."
            )

        if "espeak-ng-data" in err or "phontab" in err:
            raise RuntimeError(
                "Piper runtime incompleto o configurato male: espeak-ng-data non trovato dal runtime."
            )

        raise RuntimeError(err)

    if not final_output.exists():
        raise RuntimeError(f"tts output not created: {final_output}")

    meta_path = final_output.with_suffix(".tts.meta.json")
    meta_path.write_text(
        json.dumps(
            {
                "backend": runner.backend,
                "engine": "piper",
                "audio_path": str(final_output),
                "language": lang,
                "voice_id": voice_id or _default_voice_for_lang(cfg, lang),
                "model_path": model_path,
                "text_len": len(str(text)),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return str(final_output)


def make_tts_tool(cfg=None) -> ToolSpec:
    async def _handler(args: TTSArgs) -> dict:
        try:
            audio_path = synthesize_speech(
                cfg,
                args.text,
                lang=args.lang,
                voice_id=args.voice_id,
                output_path=args.output_path,
            )

            backend = "unknown"
            meta_path = str(Path(audio_path).with_suffix(".tts.meta.json"))
            try:
                payload = json.loads(Path(meta_path).read_text(encoding="utf-8"))
                backend = str(payload.get("backend") or "unknown")
            except Exception:
                pass

            return tool_ok(
                {
                    "audio_path": audio_path,
                    "backend": backend,
                    "meta_path": meta_path,
                },
                language=args.lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="tts",
        description="Generate speech audio using Piper via the configured sandbox backend.",
        schema=TTSArgs,
        handler=_handler,
    )
