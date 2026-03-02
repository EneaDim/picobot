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

# Piper bundles (rhasspy/piper release)
PIPER_TARBALLS = {
    "linux_x86_64": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz",
    "linux_aarch64": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz",
}

# voice_id -> either:
#  - rhasspy prefix (resolve/main/<prefix>) OR
#  - full base URL (without .onnx/.onnx.json)
# We download BOTH .onnx and .onnx.json
VOICE_MAP: dict[str, str] = {
    # IT
    "it_IT-paola-medium": "it/it_IT/paola/medium/it_IT-paola-medium",
    "it_IT-aurora-medium": "https://huggingface.co/kirys79/piper_italiano/resolve/main/Aurora/it_IT-aurora-medium",
    "it_IT-riccardo-low": "it/it_IT/riccardo/low/it_IT-riccardo-low",
    # EN
    "en_US-lessac-medium": "en/en_US/lessac/medium/en_US-lessac-medium",
    "en_US-amy-medium": "en/en_US/amy/medium/en_US-amy-medium",
    "en_US-ryan-high": "en/en_US/ryan/high/en_US-ryan-high",
}


def _load_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "tools" not in data or not isinstance(data["tools"], dict):
        raise ValueError("Invalid config: missing top-level 'tools' object")
    return data


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _is_probably_bin_dir(p: Path) -> bool:
    return p.name == "bin" or str(p).endswith("/bin") or str(p).endswith("\\bin")


def _download(url: str, dest: Path) -> None:
    _ensure_dir(dest.parent)
    req = urllib.request.Request(url, headers={"User-Agent": "picobot-init-tools"})
    with urllib.request.urlopen(req) as r:
        if getattr(r, "status", 200) != 200:
            raise RuntimeError(f"Download failed {getattr(r,'status','?')} for {url}")
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
    if _is_probably_bin_dir(bin_dir_or_path):
        return bin_dir_or_path / exe_name
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
            _run(["git", "-C", str(whisper_cpp_dir), "pull", "--ff-only"])
        else:
            backup = whisper_cpp_dir.with_name(whisper_cpp_dir.name + ".bak")
            i = 1
            while backup.exists():
                backup = whisper_cpp_dir.with_name(f"{whisper_cpp_dir.name}.bak{i}")
                i += 1
            print(f"⚠️  {whisper_cpp_dir} exists but is not a git repo. Moving to {backup}")
            whisper_cpp_dir.rename(backup)
            _run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(whisper_cpp_dir)])
    else:
        _ensure_dir(whisper_cpp_dir.parent)
        _run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(whisper_cpp_dir)])

    print("🛠️  build whisper.cpp")
    _run(["make", "-j"], cwd=whisper_cpp_dir)

    print(f"⬇️  Whisper model -> {whisper_model}")
    if not whisper_model.exists():
        _download(WHISPER_SMALL_URL, whisper_model)

    if whisper_model.stat().st_size == 0:
        raise RuntimeError("Whisper model downloaded but file is empty")

    print("✅ whisper.cpp ok")


def _piper_platform_key() -> str:
    sys = platform.system().lower().strip()
    mach = platform.machine().lower().strip()
    if sys != "linux":
        return f"{sys}_{mach}"
    if mach in {"x86_64", "amd64"}:
        return "linux_x86_64"
    if mach in {"aarch64", "arm64"}:
        return "linux_aarch64"
    return f"linux_{mach}"


def _install_piper_bundle(piper_bin_cfg: Path) -> Path:
    """
    Install piper as a self-contained bundle in the configured bin dir.
    Layout:
      <bin>/piper.bin
      <bin>/piper_phonemize (optional)
      <bin>/lib/*.so*
      <bin>/share/espeak-ng-data/*
      <bin>/piper (wrapper)
    Returns: wrapper path (<bin>/piper)
    """
    if not _is_probably_bin_dir(piper_bin_cfg):
        bin_dir = piper_bin_cfg.parent
    else:
        bin_dir = piper_bin_cfg

    _ensure_dir(bin_dir)

    wrapper_path = bin_dir / "piper"
    real_bin_path = bin_dir / "piper.bin"

    key = _piper_platform_key()
    url = PIPER_TARBALLS.get(key)
    print(f"⬇️  piper bundle ({key}) -> {bin_dir}")
    if not url:
        raise RuntimeError(f"Unsupported platform for bundled piper: {key}")

    if not real_bin_path.exists():
        with tempfile.TemporaryDirectory() as td:
            td_path = Path(td)
            tar_path = td_path / "piper.tar.gz"
            _download(url, tar_path)

            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(td_path)

            src_root = td_path / "piper"
            if not src_root.exists():
                raise RuntimeError(f"Unexpected piper tar layout; missing {src_root}")

            src_piper = src_root / "piper"
            if not src_piper.exists():
                raise RuntimeError(f"Unexpected piper tar layout; missing {src_piper}")
            shutil.copy2(src_piper, real_bin_path)
            _chmod_x(real_bin_path)

            src_ph = src_root / "piper_phonemize"
            if src_ph.exists():
                dst_ph = bin_dir / "piper_phonemize"
                shutil.copy2(src_ph, dst_ph)
                _chmod_x(dst_ph)

            # Prefer upstream layout if present
            src_lib = src_root / "lib"
            if src_lib.exists():
                dst_lib = bin_dir / "lib"
                if dst_lib.exists():
                    shutil.rmtree(dst_lib)
                shutil.copytree(src_lib, dst_lib)

            src_share = src_root / "share"
            if src_share.exists():
                dst_share = bin_dir / "share"
                if dst_share.exists():
                    shutil.rmtree(dst_share)
                shutil.copytree(src_share, dst_share)

            # Back-compat: libs at root
            dst_lib = bin_dir / "lib"
            _ensure_dir(dst_lib)
            for so in src_root.glob("*.so*"):
                shutil.copy2(so, dst_lib / so.name)

            # Back-compat: espeak-ng-data at root
            src_espeak_data = src_root / "espeak-ng-data"
            if src_espeak_data.exists():
                dst_espeak = bin_dir / "share" / "espeak-ng-data"
                _ensure_dir(dst_espeak.parent)
                if dst_espeak.exists():
                    shutil.rmtree(dst_espeak)
                shutil.copytree(src_espeak_data, dst_espeak)

            ort = src_root / "libtashkeel_model.ort"
            if ort.exists():
                shutil.copy2(ort, bin_dir / ort.name)

    wrapper = """#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export LD_LIBRARY_PATH="$HERE/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if [ -d "$HERE/share/espeak-ng-data" ]; then
  export ESPEAK_DATA_PATH="$HERE/share/espeak-ng-data"
fi
exec "$HERE/piper.bin" "$@"
"""
    wrapper_path.write_text(wrapper, encoding="utf-8")
    _chmod_x(wrapper_path)

    _run([str(wrapper_path), "--help"])
    print("✅ piper ok (bundled)")
    return wrapper_path


def _voice_urls(voice_id: str) -> tuple[str, str] | None:
    ref = (VOICE_MAP.get(voice_id) or "").strip()
    if not ref:
        return None
    # ref can be either a rhasspy prefix or a full base URL.
    if ref.startswith("http://") or ref.startswith("https://"):
        base = ref
    else:
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{ref}"
    return (base + ".onnx", base + ".onnx.json")

def _looks_like_json_bytes(b: bytes) -> bool:
    t = (b or b"").lstrip()
    return bool(t.startswith(b"{") or t.startswith(b"["))


def _download_voice_pair(voices_dir: Path, voice_id: str) -> None:
    urls = _voice_urls(voice_id)
    if not urls:
        print(f"⚠️  Unknown voice_id '{voice_id}'. Skipping download (provide files manually).")
        return

    onnx_url, json_url = urls
    onnx_path = voices_dir / f"{voice_id}.onnx"
    json_path = voices_dir / f"{voice_id}.onnx.json"

    print(f"⬇️  Piper voice -> {voice_id}")

    if not onnx_path.exists():
        _download(onnx_url, onnx_path)
    if onnx_path.stat().st_size == 0:
        raise RuntimeError(f"Voice onnx empty: {voice_id}")

    if not json_path.exists():
        _download(json_url, json_path)
    jb = json_path.read_bytes()
    if json_path.stat().st_size == 0 or not _looks_like_json_bytes(jb):
        # likely HTML error page
        preview = jb[:200].decode("utf-8", errors="replace")
        try:
            json_path.unlink()
        except Exception:
            pass
        raise RuntimeError(f"Voice json invalid for {voice_id}. First bytes: {preview!r}")

    print(f"✅ voice ok: {voice_id}")


def _install_piper(
    piper_bin_cfg: Path,
    model_it: Path,
    model_en: Path,
    voices_dir: Path | None,
    cfg: dict[str, Any],
) -> None:
    wrapper_path = _install_piper_bundle(piper_bin_cfg)

    def ensure_model_pair(model_path: Path, fallback_voice_id: str) -> None:
        _ensure_dir(model_path.parent)
        json_path = model_path.with_suffix(model_path.suffix + ".json")  # .onnx.json

        if model_path.exists() and json_path.exists():
            if model_path.stat().st_size == 0:
                raise RuntimeError(f"Model onnx empty: {model_path.name}")
            jb = json_path.read_bytes()
            if json_path.stat().st_size == 0 or not _looks_like_json_bytes(jb):
                preview = jb[:200].decode("utf-8", errors="replace")
                raise RuntimeError(f"Model json invalid: {json_path.name}. First bytes: {preview!r}")
            return

        print(f"⬇️  Piper model pair -> {model_path.name}")
        urls = _voice_urls(fallback_voice_id)
        if not urls:
            raise RuntimeError(f"No download mapping for fallback voice_id={fallback_voice_id}")
        onnx_url, onnx_json_url = urls

        if not model_path.exists():
            _download(onnx_url, model_path)
        if model_path.stat().st_size == 0:
            raise RuntimeError(f"Model onnx empty: {model_path.name}")

        if not json_path.exists():
            _download(onnx_json_url, json_path)
        jb = json_path.read_bytes()
        if json_path.stat().st_size == 0 or not _looks_like_json_bytes(jb):
            preview = jb[:200].decode("utf-8", errors="replace")
            try:
                json_path.unlink()
            except Exception:
                pass
            raise RuntimeError(f"Model json invalid: {json_path.name}. First bytes: {preview!r}")

    ensure_model_pair(model_it, "it_IT-paola-medium")
    ensure_model_pair(model_en, "en_US-lessac-medium")

    if voices_dir:
        _ensure_dir(voices_dir)

        def collect_voice_ids() -> list[str]:
            out: list[str] = []
            pod = cfg.get("podcast") or {}
            voices = (pod.get("voices") or {})
            for lang_key in ("it", "en"):
                vv = voices.get(lang_key) or {}
                for role in ("narrator", "expert"):
                    vid = ((vv.get(role) or {}).get("voice_id") or "").strip()
                    if vid and vid not in out:
                        out.append(vid)
            return out

        for vid in collect_voice_ids():
            try:
                _download_voice_pair(voices_dir, vid)
            except Exception as e:
                print(f"⚠️  voice download failed for {vid}: {e}")

    _run([str(wrapper_path), "--model", str(model_it), "--help"])
    print("✅ piper models ok")


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

    voices_dir = None
    if tools.get("piper_voices_dir"):
        voices_dir = Path(tools["piper_voices_dir"])

    _ensure_dir(base_dir)
    _ensure_dir(whisper_model.parent)
    _ensure_dir(piper_model_it.parent)
    _ensure_dir(piper_model_en.parent)

    _ensure_dir(ytdlp_bin_cfg if _is_probably_bin_dir(ytdlp_bin_cfg) else ytdlp_bin_cfg.parent)
    _ensure_dir(piper_bin_cfg if _is_probably_bin_dir(piper_bin_cfg) else piper_bin_cfg.parent)
    _ensure_dir(ffmpeg_bin_cfg if _is_probably_bin_dir(ffmpeg_bin_cfg) else ffmpeg_bin_cfg.parent)
    _ensure_dir(arecord_bin_cfg if _is_probably_bin_dir(arecord_bin_cfg) else arecord_bin_cfg.parent)
    _ensure_dir(aplay_bin_cfg if _is_probably_bin_dir(aplay_bin_cfg) else aplay_bin_cfg.parent)

    if voices_dir:
        _ensure_dir(voices_dir)

    print(f"🧩 OS={platform.system()} ARCH={platform.machine()} key={_piper_platform_key()}")
    if platform.system().lower() != "linux":
        print("⚠️  Questo script è pensato principalmente per Linux. Potrebbe richiedere aggiustamenti.")

    _install_yt_dlp(ytdlp_bin_cfg)
    _install_whisper_cpp(whisper_cpp_dir, whisper_model)
    _install_piper(piper_bin_cfg, piper_model_it, piper_model_en, voices_dir, cfg)

    _link_system_tool(ffmpeg_bin_cfg, "ffmpeg")
    _link_system_tool(arecord_bin_cfg, "arecord")
    _link_system_tool(aplay_bin_cfg, "aplay")

    print("🎉 Tutti i tools sono stati inizializzati.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
