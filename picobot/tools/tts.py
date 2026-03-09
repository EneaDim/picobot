from __future__ import annotations

import subprocess
from pathlib import Path
from uuid import uuid4

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.paths import get_tool_bin, get_tool_model, resolve_repo_path, sibling_lib_dirs


class TTSArgs(BaseModel):
    text: str = Field(..., min_length=1)
    lang: str = Field(default="it")
    voice_id: str | None = Field(default=None)
    output_path: str | None = Field(default=None)


def _pick_model(cfg, lang: str) -> str:
    if (lang or "").lower().startswith("it"):
        return get_tool_model(
            cfg,
            "piper_it",
            ".picobot/tools/piper/models/it_IT-paola-medium.onnx",
        )
    return get_tool_model(
        cfg,
        "piper_en",
        ".picobot/tools/piper/models/en_US-lessac-medium.onnx",
    )


def _default_output_dir() -> Path:
    out_dir = Path(resolve_repo_path("outputs/podcasts"))
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _build_output_path(
    *,
    lang: str,
    output_path: str | None = None,
    output_dir: str | None = None,
    file_stem: str | None = None,
    audio_format: str | None = None,
) -> str:
    if str(output_path or "").strip():
        return resolve_repo_path(output_path)

    ext = "wav"
    requested_ext = str(audio_format or "").strip().lower()
    if requested_ext == "wav":
        ext = "wav"

    if str(output_dir or "").strip():
        out_dir = Path(resolve_repo_path(output_dir))
    else:
        out_dir = _default_output_dir()

    out_dir.mkdir(parents=True, exist_ok=True)

    stem = str(file_stem or "").strip()
    if not stem:
        suffix = "it" if (lang or "").lower().startswith("it") else "en"
        stem = f"tts_output_{suffix}_{uuid4().hex[:8]}"

    return str((out_dir / f"{stem}.{ext}").resolve())


def _build_piper_env(piper_bin: str) -> dict[str, str]:
    piper_path = Path(piper_bin).expanduser().resolve()
    piper_root = piper_path.parent.parent

    env = dict()
    lib_dirs = sibling_lib_dirs(piper_bin)
    if lib_dirs:
        env["LD_LIBRARY_PATH"] = ":".join(lib_dirs)

    espeak_data = piper_root / "espeak-ng-data"
    if espeak_data.exists() and espeak_data.is_dir():
        env["ESPEAK_DATA_PATH"] = str(espeak_data.resolve())

    return env


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
    _ = voice_id

    if not str(text or "").strip():
        raise ValueError("text is empty")

    piper_bin = get_tool_bin(cfg, "piper", ".picobot/tools/piper/bin/piper")
    if not piper_bin:
        raise RuntimeError("piper binary not configured")

    model_path = _pick_model(cfg, lang)
    if not model_path:
        raise RuntimeError("piper model path not configured")

    piper_bin_path = Path(piper_bin).expanduser().resolve()
    model_path_obj = Path(model_path).expanduser().resolve()

    if not piper_bin_path.exists():
        raise RuntimeError(f"piper binary not found: {piper_bin_path}")

    if not model_path_obj.exists():
        raise RuntimeError(f"piper model not found: {model_path_obj}")

    final_output = _build_output_path(
        lang=lang,
        output_path=output_path,
        output_dir=output_dir,
        file_stem=file_stem,
        audio_format=audio_format,
    )
    Path(final_output).parent.mkdir(parents=True, exist_ok=True)

    env = dict(**_build_piper_env(str(piper_bin_path)))
    # eredita env di processo
    import os
    merged_env = dict(os.environ)
    merged_env.update(env)

    try:
        cp = subprocess.run(
            [str(piper_bin_path), "--model", str(model_path_obj), "--output_file", str(final_output)],
            input=(str(text).rstrip() + "\n").encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
            env=merged_env,
        )
    except FileNotFoundError as e:
        raise RuntimeError(f"piper binary not found: {piper_bin_path}") from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError("piper timed out") from e

    stdout = (cp.stdout or b"").decode("utf-8", errors="ignore").strip()
    stderr = (cp.stderr or b"").decode("utf-8", errors="ignore").strip()

    if cp.returncode != 0:
        err = stderr or stdout or "tts failed"

        if "libpiper_phonemize.so" in err or "error while loading shared libraries" in err:
            raise RuntimeError(
                "Piper runtime incompleto: il binario esiste ma mancano librerie condivise richieste "
                "(es. libpiper_phonemize.so.*) oppure non sono nel LD_LIBRARY_PATH del bundle tool."
            )

        if "espeak-ng-data" in err or "phontab" in err:
            raise RuntimeError(
                "Piper runtime incompleto o configurato male: espeak-ng-data non trovato dal bundle locale."
            )

        raise RuntimeError(err)

    if not Path(final_output).exists():
        raise RuntimeError(f"tts output not created: {final_output}")

    return final_output


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
            return tool_ok(
                {
                    "audio_path": audio_path,
                    "backend": "local",
                },
                language=args.lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="tts",
        description="Generate speech audio using Piper.",
        schema=TTSArgs,
        handler=_handler,
    )
