from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.terminal_tool import TerminalToolBase


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1)
    count: int = Field(default=5, ge=1, le=10)


@dataclass(frozen=True)
class _Cfg:
    enabled: bool
    searxng_url: str
    timeout_s: float
    max_results: int


def _read_cfg(cfg) -> _Cfg:
    web = getattr(cfg, "web", None)
    enabled = bool(getattr(web, "enabled", False)) if web else False
    searxng_url = (getattr(web, "searxng_url", "") if web else "") or "http://localhost:8080"
    timeout_s = float(getattr(web, "timeout_s", 10.0) if web else 10.0)
    max_results = int(getattr(web, "max_results", 5) if web else 5)
    return _Cfg(enabled=enabled, searxng_url=searxng_url.rstrip("/"), timeout_s=timeout_s, max_results=max_results)


def make_web_search_tool(cfg) -> ToolSpec:
    c = _read_cfg(cfg)
    runner = TerminalToolBase(allowed_bins=["python"], timeout_s=30, max_output_bytes=250_000)

    async def _handler(args: WebSearchArgs) -> dict:
        if not c.enabled:
            return tool_error("web search disabled (web.enabled=false)")

        q = (args.query or "").strip()
        n = min(max(int(args.count or c.max_results), 1), 10)
        n = min(n, int(c.max_results or 5))

        payload = json.dumps(
            {"searxng_url": c.searxng_url, "query": q, "count": n, "timeout_s": float(c.timeout_s)},
            ensure_ascii=False,
        )
        res = runner.run_cmd(
            ["python", "-I", "-c", _PY_SEARXNG],
            prefix="[web_search]",
            timeout_s=int(c.timeout_s) + 2,
            input_bytes=payload.encode("utf-8"),
        )
        if res.returncode != 0:
            return tool_error(f"web_search error: {(res.stderr or '')[:200]}")

        data = json.loads(res.stdout or "{}")
        if not data.get("ok"):
            return tool_error(data.get("error") or "web_search failed")

        return tool_ok(
            {
                "query": q,
                "results": data.get("results") or [],
                "elapsed_s": data.get("elapsed_s"),
            },
            language=None,
        )

    return ToolSpec(
        name="web_search",
        description="Search the web via local SearXNG, executed inside sandbox runner.",
        schema=WebSearchArgs,
        handler=_handler,
    )


_PY_SEARXNG = r'''
import sys, json, time, urllib.parse, urllib.request, urllib.error

args = json.loads(sys.stdin.read() or "{}")
base = (args.get("searxng_url") or "http://localhost:8080").rstrip("/")
q = (args.get("query") or "").strip()
count = int(args.get("count") or 5)
timeout_s = float(args.get("timeout_s") or 10.0)

params = {"q": q, "format": "json"}
url = f"{base}/search?{urllib.parse.urlencode(params)}"
req = urllib.request.Request(url, headers={"User-Agent": "picobot/1.0", "Accept":"application/json"}, method="GET")

t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=timeout_s) as r:
        raw = r.read()
    data = json.loads(raw.decode("utf-8", errors="replace"))
    results = data.get("results") or []
    out = []
    for item in results[:count]:
        out.append({
            "title": (item.get("title") or "").strip(),
            "url": (item.get("url") or "").strip(),
            "snippet": (item.get("content") or item.get("snippet") or "").strip(),
            "engine": (item.get("engine") or "").strip(),
        })
    print(json.dumps({"ok": True, "results": out, "elapsed_s": round(time.time()-t0, 3)}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False))
'''
