from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def resolve_repo_path(value: str | Path | None) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    p = Path(raw).expanduser()
    if p.is_absolute():
        return str(p.resolve())
    return str((repo_root() / p).resolve())


def _get_attr_path(obj: Any, path: str, default: Any = None) -> Any:
    current = obj
    for part in path.split("."):
        if current is None:
            return default
        if hasattr(current, part):
            current = getattr(current, part)
        else:
            return default
    return current


def get_tool_bin(cfg: Any, key: str, default: str = "") -> str:
    value = _get_attr_path(cfg, f"tools.bins.{key}", None)

    legacy_map = {
        "ytdlp": "ytdlp_bin",
        "ffmpeg": "ffmpeg_bin",
        "piper": "piper_bin",
        "aplay": "aplay_bin",
        "arecord": "arecord_bin",
        "whisper_cpp_cli": "whisper_cpp_cli_bin",
    }

    if not value:
        legacy_attr = legacy_map.get(key)
        if legacy_attr:
            value = _get_attr_path(cfg, f"tools.{legacy_attr}", None)

    raw = str(value or default or "").strip()
    if not raw:
        return ""

    if "/" not in raw and "\\" not in raw and not raw.startswith("."):
        return raw

    return resolve_repo_path(raw)


def _detect_docker_backend(cfg: Any) -> bool:
    """
    Rilevazione robusta e pragmatica del backend docker.

    Ordine:
    1. sandbox.runtime.backend == "docker"
    2. sandbox.runtime.docker.enabled == True
    3. fallback su config raw da .picobot/config.json
    """
    backend = str(_get_attr_path(cfg, "sandbox.runtime.backend", "") or "").strip().lower()
    if backend == "docker":
        return True

    docker_enabled = _get_attr_path(cfg, "sandbox.runtime.docker.enabled", None)
    if docker_enabled is True:
        return True

    # fallback robusto sul file raw
    try:
        import json
        raw_cfg = json.loads((repo_root() / ".picobot" / "config.json").read_text(encoding="utf-8"))
        raw_backend = str(
            (((raw_cfg.get("sandbox") or {}).get("runtime") or {}).get("backend") or "")
        ).strip().lower()
        if raw_backend == "docker":
            return True

        raw_docker_enabled = (
            (((raw_cfg.get("sandbox") or {}).get("runtime") or {}).get("docker") or {}).get("enabled")
        )
        if raw_docker_enabled is True:
            return True
    except Exception:
        pass

    return False


def get_runtime_tool_bin(cfg: Any, key: str, fallback: str) -> str:
    """
    - backend docker -> usa il binario sul PATH del container
    - backend host   -> usa il path/tool locale risolto da config
    """
    if _detect_docker_backend(cfg):
        return fallback
    return get_tool_bin(cfg, key, fallback)


def get_tool_model(cfg: Any, key: str, default: str = "") -> str:
    value = _get_attr_path(cfg, f"tools.models.{key}", None)
    raw = str(value or default or "").strip()
    if not raw:
        return ""
    return resolve_repo_path(raw)


def sibling_lib_dirs(binary_path: str | Path) -> list[str]:
    p = Path(str(binary_path)).expanduser().resolve()
    if not p.exists():
        return []

    candidates = [
        p.parent.parent / "lib",
        p.parent.parent / "lib64",
        p.parent,
    ]

    out: list[str] = []
    seen: set[str] = set()

    for c in candidates:
        try:
            rp = str(c.resolve())
        except Exception:
            continue
        if c.exists() and c.is_dir() and rp not in seen:
            seen.add(rp)
            out.append(rp)

    return out
