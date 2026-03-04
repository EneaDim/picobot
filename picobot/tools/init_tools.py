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



def _infer_whisper_repo_from_cli_path(whisper_cli: Path) -> Path:
    # Prefer deterministic: if path contains 'whisper.cpp', repo is that directory.
    try:
        parts = list(whisper_cli.parts)
        if "whisper.cpp" in parts:
            i = parts.index("whisper.cpp")
            return Path(*parts[: i + 1])
    except Exception:
        pass
    # Fallback: walk up and pick the first dir that looks like a repo/build root.
    for parent in [whisper_cli.parent, *whisper_cli.parents]:
        if (parent / ".git").exists() or (parent / "Makefile").exists() or (parent / "CMakeLists.txt").exists():
            return parent
    return whisper_cli.parent


def _find_whisper_cli(repo_dir: Path) -> Path | None:
    # Known locations across whisper.cpp versions
    candidates = [
        repo_dir / "build" / "bin" / "whisper-cli",
        repo_dir / "build" / "bin" / "main",
        repo_dir / "main",
        repo_dir / "whisper-cli",
    ]
    for c in candidates:
        if c.exists():
            return c
    # Last resort: search a bit
    for c in repo_dir.rglob("whisper-cli"):
        if c.is_file():
            return c
    for c in repo_dir.rglob("main"):
        if c.is_file() and c.parent.name in {"bin", "build"}:
            return c
    return None
# ----------------------------
# URLs (minimal set)
# ----------------------------

YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp"
WHISPER_SMALL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"

PIPER_TARBALLS = {
    "linux_x86_64": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz",
    "linux_aarch64": "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz",
}

# Minimal voice map for the voices used by the default template.
# You can add more voice_ids here if you want init-tools to auto-download them.
VOICE_MAP: dict[str, str] = {
    # IT
    "it_IT-paola-medium": "it/it_IT/paola/medium/it_IT-paola-medium",
    "it_IT-aurora-medium": "https://huggingface.co/kirys79/piper_italiano/resolve/main/Aurora/it_IT-aurora-medium",
    # EN
    "en_US-lessac-medium": "en/en_US/lessac/medium/en_US-lessac-medium",
    "en_US-amy-medium": "en/en_US/amy/medium/en_US-amy-medium",
    "en_US-ryan-high": "en/en_US/ryan/high/en_US-ryan-high",
}


# ----------------------------
# Small helpers
# ----------------------------

def _read_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config.json must be a JSON object")
    return data


def _get(d: dict[str, Any], *keys: str, default=None):
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _chmod_x(p: Path) -> None:
    mode = p.stat().st_mode
    p.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _download(url: str, dest: Path) -> None:
    _ensure_dir(dest.parent)
    req = urllib.request.Request(url, headers={"User-Agent": "picobot-init-tools"})
    with urllib.request.urlopen(req) as r:
        if getattr(r, "status", 200) != 200:
            raise RuntimeError(f"download failed {getattr(r,'status','?')} for {url}")
        dest.write_bytes(r.read())


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    subprocess.run(cmd, cwd=str(cwd) if cwd else None, check=True)


def _is_bin_dir(p: Path) -> bool:
    return p.name == "bin" or str(p).endswith("/bin") or str(p).endswith("\\bin")


def _resolve_exe(path_or_bindir: Path, exe_name: str) -> Path:
    return (path_or_bindir / exe_name) if _is_bin_dir(path_or_bindir) else path_or_bindir


def _symlink_or_copy(src: Path, dest: Path) -> None:
    _ensure_dir(dest.parent)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    try:
        dest.symlink_to(src)
    except OSError:
        shutil.copy2(src, dest)
        _chmod_x(dest)


def _platform_key() -> str:
    sys = platform.system().lower().strip()
    mach = platform.machine().lower().strip()
    if sys != "linux":
        return f"{sys}_{mach}"
    if mach in {"x86_64", "amd64"}:
        return "linux_x86_64"
    if mach in {"aarch64", "arm64"}:
        return "linux_aarch64"
    return f"linux_{mach}"


def _hf_voice_urls(voice_id: str) -> tuple[str, str] | None:
    ref = (VOICE_MAP.get(voice_id) or "").strip()
    if not ref:
        return None
    if ref.startswith("http://") or ref.startswith("https://"):
        base = ref
    else:
        base = f"https://huggingface.co/rhasspy/piper-voices/resolve/main/{ref}"
    return (base + ".onnx", base + ".onnx.json")


def _looks_like_json_bytes(b: bytes) -> bool:
    t = (b or b"").lstrip()
    return bool(t.startswith(b"{") or t.startswith(b"["))


# ----------------------------
# Install steps (minimal)
# ----------------------------

def install_ytdlp(ytdlp_cfg: Path) -> None:
    target = _resolve_exe(ytdlp_cfg, "yt-dlp")
    print(f"⬇️  yt-dlp -> {target}")
    if target.exists():
        print("✅ yt-dlp present, skip")
        return
    _download(YTDLP_URL, target)
    _chmod_x(target)
    _run([str(target), "--version"])
    print("✅ yt-dlp ok")


def link_system_exe(cfg_path_or_bindir: Path, exe_name: str) -> None:
    target = _resolve_exe(cfg_path_or_bindir, exe_name)
    print(f"🔗 {exe_name} -> {target}")
    if target.exists():
        print(f"✅ {exe_name} present, skip")
        return
    found = shutil.which(exe_name)
    if not found:
        if exe_name in {"arecord", "aplay"}:
            print("⚠️  ALSA tools not found in PATH. Install them (Linux): sudo apt install alsa-utils")
        else:
            print(f"⚠️  {exe_name} not found in PATH (install it via system package manager)")
        return
    _symlink_or_copy(Path(found), target)
    print(f"✅ {exe_name} ok")


def install_whisper_cpp(repo_dir: Path, model_path: Path) -> None:
    print(f"⬇️  whisper.cpp -> {repo_dir}")
    if repo_dir.exists() and (repo_dir / ".git").exists():
        _run(["git", "-C", str(repo_dir), "pull", "--ff-only"])
    elif repo_dir.exists():
        # Not a git repo.
        # Common case: a stub dir created by previous installers (e.g. only build/ + models/).
        keep = {".keep", ".gitignore"}
        try:
            entries = [x for x in repo_dir.iterdir() if x.name not in keep]
        except Exception:
            entries = []

        import shutil as _shutil

        def _is_stub_only_build_models(items):
            names = {x.name for x in items}
            return names.issubset({"build", "models"})

        if not entries:
            # empty placeholder → replace with clone
            _shutil.rmtree(repo_dir, ignore_errors=True)
            _ensure_dir(repo_dir.parent)
            _run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(repo_dir)])
        elif (repo_dir / "Makefile").exists() or (repo_dir / "CMakeLists.txt").exists():
            # manual checkout → build as-is
            pass
        elif _is_stub_only_build_models(entries):
            # migrate stub → real repo
            tmp_models = None
            models_dir = repo_dir / "models"
            if models_dir.exists():
                tmp_models = repo_dir.parent / (repo_dir.name + ".models.bak")
                if tmp_models.exists():
                    _shutil.rmtree(tmp_models, ignore_errors=True)
                _shutil.move(str(models_dir), str(tmp_models))

            # wipe stub
            _shutil.rmtree(repo_dir, ignore_errors=True)

            # clone fresh repo
            _ensure_dir(repo_dir.parent)
            _run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(repo_dir)])

            # restore models if we had them
            if tmp_models and tmp_models.exists():
                _shutil.move(str(tmp_models), str(repo_dir / "models"))
        else:
            raise RuntimeError(
                f"{repo_dir} exists but is not a git repo and looks non-standard (contains: {[x.name for x in entries]}). "
                "Delete it or point tools.bins.whisper_cpp_cli somewhere else."
            )
    else:
        _ensure_dir(repo_dir.parent)
        _run(["git", "clone", "--depth", "1", "https://github.com/ggml-org/whisper.cpp", str(repo_dir)])

    print("🛠️  build whisper.cpp")
    _run(["make", "-j"], cwd=repo_dir)

    cli = _find_whisper_cli(repo_dir)
    if not cli:
        raise RuntimeError(f"whisper.cpp build completed but whisper-cli not found under: {repo_dir}")
    print(f"✅ whisper.cpp built: {cli}")

    print(f"⬇️  whisper model -> {model_path}")
    if not model_path.exists():
        _ensure_dir(model_path.parent)
        _download(WHISPER_SMALL_URL, model_path)
    if model_path.stat().st_size == 0:
        raise RuntimeError("whisper model downloaded but empty")
    print("✅ whisper.cpp ok")


def install_piper_bundle(piper_cfg: Path) -> Path:
    key = _platform_key()
    if not key.startswith("linux_"):
        raise RuntimeError(f"bundled piper supported only on Linux (got {key})")
    url = PIPER_TARBALLS.get(key)
    if not url:
        raise RuntimeError(f"unsupported Linux arch for bundled piper: {key}")

    bin_dir = piper_cfg if _is_bin_dir(piper_cfg) else piper_cfg.parent
    _ensure_dir(bin_dir)

    wrapper_path = bin_dir / "piper"
    real_bin = bin_dir / "piper.bin"

    print(f"⬇️  piper bundle ({key}) -> {bin_dir}")
    if not real_bin.exists():
        with tempfile.TemporaryDirectory(prefix="picobot-piper-") as td:
            td_path = Path(td)
            tar_path = td_path / "piper.tar.gz"
            _download(url, tar_path)
            with tarfile.open(tar_path, "r:gz") as tf:
                tf.extractall(td_path)

            src_root = td_path / "piper"
            src_piper = src_root / "piper"
            if not src_piper.exists():
                raise RuntimeError("unexpected piper tar layout (missing piper binary)")

            shutil.copy2(src_piper, real_bin)
            _chmod_x(real_bin)

            # libs/share (keep it minimal but robust)
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

            # back-compat (libs at root)
            dst_lib = bin_dir / "lib"
            _ensure_dir(dst_lib)
            for so in src_root.glob("*.so*"):
                shutil.copy2(so, dst_lib / so.name)

            # back-compat (espeak data at root)
            src_espeak = src_root / "espeak-ng-data"
            if src_espeak.exists():
                dst_espeak = bin_dir / "share" / "espeak-ng-data"
                _ensure_dir(dst_espeak.parent)
                if dst_espeak.exists():
                    shutil.rmtree(dst_espeak)
                shutil.copytree(src_espeak, dst_espeak)

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


def _download_piper_pair(dest_onnx: Path, voice_id: str) -> None:
    urls = _hf_voice_urls(voice_id)
    if not urls:
        print(f"⚠️  voice_id not in VOICE_MAP: {voice_id} (skip download; provide files manually)")
        return

    onnx_url, json_url = urls
    json_path = dest_onnx.with_suffix(dest_onnx.suffix + ".json")  # .onnx.json

    _ensure_dir(dest_onnx.parent)

    if not dest_onnx.exists():
        _download(onnx_url, dest_onnx)
    if dest_onnx.stat().st_size == 0:
        raise RuntimeError(f"piper voice onnx empty: {voice_id}")

    if not json_path.exists():
        _download(json_url, json_path)
    jb = json_path.read_bytes()
    if json_path.stat().st_size == 0 or not _looks_like_json_bytes(jb):
        preview = jb[:200].decode("utf-8", errors="replace")
        try:
            json_path.unlink()
        except Exception:
            pass
        raise RuntimeError(f"piper voice json invalid for {voice_id}. First bytes: {preview!r}")

    print(f"✅ piper voice ok: {voice_id}")


def install_piper_models_and_voices(cfg: dict[str, Any]) -> None:
    tools = _get(cfg, "tools", default={}) or {}
    models = _get(tools, "models", default={}) or {}

    piper_it = Path(str(models.get("piper_it") or ""))
    piper_en = Path(str(models.get("piper_en") or ""))

    # minimal: ensure the two configured models exist (download via VOICE_MAP fallback)
    if piper_it.name.endswith(".onnx"):
        print(f"⬇️  piper model it -> {piper_it}")
        _download_piper_pair(piper_it, "it_IT-paola-medium")

    if piper_en.name.endswith(".onnx"):
        print(f"⬇️  piper model en -> {piper_en}")
        _download_piper_pair(piper_en, "en_US-lessac-medium")

    # additionally: download podcast voices (if listed in config)
    pod = _get(cfg, "podcast", default={}) or {}
    voices = _get(pod, "voices", default={}) or {}

    want_voice_ids: list[str] = []
    for lk in ("it", "en"):
        vv = voices.get(lk) or {}
        for role in ("narrator", "expert"):
            vid = ((vv.get(role) or {}).get("voice_id") or "").strip()
            if vid and vid not in want_voice_ids:
                want_voice_ids.append(vid)

    # If config uses voice ids, ensure they exist in the piper voices dir if present
    voices_dir = _get(tools, "voices", "piper_voices_dir", default=None)
    if voices_dir:
        vd = Path(str(voices_dir))
        _ensure_dir(vd)
        for vid in want_voice_ids:
            try:
                _download_piper_pair(vd / f"{vid}.onnx", vid)
            except Exception as e:
                print(f"⚠️  voice download failed for {vid}: {e}")


# ----------------------------
# Main
# ----------------------------

def main() -> int:
    cfg_path = Path(os.environ.get("PICOBOT_CONFIG", ".picobot/config.json"))
    if not cfg_path.exists():
        print(f"❌ config not found: {cfg_path}")
        return 2

    cfg = _read_json(cfg_path)

    tools = _get(cfg, "tools", default={}) or {}
    base_dir = Path(str(_get(tools, "base_dir", default=".picobot/tools")))
    _ensure_dir(base_dir)

    bins = _get(tools, "bins", default={}) or {}
    models = _get(tools, "models", default={}) or {}

    ytdlp = Path(str(bins.get("ytdlp") or ""))
    ffmpeg = Path(str(bins.get("ffmpeg") or ""))
    arecord = Path(str(bins.get("arecord") or ""))
    aplay = Path(str(bins.get("aplay") or ""))
    whisper_cli = Path(str(bins.get("whisper_cpp_cli") or ""))
    piper = Path(str(bins.get("piper") or ""))

    whisper_model = Path(str(models.get("whisper_cpp") or ""))

    print(f"🧩 OS={platform.system()} ARCH={platform.machine()} key={_platform_key()}")

    # Ensure parent dirs exist
    for p in (ytdlp, ffmpeg, arecord, aplay, whisper_cli, piper, whisper_model):
        if str(p).strip():
            _ensure_dir(p.parent if not _is_bin_dir(p) else p)

    # yt-dlp
    if str(ytdlp).strip():
        install_ytdlp(ytdlp)

    # ffmpeg/alsa links (optional but useful)
    if str(ffmpeg).strip():
        link_system_exe(ffmpeg, "ffmpeg")
    if str(arecord).strip():
        link_system_exe(arecord, "arecord")
    if str(aplay).strip():
        link_system_exe(aplay, "aplay")

    # whisper.cpp + model (only if paths are configured)
    # We do NOT require whisper_cli to exist yet: init-tools is responsible for cloning/building it.
    if str(whisper_cli).strip() and str(whisper_model).strip():
        repo = _infer_whisper_repo_from_cli_path(Path(str(whisper_cli)))
        install_whisper_cpp(repo, whisper_model)
        # piper bundle + models/voices
        if str(piper).strip():
            install_piper_bundle(piper)
            install_piper_models_and_voices(cfg)
    
        print("🎉 init-tools done")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
