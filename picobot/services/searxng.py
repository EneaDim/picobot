from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from picobot.sandbox.runner import SandboxRunner


def _get(cfg: Any, path: str, default: Any = None) -> Any:
    cur = cfg
    for part in path.split("."):
        if cur is None:
            return default
        cur = getattr(cur, part, None)
    return default if cur is None else cur


def _probe_searxng(searxng_url: str, timeout_s: float = 1.5) -> tuple[bool, str]:
    base = (searxng_url or "").rstrip("/")
    if not base:
        return False, "missing searxng_url"
    params = {"q": "test", "format": "json"}
    url = f"{base}/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "picobot/1.0", "Accept": "application/json"}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read()
        _ = json.loads(raw.decode("utf-8", errors="replace"))
        return True, "ok"
    except Exception as e:
        return False, str(e)


def _find_compose_file(cfg: Any, workspace: Path) -> Path | None:
    # config override first
    p = _get(cfg, "web.searxng_compose_file", None)
    if p:
        fp = Path(str(p)).expanduser()
        if fp.exists():
            return fp.resolve()

    # repo-local default (recommended)
    repo_default = Path("searxng/docker-compose.yml")
    if repo_default.exists():
        return repo_default.resolve()

    # workspace fallbacks
    candidates = [
        workspace / "searxng" / "docker-compose.yml",
        workspace / "searxng" / "docker-compose.yaml",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()
    return None


def _env_file_for(compose: Path) -> Path | None:
    # prefer sibling .env
    env = compose.parent / ".env"
    if env.exists():
        return env.resolve()
    return None


def ensure_searxng_running(cfg: Any, workspace: Path) -> None:
    """
    Best-effort autostart.
    Runs docker compose inside sandbox runner (docker is a CLI tool).
    """
    enabled = bool(_get(cfg, "web.enabled", True))
    if not enabled:
        return

    autostart = _get(cfg, "web.searxng_autostart", True)
    if autostart is False:
        return

    searxng_url = str(_get(cfg, "web.searxng_url", "http://localhost:8080"))
    ok, _ = _probe_searxng(searxng_url, timeout_s=1.2)
    if ok:
        return

    compose = _find_compose_file(cfg, workspace)
    if not compose:
        print("[searxng] autostart enabled but compose file not found. Create searxng/docker-compose.yml or set web.searxng_compose_file.", file=sys.stderr)
        return

    try:
        runner = SandboxRunner(
            allowed_bins=["docker"],
            sandbox_root=str(workspace / "sandbox_runs"),
            timeout_s=90,
            max_output_bytes=400_000,
        )

        cmd = ["docker", "compose", "-f", str(compose)]
        env_file = _env_file_for(compose)
        if env_file:
            cmd += ["--env-file", str(env_file)]
        cmd += ["up", "-d"]

        r = runner.run(cmd)
        res = r.to_exec_result()

        if res.returncode != 0:
            print("[searxng] docker compose up -d failed", file=sys.stderr)
            if res.stderr:
                print(res.stderr, file=sys.stderr)
            return

        # small wait then probe again
        time.sleep(1.0)
        ok2, msg2 = _probe_searxng(searxng_url, timeout_s=2.5)
        if not ok2:
            print(f"[searxng] started but probe failed: {msg2}", file=sys.stderr)

    except Exception as e:
        print(f"[searxng] autostart error: {e}", file=sys.stderr)
