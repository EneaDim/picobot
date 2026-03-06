from __future__ import annotations

# Inizializzazione "tooling locale" di Picobot.
#
# Questo modulo NON è runtime-critical per chat/router/retrieval,
# ma è importante per la coerenza operativa del progetto:
# - directory tools
# - binari locali
# - modelli locali
# - stato di presenza/mancanza leggibile
#
# Strategia:
# - niente magie invasive
# - niente installazioni implicite non richieste
# - forniamo:
#   1. snapshot stato
#   2. init directory
#   3. download mirati opzionali
#
# Tutto resta locale e trasparente.

import json
import os
import platform
import stat
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"

PIPER_TARBALLS = {
    "linux_x86_64": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz",
    "linux_aarch64": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz",
}


def _read_json(path: Path) -> dict[str, Any]:
    """
    Legge un file JSON e garantisce dict.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json must be a JSON object")
    return data


def _get(d: dict[str, Any], *keys: str, default=None):
    """
    Getter annidato minimale.
    """
    cur: Any = d
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _ensure_dir(path: Path) -> None:
    """
    Crea directory ricorsivamente.
    """
    path.mkdir(parents=True, exist_ok=True)


def _chmod_x(path: Path) -> None:
    """
    Rende eseguibile un file.
    """
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download(url: str, dest: Path) -> None:
    """
    Download HTTP minimale.
    """
    _ensure_dir(dest.parent)
    req = urllib.request.Request(url, headers={"User-Agent": "picobot-init-tools"})
    with urllib.request.urlopen(req) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"download failed {getattr(response, 'status', '?')} for {url}")
        dest.write_bytes(response.read())


def _platform_key() -> str:
    """
    Chiave piattaforma usata per scegliere i tarball Piper.
    """
    sysname = platform.system().lower()
    machine = platform.machine().lower()

    if sysname == "linux" and machine in {"x86_64", "amd64"}:
        return "linux_x86_64"
    if sysname == "linux" and machine in {"aarch64", "arm64"}:
        return "linux_aarch64"

    return f"{sysname}_{machine}"


def _tool_root_from_cfg(raw_cfg: dict[str, Any]) -> Path:
    """
    Base dir tools da config.
    """
    base = str(_get(raw_cfg, "tools", "base_dir", default=".picobot/tools") or ".picobot/tools")
    return Path(base).expanduser().resolve()


def _collect_paths(raw_cfg: dict[str, Any]) -> dict[str, Path]:
    """
    Colleziona i path principali dei binari/modelli.
    """
    return {
        "tools_root": _tool_root_from_cfg(raw_cfg),

        "ytdlp_bin": Path(str(_get(raw_cfg, "tools", "bins", "ytdlp", default="") or "")).expanduser(),
        "ffmpeg_bin": Path(str(_get(raw_cfg, "tools", "bins", "ffmpeg", default="ffmpeg") or "ffmpeg")).expanduser(),
        "whisper_cpp_cli": Path(str(_get(raw_cfg, "tools", "bins", "whisper_cpp_cli", default="") or "")).expanduser(),
        "piper_bin": Path(str(_get(raw_cfg, "tools", "bins", "piper", default="") or "")).expanduser(),
        "arecord_bin": Path(str(_get(raw_cfg, "tools", "bins", "arecord", default="arecord") or "arecord")).expanduser(),
        "aplay_bin": Path(str(_get(raw_cfg, "tools", "bins", "aplay", default="aplay") or "aplay")).expanduser(),

        "whisper_model": Path(str(_get(raw_cfg, "tools", "models", "whisper_cpp", default="") or "")).expanduser(),
        "piper_it_model": Path(str(_get(raw_cfg, "tools", "models", "piper_it", default="") or "")).expanduser(),
        "piper_en_model": Path(str(_get(raw_cfg, "tools", "models", "piper_en", default="") or "")).expanduser(),
    }


def tool_snapshot(config_path: str | Path) -> dict[str, Any]:
    """
    Restituisce una fotografia dello stato dei tool locali.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    raw_cfg = _read_json(cfg_path)
    paths = _collect_paths(raw_cfg)

    def exists_or_system(path: Path) -> dict[str, Any]:
        text = str(path)
        # Se è comando "nudo" tipo ffmpeg, non possiamo validare il path
        # come file locale. Segnaliamo solo che non è path assoluto.
        if not text or text in {"ffmpeg", "arecord", "aplay"} or "/" not in text:
            return {
                "configured": bool(text),
                "path": text,
                "exists": None,
            }

        return {
            "configured": bool(text),
            "path": text,
            "exists": path.exists(),
        }

    return {
        "config": str(cfg_path),
        "tools_root": str(paths["tools_root"]),
        "platform": _platform_key(),
        "bins": {
            "ytdlp": exists_or_system(paths["ytdlp_bin"]),
            "ffmpeg": exists_or_system(paths["ffmpeg_bin"]),
            "whisper_cpp_cli": exists_or_system(paths["whisper_cpp_cli"]),
            "piper": exists_or_system(paths["piper_bin"]),
            "arecord": exists_or_system(paths["arecord_bin"]),
            "aplay": exists_or_system(paths["aplay_bin"]),
        },
        "models": {
            "whisper_cpp": exists_or_system(paths["whisper_model"]),
            "piper_it": exists_or_system(paths["piper_it_model"]),
            "piper_en": exists_or_system(paths["piper_en_model"]),
        },
    }


def init_tool_dirs(config_path: str | Path) -> dict[str, Any]:
    """
    Crea la struttura directory minima dei tool locali.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    raw_cfg = _read_json(cfg_path)
    paths = _collect_paths(raw_cfg)

    root = paths["tools_root"]
    created = [
        root,
        root / "yt-dlp" / "bin",
        root / "ffmpeg" / "bin",
        root / "whisper.cpp" / "build" / "bin",
        root / "whisper.cpp" / "models",
        root / "piper" / "bin",
        root / "piper" / "models",
        root / "arecord" / "bin",
        root / "aplay" / "bin",
    ]

    for path in created:
        _ensure_dir(path)

    return {
        "ok": True,
        "root": str(root),
        "created": [str(p) for p in created],
    }


def download_ytdlp(config_path: str | Path, overwrite: bool = False) -> dict[str, Any]:
    """
    Scarica yt-dlp nel path configurato.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    raw_cfg = _read_json(cfg_path)
    paths = _collect_paths(raw_cfg)

    dest = paths["ytdlp_bin"]
    if not str(dest):
        raise ValueError("tools.bins.ytdlp is empty in config")

    if dest.exists() and not overwrite:
        return {
            "ok": True,
            "downloaded": False,
            "path": str(dest),
            "reason": "already exists",
        }

    _download(YTDLP_URL, dest)
    _chmod_x(dest)

    return {
        "ok": True,
        "downloaded": True,
        "path": str(dest),
    }


def download_piper_runtime(config_path: str | Path, overwrite: bool = False) -> dict[str, Any]:
    """
    Scarica il runtime Piper per la piattaforma locale, se supportata.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    raw_cfg = _read_json(cfg_path)
    paths = _collect_paths(raw_cfg)

    piper_bin = paths["piper_bin"]
    key = _platform_key()

    if key not in PIPER_TARBALLS:
        return {
            "ok": False,
            "error": f"unsupported platform for bundled Piper runtime: {key}",
        }

    if piper_bin.exists() and not overwrite:
        return {
            "ok": True,
            "downloaded": False,
            "path": str(piper_bin),
            "reason": "already exists",
        }

    url = PIPER_TARBALLS[key]

    with tempfile.TemporaryDirectory(prefix="picobot-piper-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        archive = tmpdir_path / "piper.tar.gz"

        _download(url, archive)

        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(tmpdir_path)

        # Cerchiamo il binario "piper" estratto.
        extracted_bin: Path | None = None
        for cand in tmpdir_path.rglob("piper"):
            if cand.is_file():
                extracted_bin = cand
                break

        if extracted_bin is None:
            return {
                "ok": False,
                "error": "could not find extracted piper binary",
            }

        _ensure_dir(piper_bin.parent)
        piper_bin.write_bytes(extracted_bin.read_bytes())
        _chmod_x(piper_bin)

    return {
        "ok": True,
        "downloaded": True,
        "path": str(piper_bin),
    }


def ensure_env_file(config_path: str | Path) -> dict[str, Any]:
    """
    Scrive un piccolo file di stato dei tool locali.
    """
    cfg_path = Path(config_path).expanduser().resolve()
    raw_cfg = _read_json(cfg_path)
    root = _tool_root_from_cfg(raw_cfg)
    _ensure_dir(root)

    env_path = root / "tooling_state.json"
    snapshot = tool_snapshot(cfg_path)
    env_path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "ok": True,
        "path": str(env_path),
    }
