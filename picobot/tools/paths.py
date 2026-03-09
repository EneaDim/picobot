from __future__ import annotations

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


def get_tool_model(cfg: Any, key: str, default: str = "") -> str:
    value = _get_attr_path(cfg, f"tools.models.{key}", None)
    raw = str(value or default or "").strip()
    if not raw:
        return ""
    return resolve_repo_path(raw)


def sibling_lib_dirs(binary_path: str | Path) -> list[str]:
    """
    Cerca cartelle lib comuni accanto al bundle del tool.
    Esempio:
      .picobot/tools/piper/bin/piper
      -> .picobot/tools/piper/lib
      -> .picobot/tools/piper/lib64
      -> .picobot/tools/piper/bin
    """
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
