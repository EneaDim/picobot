from __future__ import annotations

import json
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any


# ---- URLs ----
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
WHISPER_SMALL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"

# Piper (Linux x86_64). Se sei arm64, va cambiato (dimmi arch e te lo adatto).
PIPER_TARBALL_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"

PIPER_IT_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/it/it_IT/paola/medium/it_IT-paola-medium.onnx?download=true"
PIPER_EN_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/en_US-lessac-medium.onnx?download=true"


def _load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "tools" not in data or not isinstance(data["tools"], dict):
        raise ValueError("Invalid config: missing top-level 'tools' object")
    return data


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _is_probably_bin_dir(p: Path) -> bool:
    # your config uses ".../bin" directories, so we treat those as dirs
    return p.name == "bin" or str(p).endswith("/bin") or str(p).endswith("\\bin")


def _download(url: str, dest: Path) -> None:
    _ensure_dir(dest.parent)
    with urllib.request.urlopen(url) as r:
        if r.status != 200:
            raise RuntimeError(f"Download failed {r.status} for {url}")
        data = r.read()
    dest.write_bytes(data)


def _chmod_x(p: Path) -> None:
    mode = p.stat().st_mode
    p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _symlink_or_copy(src: Path, dest: Path) -> None:
    _ensure_dir(dest.parent)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        dest.symlink_to(src)
    except OSError:
        shutil.copy2(src, dest)
        _chmod_x(dest)


def _resolve_tool_exe(bin_dir_or_path: Path, exe_name: str) -> Path:
    # If config points to ".../bin", install inside it as ".../bin/<exe_name>"
    if _is_probably_bin_dir(bin_dir_or_path):
        return bin_dir_or_path / exe_name
    # Otherwise assume it's the full path to executable
    return bin_dir_or_path


def _install_yt_dlp(ytdlp_bin_cfg: Path) -> None:
    target = _resolve_tool_exe(ytdlp_bin_cfg, "yt-dlp")
    print(f"⬇️  yt-dlp -> {target}")
    if target.exists():
        print("✅ yt-dlp già presente, skip")
        return
    _download(YTDLP_URL, target)
    _chmod_x(target)
    _run([str(target), "--version"])
    print("✅ yt-dlp ok")

def _install_whisper_cpp(whisper_cpp_dir: Path, whisper_model: Path) -> None:
    print(f"⬇️  whisper.cpp -> {whisper_cpp_dir}")

    if whisper_cpp_dir.exists():
        if (whisper_cpp_dir / ".git").exists():
            # existing git repo: update
            _run(["git", "-C", str(whisper_cpp_dir), "pull", "--ff-only"])
        else:
            # directory exists but is not a git repo -> backup + fresh clone
            backup = whisper_cpp_dir.with_name(
                whisper_cpp_dir.name + ".bak"
            )
            i = 1
            while backup.exists():
                backup = whisper_cpp_dir.with_name(f"{whisper_cpp_dir.name}.bak{i}")
                i += 1

            print(f"⚠️  {whisper_cpp_dir} exists but is not a git repo. Moving to {backup}")
            whisper_cpp_dir.rename(backup)

            _run(
                ["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(whisper_cpp_dir)]
            )
    else:
        _ensure_dir(whisper_cpp_dir.parent)
        _run(
            ["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(whisper_cpp_dir)]
        )

    print("🛠️  build whisper.cpp")
    _run(["make", "-j"], cwd=whisper_cpp_dir)

    print(f"⬇️  Whisper model -> {whisper_model}")
    if not whisper_model.exists():
        _download(WHISPER_SMALL_URL, whisper_model)

    if whisper_model.stat().st_size == 0:
        raise RuntimeError("Whisper model downloaded but file is empty")

    print("✅ whisper.cpp ok")

def _install_piper(piper_bin_cfg: Path, model_it: Path, model_en: Path) -> None:
    """
    Install piper as a self-contained bundle and provide a wrapper script that
    sets LD_LIBRARY_PATH / ESPEAK_DATA_PATH so it works on most Linux systems.
    """

    # Config points to ".../piper/bin" directory in your design
    if not _is_probably_bin_dir(piper_bin_cfg):
        # If someone configured a full path, treat parent as bundle root
        bundle_root = piper_bin_cfg.parent
        bin_dir = piper_bin_cfg.parent
    else:
        bin_dir = piper_bin_cfg
        bundle_root = bin_dir.parent  # .../.picobot/tools/piper

    lib_dir = bundle_root / "lib"
    share_dir = bundle_root / "share"
    espeak_data_dir = share_dir / "espeak-ng-data"

    wrapper_path = bin_dir / "piper"
    real_bin_path = bin_dir / "piper.bin"

    print(f"⬇️  piper bundle -> {bundle_root}")

    _ensure_dir(bin_dir)
    _ensure_dir(lib_dir)
    _ensure_dir(share_dir)

    # Install only if missing
    if not real_bin_path.exists():
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            tar_path = td_path / "piper.tar.gz"
            _download(PIPER_TARBALL_URL, tar_path)

            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(td_path)

            src_root = td_path / "piper"
            if not src_root.exists():
                raise RuntimeError(f"Unexpected piper tar layout; missing {src_root}")

            # 1) Copy main binary to bin/piper.bin
            src_piper = src_root / "piper"
            if not src_piper.exists():
                raise RuntimeError(f"Unexpected piper tar layout; missing {src_piper}")
            shutil.copy2(src_piper, real_bin_path)
            _chmod_x(real_bin_path)

            # 2) Copy optional piper_phonemize binary too (nice to have)
            src_ph = src_root / "piper_phonemize"
            if src_ph.exists():
                dst_ph = bin_dir / "piper_phonemize"
                shutil.copy2(src_ph, dst_ph)
                _chmod_x(dst_ph)

            # 3) Copy shared libraries (*.so*)
            for so in src_root.glob("*.so*"):
                shutil.copy2(so, lib_dir / so.name)

            # 4) Copy ONNX runtime model (if present)
            ort = src_root / "libtashkeel_model.ort"
            if ort.exists():
                shutil.copy2(ort, bundle_root / ort.name)

            # 5) Copy espeak-ng-data directory (if present)
            src_espeak_data = src_root / "espeak-ng-data"
            if src_espeak_data.exists():
                if espeak_data_dir.exists():
                    shutil.rmtree(espeak_data_dir)
                shutil.copytree(src_espeak_data, espeak_data_dir)

    # Create/overwrite wrapper script that sets runtime env
    wrapper = """#!/usr/bin/env bash
set -euo pipefail

HERE=\"$(cd \"$(dirname \"${BASH_SOURCE[0]}\")\" && pwd)\"
ROOT=\"$(cd \"$HERE/..\" && pwd)\"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export LD_LIBRARY_PATH="$HERE/lib:$ROOT/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [ -d "$ROOT/share/espeak-ng-data" ]; then
  export ESPEAK_DATA_PATH="$ROOT/share/espeak-ng-data"
fi
exec "$ROOT/bin/piper.bin" "$@"
"""
    wrapper_path.write_text(wrapper, encoding="utf-8")
    _chmod_x(wrapper_path)

    # models
    print(f"⬇️  Piper model IT -> {model_it}")
    if not model_it.exists():
        _download(PIPER_IT_URL, model_it)

    print(f"⬇️  Piper model EN -> {model_en}")
    if not model_en.exists():
        _download(PIPER_EN_URL, model_en)

    if model_it.stat().st_size == 0 or model_en.stat().st_size == 0:
        raise RuntimeError("Piper model download failed (empty file)")

    # sanity check on wrapper (now should find bundled libs)
    _run([str(wrapper_path), "--help"])
    print("✅ piper ok (bundled)")

def _link_system_tool(bin_dir_cfg: Path, exe_name: str) -> None:
    target = _resolve_tool_exe(bin_dir_cfg, exe_name)
    print(f"🔗 {exe_name} -> {target}")

    if target.exists():
        print(f"✅ {exe_name} già presente, skip")
        return

    found = shutil.which(exe_name)
    if not found:
        print(f"⚠️  {exe_name} non trovato in PATH. Installalo via sistema e rilancia init-tools.")
        return

    _symlink_or_copy(Path(found), target)
    print(f"✅ {exe_name} ok (link/copy da {found})")


def main() -> int:
    cfg_path = Path(os.environ.get("PICOBOT_CONFIG", ".picobot/config.json"))
    if not cfg_path.exists():
        print(f"❌ Config not found: {cfg_path}")
        return 2

    cfg = _load_config(cfg_path)
    tools = cfg["tools"]

    base_dir = Path(tools["base_dir"])
    whisper_cpp_dir = Path(tools["whisper_cpp_dir"])
    whisper_model = Path(tools["whisper_model"])

    ytdlp_bin_cfg = Path(tools["ytdlp_bin"])
    ffmpeg_bin_cfg = Path(tools["ffmpeg_bin"])
    arecord_bin_cfg = Path(tools["arecord_bin"])
    aplay_bin_cfg = Path(tools["aplay_bin"])

    piper_bin_cfg = Path(tools["piper_bin"])
    piper_model_it = Path(tools["piper_model_it"])
    piper_model_en = Path(tools["piper_model_en"])

    # Create base dirs early
    _ensure_dir(base_dir)
    _ensure_dir(whisper_model.parent)
    _ensure_dir(piper_model_it.parent)
    _ensure_dir(piper_model_en.parent)
    _ensure_dir(ytdlp_bin_cfg if _is_probably_bin_dir(ytdlp_bin_cfg) else ytdlp_bin_cfg.parent)
    _ensure_dir(piper_bin_cfg if _is_probably_bin_dir(piper_bin_cfg) else piper_bin_cfg.parent)
    _ensure_dir(ffmpeg_bin_cfg if _is_probably_bin_dir(ffmpeg_bin_cfg) else ffmpeg_bin_cfg.parent)
    _ensure_dir(arecord_bin_cfg if _is_probably_bin_dir(arecord_bin_cfg) else arecord_bin_cfg.parent)
    _ensure_dir(aplay_bin_cfg if _is_probably_bin_dir(aplay_bin_cfg) else aplay_bin_cfg.parent)

    print(f"🧩 OS={platform.system()} ARCH={platform.machine()}")
    if platform.system().lower() != "linux":
        print("⚠️  Questo script è pensato principalmente per Linux. Potrebbe richiedere aggiustamenti.")

    _install_yt_dlp(ytdlp_bin_cfg)
    _install_whisper_cpp(whisper_cpp_dir, whisper_model)
    _install_piper(piper_bin_cfg, piper_model_it, piper_model_en)

    # Link system deps into your tools tree (clean + consistent paths)
    _link_system_tool(ffmpeg_bin_cfg, "ffmpeg")
    _link_system_tool(arecord_bin_cfg, "arecord")
    _link_system_tool(aplay_bin_cfg, "aplay")

    print("🎉 Tutti i tools sono stati inizializzati.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
