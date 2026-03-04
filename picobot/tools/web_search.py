from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok


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


def _http_get_json(url: str, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "picobot/1.0",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as r:
            raw = r.read()
        return json.loads(raw.decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:  # type: ignore[attr-defined]
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")[:200]
        except Exception:
            body = ""
        raise RuntimeError(f"HTTP {getattr(e, 'code', '?')} {getattr(e, 'reason', '')}: {body}") from e


def make_web_search_tool(cfg) -> ToolSpec:
    c = _read_cfg(cfg)

    async def _handler(args: WebSearchArgs) -> dict:
        if not c.enabled:
            return tool_error("web search disabled (web.enabled=false)")

        q = (args.query or "").strip()
        n = min(max(int(args.count or c.max_results), 1), 10)
        n = min(n, int(c.max_results or 5))

        # SearXNG JSON endpoint: /search?q=...&format=json
        params = {"q": q, "format": "json"}
        url = f"{c.searxng_url}/search?{urllib.parse.urlencode(params)}"

        t0 = time.time()
        try:
            data = _http_get_json(url, timeout_s=c.timeout_s)
            results = data.get("results") or []
            out = []
            for item in results[:n]:
                out.append(
                    {
                        "title": (item.get("title") or "").strip(),
                        "url": (item.get("url") or "").strip(),
                        "snippet": (item.get("content") or item.get("snippet") or "").strip(),
                        "engine": (item.get("engine") or "").strip(),
                    }
                )
            return tool_ok(
                {
                    "query": q,
                    "results": out,
                    "elapsed_s": round(time.time() - t0, 3),
                },
                language=None,
            )
        except Exception as e:
            return tool_error(f"web_search error: {e!r}")

    return ToolSpec(
        name="web_search",
        description="Search the web via a local SearXNG instance. Returns titles/urls/snippets.",
        schema=WebSearchArgs,
        handler=_handler,
    )
