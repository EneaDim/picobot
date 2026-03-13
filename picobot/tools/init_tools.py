from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


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


def _repo_root_from_config(cfg_path: Path) -> Path:
    if cfg_path.parent.name == ".picobot":
        return cfg_path.parent.parent.resolve()
    return Path.cwd().resolve()


def _workspace_root(repo_root: Path, cfg: dict[str, Any]) -> Path:
    raw = str(_get_in(cfg, "workspace", ".picobot/workspace") or ".picobot/workspace").strip()
    p = Path(raw).expanduser()
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def _docker_cfg(cfg: dict[str, Any]) -> dict[str, Any]:
    return {
        "docker_bin": str(_get_in(cfg, "sandbox.runtime.docker.docker_bin", "docker") or "docker"),
        "image": str(_get_in(cfg, "sandbox.runtime.docker.image", "picobot-sandbox:latest") or "picobot-sandbox:latest"),
        "container_name": str(_get_in(cfg, "sandbox.runtime.docker.container_name", "picobot-sandbox") or "picobot-sandbox"),
        "container_workspace_root": str(_get_in(cfg, "sandbox.runtime.docker.container_workspace_root", "/workspace") or "/workspace"),
        "auto_create": bool(_get_in(cfg, "sandbox.runtime.docker.auto_create", True)),
        "extra_run_args": list(_get_in(cfg, "sandbox.runtime.docker.extra_run_args", []) or []),
    }


def _installed_voices(cfg: dict[str, Any]) -> list[str]:
    voices = []
    seen = set()

    def add(v: str | None) -> None:
        value = str(v or "").strip()
        if value and value not in seen:
            seen.add(value)
            voices.append(value)

    for v in _get_in(cfg, "tools.piper.installed_voices", []) or []:
        add(v)

    podcast = _get_in(cfg, "podcast.voices", {}) or {}
    if isinstance(podcast, dict):
        for lang_block in podcast.values():
            if not isinstance(lang_block, dict):
                continue
            for role_cfg in lang_block.values():
                if isinstance(role_cfg, dict):
                    add(role_cfg.get("voice_id"))

    return voices


def _custom_voice_urls(cfg: dict[str, Any]) -> dict[str, dict[str, str]]:
    raw = _get_in(cfg, "tools.piper.custom_voice_urls", {}) or {}
    if not isinstance(raw, dict):
        return {}

    out: dict[str, dict[str, str]] = {}
    for voice_id, urls in raw.items():
        if not isinstance(urls, dict):
            continue
        onnx = str(urls.get("onnx") or "").strip()
        js = str(urls.get("json") or "").strip()
        if onnx and js:
            out[str(voice_id)] = {"onnx": onnx, "json": js}
    return out


def _docker_run(
    cfg: dict[str, Any],
    *,
    argv: list[str],
    mount_workspace: bool = True,
    extra_env: dict[str, str] | None = None,
    config_path: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    docker = _docker_cfg(cfg)
    cfg_path = config_path or resolve_config_path(None)
    repo_root = _repo_root_from_config(cfg_path)
    workspace_root = _workspace_root(repo_root, cfg)
    workspace_root.mkdir(parents=True, exist_ok=True)

    cmd = [docker["docker_bin"], "run", "--rm"]

    if mount_workspace:
        cmd += ["-v", f"{workspace_root}:{docker['container_workspace_root']}"]

    for item in docker["extra_run_args"]:
        cmd.append(str(item))

    for key, value in (extra_env or {}).items():
        cmd += ["-e", f"{key}={value}"]

    cmd += [docker["image"]]
    cmd += argv

    return subprocess.run(cmd, text=True, capture_output=True)


def tool_snapshot(config_path: str | Path | None = None) -> dict[str, Any]:
    resolved_cfg = resolve_config_path(str(config_path) if config_path is not None else None)
    cfg = _load_json(resolved_cfg)
    repo_root = _repo_root_from_config(resolved_cfg)
    workspace_root = _workspace_root(repo_root, cfg)
    docker = _docker_cfg(cfg)

    voices = _installed_voices(cfg)

    probe = _docker_run(
        cfg,
        argv=[
            "bash",
            "-lc",
            "command -v yt-dlp || true; command -v ffmpeg || true; command -v whisper || true; command -v whisper-cli || true; command -v piper || true; "
            "ls -1 /opt/picobot/models/piper 2>/dev/null || true; "
            "ls -1 /opt/picobot/models/whisper 2>/dev/null || true",
        ],
        config_path=resolved_cfg,
    )

    return {
        "config_path": str(resolved_cfg),
        "repo_root": str(repo_root),
        "workspace_root": str(workspace_root),
        "docker": docker,
        "voices_requested": voices,
        "custom_voice_urls": _custom_voice_urls(cfg),
        "runtime_probe": {
            "returncode": probe.returncode,
            "stdout": probe.stdout,
            "stderr": probe.stderr,
        },
    }


def bootstrap_tools(config_path: str | None = None) -> dict[str, Any]:
    resolved_cfg = resolve_config_path(config_path)
    cfg = _load_json(resolved_cfg)
    voices = ",".join(_installed_voices(cfg))
    custom_voice_urls = json.dumps(_custom_voice_urls(cfg), ensure_ascii=False)

    result = _docker_run(
        cfg,
        argv=["bash", "-lc", "command -v picobot-runtime-bootstrap >/dev/null 2>&1 && picobot-runtime-bootstrap"],
        extra_env={
            "PICO_BOOTSTRAP_TOOLS": "1",
            "PICO_PIPER_VOICES": voices,
            "PICO_PIPER_CUSTOM_VOICE_URLS": custom_voice_urls,
        },
        config_path=resolved_cfg,
    )

    return {
        "config_path": str(resolved_cfg),
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "voices_requested": _installed_voices(cfg),
        "custom_voice_urls": _custom_voice_urls(cfg),
        "ok": result.returncode == 0,
    }


def tool_doctor(config_path: str | None = None) -> dict[str, Any]:
    resolved_cfg = resolve_config_path(config_path)
    cfg = _load_json(resolved_cfg)

    checks = []

    bootstrap = _docker_run(
        cfg,
        argv=["bash", "-lc", "command -v picobot-runtime-bootstrap"],
        config_path=resolved_cfg,
    )
    checks.append({
        "name": "runtime_bootstrap_command",
        "ok": bootstrap.returncode == 0,
        "stdout": bootstrap.stdout,
        "stderr": bootstrap.stderr,
    })

    binaries = _docker_run(
        cfg,
        argv=["bash", "-lc", "command -v yt-dlp && command -v ffmpeg && command -v whisper && command -v whisper-cli && command -v piper"],
        config_path=resolved_cfg,
    )
    checks.append({
        "name": "runtime_binaries",
        "ok": binaries.returncode == 0,
        "stdout": binaries.stdout,
        "stderr": binaries.stderr,
    })

    piper_models = _docker_run(
        cfg,
        argv=["bash", "-lc", "test -d /opt/picobot/models/piper && ls -1 /opt/picobot/models/piper"],
        config_path=resolved_cfg,
    )
    checks.append({
        "name": "piper_models_dir",
        "ok": piper_models.returncode == 0,
        "stdout": piper_models.stdout,
        "stderr": piper_models.stderr,
    })

    whisper_model = _docker_run(
        cfg,
        argv=["bash", "-lc", "test -f /opt/picobot/models/whisper/ggml-small.bin"],
        config_path=resolved_cfg,
    )
    checks.append({
        "name": "whisper_model",
        "ok": whisper_model.returncode == 0,
        "stdout": whisper_model.stdout,
        "stderr": whisper_model.stderr,
    })

    ok = all(bool(item["ok"]) for item in checks)

    return {
        "config_path": str(resolved_cfg),
        "ok": ok,
        "checks": checks,
    }


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=None)
    parser.add_argument("action", choices=["snapshot", "bootstrap", "doctor"])
    args = parser.parse_args()

    if args.action == "snapshot":
        print(json.dumps(tool_snapshot(args.config), ensure_ascii=False, indent=2))
        return 0

    if args.action == "bootstrap":
        out = bootstrap_tools(args.config)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1

    out = tool_doctor(args.config)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
