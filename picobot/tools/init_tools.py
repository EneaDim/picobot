from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


YT_DLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
PIPER_LINUX_X86_64_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"

VOICE_URLS = {
    "it_IT-paola-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/it/it_IT/paola/medium/it_IT-paola-medium.onnx.json",
    },
    "en_US-lessac-medium": {
        "onnx": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx",
        "json": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium.onnx.json",
    },
}


@dataclass(frozen=True)
class DownloadResult:
    path: str
    downloaded: bool
    size_bytes: int


def resolve_config_path(config_path: str | None = None) -> Path:
    if config_path:
        return Path(config_path).expanduser().resolve()

    candidates = [
        Path(".picobot/config.json"),
        Path("picobot.config.json"),
        Path("config.json"),
        Path.home() / ".picobot" / "config.json",
    ]
    for p in candidates:
        if p.exists():
            return p.expanduser().resolve()

    raise FileNotFoundError("Config non trovata. Crea .picobot/config.json")


def _repo_root_from_config(cfg_path: Path) -> Path:
    if cfg_path.parent.name == ".picobot":
        return cfg_path.parent.parent.resolve()
    return Path.cwd().resolve()


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config non valida: {path}")
    return data


def _get_in(d: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def _resolve_repo_path(repo_root: Path, value: str | None, default: str = "") -> Path:
    raw = str(value or default or "").strip()
    if not raw:
        raise ValueError("path vuoto")
    p = Path(raw).expanduser()
    if p.is_absolute():
        return p.resolve()
    return (repo_root / p).resolve()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _download(url: str, dest: Path, *, overwrite: bool) -> DownloadResult:
    if dest.exists() and not overwrite:
        return DownloadResult(path=str(dest), downloaded=False, size_bytes=dest.stat().st_size)

    _ensure_parent(dest)

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "picobot-init-tools/1.0",
            "Accept": "*/*",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = resp.read()

    dest.write_bytes(data)
    return DownloadResult(path=str(dest), downloaded=True, size_bytes=len(data))


def _make_executable(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _safe_extract_tar(archive_path: Path, target_dir: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:gz") as tf:
        tf.extractall(target_dir)


def _linux_x86_64() -> bool:
    sys_name = platform.system().lower()
    machine = platform.machine().lower()
    return sys_name == "linux" and machine in {"x86_64", "amd64"}


def _check_piper_bundle(bundle_root: Path) -> dict[str, Any]:
    piper_bin = bundle_root / "bin" / "piper"
    lib_dir = bundle_root / "lib"
    espeak_dir = bundle_root / "espeak-ng-data"

    lib_candidates = sorted([p.name for p in lib_dir.glob("*")]) if lib_dir.exists() else []
    return {
        "bundle_root": str(bundle_root),
        "piper_bin_exists": piper_bin.exists(),
        "lib_dir_exists": lib_dir.exists(),
        "espeak_ng_data_exists": espeak_dir.exists(),
        "lib_count": len(lib_candidates),
        "sample_libs": lib_candidates[:20],
    }


def _find_extracted_piper_root(extract_root: Path) -> Path:
    """
    Trova la root reale del bundle estratto.
    Nel layout osservato:
      _extract/piper/piper
      _extract/piper/libpiper_phonemize.so...
      _extract/piper/espeak-ng-data/...
    quindi la root reale è _extract/piper
    """
    direct = extract_root / "piper"
    if direct.exists() and direct.is_dir():
        return direct

    for child in extract_root.iterdir():
        if child.is_dir() and (child / "piper").exists():
            return child

    raise RuntimeError("Bundle Piper estratto ma layout non riconosciuto")


def _install_piper_bundle_from_extracted(extracted_root: Path, piper_root: Path) -> dict[str, Any]:
    """
    Layout reale osservato:
      extracted_root/piper
      extracted_root/piper_phonemize
      extracted_root/lib*.so*
      extracted_root/*.ort
      extracted_root/espeak-ng-data/

    Installazione target:
      piper_root/bin/piper
      piper_root/bin/piper_phonemize
      piper_root/lib/*.so*
      piper_root/lib/*.ort
      piper_root/espeak-ng-data/
    """
    bin_dir = piper_root / "bin"
    lib_dir = piper_root / "lib"
    espeak_dir = piper_root / "espeak-ng-data"

    if bin_dir.exists():
        shutil.rmtree(bin_dir)
    if lib_dir.exists():
        shutil.rmtree(lib_dir)
    if espeak_dir.exists():
        shutil.rmtree(espeak_dir)

    bin_dir.mkdir(parents=True, exist_ok=True)
    lib_dir.mkdir(parents=True, exist_ok=True)

    bin_src = extracted_root / "piper"
    if not bin_src.exists() or not bin_src.is_file():
        raise RuntimeError(f"Binario Piper non trovato nel bundle estratto: {bin_src}")

    shutil.copy2(bin_src, bin_dir / "piper")
    _make_executable(bin_dir / "piper")

    phonemize_src = extracted_root / "piper_phonemize"
    if phonemize_src.exists() and phonemize_src.is_file():
        shutil.copy2(phonemize_src, bin_dir / "piper_phonemize")
        _make_executable(bin_dir / "piper_phonemize")

    copied_libs: list[str] = []
    for item in extracted_root.iterdir():
        if not item.is_file():
            continue
        name = item.name
        if ".so" in name or name.endswith(".ort"):
            shutil.copy2(item, lib_dir / name)
            copied_libs.append(name)

    espeak_src = extracted_root / "espeak-ng-data"
    if espeak_src.exists() and espeak_src.is_dir():
        shutil.copytree(espeak_src, espeak_dir)

    return {
        "installed_bin": str((bin_dir / "piper").resolve()),
        "installed_phonemize_bin": str((bin_dir / "piper_phonemize").resolve()) if (bin_dir / "piper_phonemize").exists() else None,
        "installed_lib_dir": str(lib_dir.resolve()),
        "installed_espeak_dir": str(espeak_dir.resolve()) if espeak_dir.exists() else None,
        "copied_libs": copied_libs,
    }


def _download_piper_bundle(repo_root: Path, cfg: dict[str, Any], overwrite: bool) -> dict[str, Any]:
    if not _linux_x86_64():
        raise RuntimeError("Questo bootstrap Piper è configurato per Linux x86_64")

    tools_base = _resolve_repo_path(repo_root, _get_in(cfg, "tools.base_dir"), ".picobot/tools")
    piper_root = tools_base / "piper"
    archive_path = piper_root / "downloads" / "piper_linux_x86_64.tar.gz"

    piper_root.mkdir(parents=True, exist_ok=True)
    dl = _download(PIPER_LINUX_X86_64_URL, archive_path, overwrite=overwrite)

    extract_root = piper_root / "_extract"
    if extract_root.exists() and overwrite:
        shutil.rmtree(extract_root)

    _safe_extract_tar(archive_path, extract_root)

    extracted_root = _find_extracted_piper_root(extract_root)
    install_info = _install_piper_bundle_from_extracted(extracted_root, piper_root)

    bundle_info = _check_piper_bundle(piper_root)
    bundle_info["download"] = {
        "path": dl.path,
        "downloaded": dl.downloaded,
        "size_bytes": dl.size_bytes,
    }
    bundle_info["install"] = install_info
    bundle_info["extracted_root"] = str(extracted_root)
    return bundle_info


def _download_voice_pair(dest_dir: Path, voice_name: str, overwrite: bool) -> dict[str, Any]:
    if voice_name not in VOICE_URLS:
        raise RuntimeError(f"Voice non supportata da bootstrap: {voice_name}")

    urls = VOICE_URLS[voice_name]
    dest_dir.mkdir(parents=True, exist_ok=True)

    onnx_path = dest_dir / f"{voice_name}.onnx"
    json_path = dest_dir / f"{voice_name}.onnx.json"

    onnx_res = _download(urls["onnx"], onnx_path, overwrite=overwrite)
    json_res = _download(urls["json"], json_path, overwrite=overwrite)

    return {
        "voice": voice_name,
        "onnx": {
            "path": onnx_res.path,
            "downloaded": onnx_res.downloaded,
            "size_bytes": onnx_res.size_bytes,
        },
        "json": {
            "path": json_res.path,
            "downloaded": json_res.downloaded,
            "size_bytes": json_res.size_bytes,
        },
    }


def _download_piper_models(repo_root: Path, cfg: dict[str, Any], overwrite: bool) -> dict[str, Any]:
    models = _get_in(cfg, "tools.models", {}) or {}
    piper_it = _resolve_repo_path(repo_root, models.get("piper_it"), ".picobot/tools/piper/models/it_IT-paola-medium.onnx")
    piper_en = _resolve_repo_path(repo_root, models.get("piper_en"), ".picobot/tools/piper/models/en_US-lessac-medium.onnx")

    out = {
        "it": _download_voice_pair(piper_it.parent, "it_IT-paola-medium", overwrite=overwrite),
        "en": _download_voice_pair(piper_en.parent, "en_US-lessac-medium", overwrite=overwrite),
    }
    return out


def _download_ytdlp(repo_root: Path, cfg: dict[str, Any], overwrite: bool) -> dict[str, Any]:
    ytdlp_path = _resolve_repo_path(
        repo_root,
        _get_in(cfg, "tools.bins.ytdlp"),
        ".picobot/tools/yt-dlp/bin/yt-dlp",
    )
    res = _download(YT_DLP_URL, ytdlp_path, overwrite=overwrite)
    _make_executable(ytdlp_path)

    node_path = shutil.which("node") or "/usr/bin/node"
    return {
        "binary": {
            "path": str(ytdlp_path),
            "downloaded": res.downloaded,
            "size_bytes": res.size_bytes,
            "exists": ytdlp_path.exists(),
            "executable": os.access(ytdlp_path, os.X_OK),
        },
        "js_runtime": {
            "node_path": node_path,
            "exists": Path(node_path).exists(),
        },
    }


def bootstrap_all(config_path: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    cfg_path = resolve_config_path(config_path)
    repo_root = _repo_root_from_config(cfg_path)
    cfg = _load_json(cfg_path)

    result: dict[str, Any] = {
        "config_path": str(cfg_path),
        "repo_root": str(repo_root),
        "overwrite": bool(overwrite),
        "tools": {},
    }

    result["tools"]["yt_dlp"] = _download_ytdlp(repo_root, cfg, overwrite=overwrite)
    result["tools"]["piper_bundle"] = _download_piper_bundle(repo_root, cfg, overwrite=overwrite)
    result["tools"]["piper_models"] = _download_piper_models(repo_root, cfg, overwrite=overwrite)

    return result


def tool_snapshot(config_path: str | None = None) -> dict[str, Any]:
    cfg_path = resolve_config_path(config_path)
    repo_root = _repo_root_from_config(cfg_path)
    cfg = _load_json(cfg_path)

    tools_base = _resolve_repo_path(repo_root, _get_in(cfg, "tools.base_dir"), ".picobot/tools")
    ytdlp_path = _resolve_repo_path(repo_root, _get_in(cfg, "tools.bins.ytdlp"), ".picobot/tools/yt-dlp/bin/yt-dlp")
    piper_path = _resolve_repo_path(repo_root, _get_in(cfg, "tools.bins.piper"), ".picobot/tools/piper/bin/piper")

    piper_root = tools_base / "piper"
    models = _get_in(cfg, "tools.models", {}) or {}
    piper_it = _resolve_repo_path(repo_root, models.get("piper_it"), ".picobot/tools/piper/models/it_IT-paola-medium.onnx")
    piper_en = _resolve_repo_path(repo_root, models.get("piper_en"), ".picobot/tools/piper/models/en_US-lessac-medium.onnx")

    piper_info = _check_piper_bundle(piper_root)

    return {
        "config_path": str(cfg_path),
        "repo_root": str(repo_root),
        "yt_dlp": {
            "path": str(ytdlp_path),
            "exists": Path(ytdlp_path).exists(),
            "executable": os.access(ytdlp_path, os.X_OK) if Path(ytdlp_path).exists() else False,
            "node_path": shutil.which("node") or "/usr/bin/node",
            "node_exists": Path(shutil.which("node") or "/usr/bin/node").exists(),
        },
        "piper": {
            "path": str(piper_path),
            "exists": Path(piper_path).exists(),
            "executable": os.access(piper_path, os.X_OK) if Path(piper_path).exists() else False,
            "bundle": piper_info,
            "models": {
                "it": {
                    "path": str(piper_it),
                    "exists": Path(piper_it).exists(),
                    "json_exists": Path(str(piper_it) + ".json").exists(),
                },
                "en": {
                    "path": str(piper_en),
                    "exists": Path(piper_en).exists(),
                    "json_exists": Path(str(piper_en) + ".json").exists(),
                },
            },
        },
    }
