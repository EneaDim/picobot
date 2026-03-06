from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

from picobot.sandbox.docker_runner import DockerRunner


def _get(cfg: Any, path: str, default: Any = None) -> Any:
    cur = cfg
    for part in path.split("."):
        if cur is None:
            return default
        cur = getattr(cur, part, None)
    return default if cur is None else cur


def _sandbox_root(workspace: Path) -> Path:
    return (workspace / "sandbox_runs").resolve()


def _repo_root_from_workspace(workspace: Path) -> Path:
    return Path(workspace).resolve()


def _compose_file(cfg: Any, workspace: Path) -> Path:
    override = _get(cfg, "web.searxng_compose_file", None)
    if override:
        return Path(str(override)).expanduser().resolve()
    return (_repo_root_from_workspace(workspace) / "searxng" / "docker-compose.yml").resolve()


def _container_name(cfg: Any) -> str:
    return str(_get(cfg, "web.searxng_container_name", "picobot-searxng"))


def _docker_runner(workspace: Path) -> DockerRunner:
    return DockerRunner(
        sandbox_root=_sandbox_root(workspace),
        timeout_s=120,
        max_output_bytes=400_000,
        allowed_bins=("docker",),
    )


def _docker_compose_cmd(compose_file: Path) -> list[str]:
    return ["docker", "compose", "-f", str(compose_file)]


def is_running(cfg: Any, workspace: Path) -> bool:
    runner = _docker_runner(workspace)
    name = _container_name(cfg)
    r = runner.run(["docker", "ps", "--filter", f"name={name}", "--format", "{{.Names}}"])
    if not r.ok:
        return False
    names = [x.strip() for x in (r.stdout or "").splitlines() if x.strip()]
    return name in names


def ensure_running(cfg: Any, workspace: Path) -> None:
    enabled = bool(_get(cfg, "web.enabled", True))
    if not enabled:
        return

    if is_running(cfg, workspace):
        return

    compose_file = _compose_file(cfg, workspace)
    if not compose_file.exists():
        print(f"[searxng] compose file not found: {compose_file}", file=sys.stderr)
        return

    runner = _docker_runner(workspace)
    cmd = _docker_compose_cmd(compose_file) + ["up", "-d"]
    r = runner.run(cmd, cwd=compose_file.parent)
    if not r.ok:
        print("[searxng] docker compose up -d failed", file=sys.stderr)
        if r.stderr:
            print(r.stderr, file=sys.stderr)
        return

    for _ in range(12):
        if is_running(cfg, workspace):
            return
        time.sleep(0.5)


def search_in_container(cfg: Any, workspace: Path, *, query: str, count: int) -> dict:
    ensure_running(cfg, workspace)

    if not is_running(cfg, workspace):
        return {"ok": False, "error": "searxng container not running"}

    container = _container_name(cfg)
    limit = max(1, min(int(count or 5), 10))

    py = r'''
import json, sys, urllib.parse, urllib.request, re, html as html_lib

args = json.loads(sys.stdin.read() or "{}")
q = (args.get("query") or "").strip()
count = int(args.get("count") or 5)

url = "http://127.0.0.1:8080/search?" + urllib.parse.urlencode({"q": q})
headers = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Referer": "http://127.0.0.1:8080/",
    "X-Forwarded-For": "127.0.0.1",
    "X-Real-IP": "127.0.0.1",
}
req = urllib.request.Request(url, headers=headers, method="GET")

def clean(s):
    s = html_lib.unescape(s or "")
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

try:
    with urllib.request.urlopen(req, timeout=10.0) as r:
        raw = r.read().decode("utf-8", errors="replace")

    blocks = re.findall(r'(<article.*?</article>)', raw, flags=re.S | re.I)
    if not blocks:
        blocks = re.findall(r'(<div[^>]+class="[^"]*result[^"]*".*?</div>\s*</div>?)', raw, flags=re.S | re.I)

    out = []
    for b in blocks:
        m_link = re.search(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', b, flags=re.S | re.I)
        if not m_link:
            continue
        href = html_lib.unescape(m_link.group(1).strip())
        title = clean(m_link.group(2))

        snippet = ""
        m_snip = re.search(r'<p[^>]*class="[^"]*(?:content|url|snippet)[^"]*"[^>]*>(.*?)</p>', b, flags=re.S | re.I)
        if m_snip:
            snippet = clean(m_snip.group(1))
        else:
            txt = clean(b)
            snippet = txt[:240]

        if title and href:
            out.append({
                "title": title,
                "url": href,
                "snippet": snippet,
                "engine": "",
            })
        if len(out) >= count:
            break

    print(json.dumps({"ok": True, "results": out}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
'''
    payload = json.dumps({"query": query, "count": limit}, ensure_ascii=False).encode("utf-8")
    runner = _docker_runner(workspace)
    r = runner.run(
        ["docker", "exec", "-i", container, "python", "-c", py],
        input_bytes=payload,
    )
    if not r.ok:
        return {"ok": False, "error": (r.stderr or "docker exec failed").strip()}

    try:
        data = json.loads(r.stdout or "{}")
    except Exception:
        return {"ok": False, "error": "invalid json from searxng container"}

    return data if isinstance(data, dict) else {"ok": False, "error": "invalid result type"}


def ensure_searxng_running(cfg: Any, workspace: Path) -> None:
    ensure_running(cfg, workspace)
