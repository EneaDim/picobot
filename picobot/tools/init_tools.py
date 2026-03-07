from __future__ import annotations

import argparse
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


def _echo(text: str) -> None:
    print(text, flush=True)


def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config file is not a JSON object: {path}")
    return data


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get(d: dict[str, Any], *keys: str, default=None):
    cur: Any = d
    for key in keys:
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _chmod_x(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download(url: str, dest: Path) -> None:
    _ensure_dir(dest.parent)
    req = urllib.request.Request(url, headers={"User-Agent": "picobot-init-tools"})
    with urllib.request.urlopen(req) as response:
        if getattr(response, "status", 200) != 200:
            raise RuntimeError(f"download failed ({getattr(response, 'status', '?')}): {url}")
        dest.write_bytes(response.read())


def _platform_key() -> str:
    sysname = platform.system().lower()
    machine = platform.machine().lower()

    if sysname == "linux" and machine in {"x86_64", "amd64"}:
        return "linux_x86_64"
    if sysname == "linux" and machine in {"aarch64", "arm64"}:
        return "linux_aarch64"

    return f"{sysname}_{machine}"


def resolve_config_path(explicit: str | None = None) -> Path:
    """
    Risolve il config path in modo pubblico e riusabile.
    """
    candidates: list[Path] = []

    if explicit:
        candidates.append(Path(explicit).expanduser())

    env_cfg = os.environ.get("PICOBOT_CONFIG", "").strip()
    if env_cfg:
        candidates.append(Path(env_cfg).expanduser())

    candidates.extend(
        [
            Path(".picobot/config.json"),
            Path("picobot.config.json"),
            Path("config.json"),
        ]
    )

    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return candidate.resolve()

    raise FileNotFoundError(
        "Config non trovata. Crea .picobot/config.json oppure imposta PICOBOT_CONFIG."
    )


def _tool_root_from_cfg(raw_cfg: dict[str, Any]) -> Path:
    base = str(_get(raw_cfg, "tools", "base_dir", default=".picobot/tools") or ".picobot/tools")
    return Path(base).expanduser().resolve()


def _collect_paths(raw_cfg: dict[str, Any]) -> dict[str, Path]:
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


def _exists_or_system(path: Path) -> dict[str, Any]:
    text = str(path)

    if not text:
        return {"configured": False, "path": text, "exists": False}

    if text in {"ffmpeg", "arecord", "aplay"} or "/" not in text:
        return {"configured": True, "path": text, "exists": None}

    return {"configured": True, "path": text, "exists": path.exists()}


def tool_snapshot(config_path: Path) -> dict[str, Any]:
    raw_cfg = _read_json(config_path)
    paths = _collect_paths(raw_cfg)

    return {
        "config": str(config_path),
        "platform": _platform_key(),
        "tools_root": str(paths["tools_root"]),
        "bins": {
            "ytdlp": _exists_or_system(paths["ytdlp_bin"]),
            "ffmpeg": _exists_or_system(paths["ffmpeg_bin"]),
            "whisper_cpp_cli": _exists_or_system(paths["whisper_cpp_cli"]),
            "piper": _exists_or_system(paths["piper_bin"]),
            "arecord": _exists_or_system(paths["arecord_bin"]),
            "aplay": _exists_or_system(paths["aplay_bin"]),
        },
        "models": {
            "whisper_cpp": _exists_or_system(paths["whisper_model"]),
            "piper_it": _exists_or_system(paths["piper_it_model"]),
            "piper_en": _exists_or_system(paths["piper_en_model"]),
        },
    }


def init_tool_dirs(config_path: Path) -> dict[str, Any]:
    raw_cfg = _read_json(config_path)
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


def download_ytdlp(config_path: Path, overwrite: bool = False) -> dict[str, Any]:
    raw_cfg = _read_json(config_path)
    paths = _collect_paths(raw_cfg)

    dest = paths["ytdlp_bin"]
    if not str(dest):
        raise ValueError("tools.bins.ytdlp is empty in config")

    if dest.exists() and not overwrite:
        return {"ok": True, "downloaded": False, "path": str(dest), "reason": "already exists"}

    _download(YTDLP_URL, dest)
    _chmod_x(dest)

    return {"ok": True, "downloaded": True, "path": str(dest)}


def download_piper_runtime(config_path: Path, overwrite: bool = False) -> dict[str, Any]:
    raw_cfg = _read_json(config_path)
    paths = _collect_paths(raw_cfg)

    piper_bin = paths["piper_bin"]
    key = _platform_key()

    if key not in PIPER_TARBALLS:
        return {"ok": False, "error": f"unsupported platform for bundled Piper runtime: {key}"}

    if piper_bin.exists() and not overwrite:
        return {"ok": True, "downloaded": False, "path": str(piper_bin), "reason": "already exists"}

    url = PIPER_TARBALLS[key]

    with tempfile.TemporaryDirectory(prefix="picobot-piper-") as tmpdir:
        tmpdir_path = Path(tmpdir)
        archive = tmpdir_path / "piper.tar.gz"

        _download(url, archive)

        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(tmpdir_path)

        extracted_bin: Path | None = None
        for cand in tmpdir_path.rglob("piper"):
            if cand.is_file():
                extracted_bin = cand
                break

        if extracted_bin is None:
            return {"ok": False, "error": "could not find extracted piper binary"}

        _ensure_dir(piper_bin.parent)
        piper_bin.write_bytes(extracted_bin.read_bytes())
        _chmod_x(piper_bin)

    return {"ok": True, "downloaded": True, "path": str(piper_bin)}


def write_state_file(config_path: Path) -> dict[str, Any]:
    raw_cfg = _read_json(config_path)
    root = _tool_root_from_cfg(raw_cfg)
    _ensure_dir(root)

    state_path = root / "tooling_state.json"
    snapshot = tool_snapshot(config_path)
    _write_json(state_path, snapshot)

    return {"ok": True, "path": str(state_path)}


def bootstrap_all(config_path: Path, overwrite: bool = False) -> dict[str, Any]:
    report: dict[str, Any] = {
        "config": str(config_path),
        "steps": {},
    }

    report["steps"]["init_dirs"] = init_tool_dirs(config_path)

    try:
        report["steps"]["yt_dlp"] = download_ytdlp(config_path, overwrite=overwrite)
    except Exception as e:
        report["steps"]["yt_dlp"] = {"ok": False, "error": str(e)}

    try:
        report["steps"]["piper_runtime"] = download_piper_runtime(config_path, overwrite=overwrite)
    except Exception as e:
        report["steps"]["piper_runtime"] = {"ok": False, "error": str(e)}

    try:
        report["steps"]["state_file"] = write_state_file(config_path)
    except Exception as e:
        report["steps"]["state_file"] = {"ok": False, "error": str(e)}

    report["snapshot"] = tool_snapshot(config_path)
    return report


def _print_snapshot(snapshot: dict[str, Any]) -> None:
    _echo("")
    _echo(f"Config: {snapshot.get('config')}")
    _echo(f"Platform: {snapshot.get('platform')}")
    _echo(f"Tools root: {snapshot.get('tools_root')}")
    _echo("")
    _echo("Bins:")
    for name, meta in (snapshot.get("bins") or {}).items():
        _echo(f"  - {name}: {meta}")
    _echo("")
    _echo("Models:")
    for name, meta in (snapshot.get("models") or {}).items():
        _echo(f"  - {name}: {meta}")
    _echo("")


def main() -> None:
    parser = argparse.ArgumentParser(description="Picobot local tools bootstrap")
    parser.add_argument("command", nargs="?", default="init", choices=["init", "status", "dirs", "ytdlp", "piper"])
    parser.add_argument("--config", default=None, help="Path to config.json")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite already downloaded binaries")
    args = parser.parse_args()

    config_path = resolve_config_path(args.config)

    if args.command == "status":
        _print_snapshot(tool_snapshot(config_path))
        return

    if args.command == "dirs":
        _echo(json.dumps(init_tool_dirs(config_path), ensure_ascii=False, indent=2))
        return

    if args.command == "ytdlp":
        _echo(json.dumps(download_ytdlp(config_path, overwrite=args.overwrite), ensure_ascii=False, indent=2))
        return

    if args.command == "piper":
        _echo(json.dumps(download_piper_runtime(config_path, overwrite=args.overwrite), ensure_ascii=False, indent=2))
        return

    _echo(json.dumps(bootstrap_all(config_path, overwrite=args.overwrite), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
