from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from picobot.agent.prompts import detect_language
from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.web_search import make_web_search_tool, WebSearchArgs
from picobot.tools.sandbox_web import make_sandbox_web_tool, SandboxWebArgs


class NewsDigestArgs(BaseModel):
    query: str = Field(..., min_length=1)
    count: int = Field(default=6, ge=1, le=8)
    fetch_chars: int = Field(default=12000, ge=1000, le=50000)


@dataclass(frozen=True)
class _Cfg:
    enabled: bool


def _read_cfg(cfg) -> _Cfg:
    web = getattr(cfg, "web", None)
    enabled = bool(getattr(web, "enabled", False)) if web else False
    return _Cfg(enabled=enabled)


def _norm_title(s: str) -> str:
    s = (s or "").lower().strip()
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"\s*[›|»-]\s*", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip(" -|›»")


def _clean_excerpt(text: str, max_chars: int = 900) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t[:max_chars].strip()


def _source_score(url: str) -> int:
    host = (urlparse(url).hostname or "").lower()
    strong = [
        "europa.eu",
        "ec.europa.eu",
        "europarl.europa.eu",
        "reuters.com",
        "ansa.it",
        "apnews.com",
        "bbc.com",
        "bbc.co.uk",
        "ft.com",
        "ilsole24ore.com",
        "rainews.it",
        "sky.it",
        "euronews.com",
    ]
    for i, dom in enumerate(strong[::-1], start=1):
        if host.endswith(dom):
            return 100 + i
    return 10


def make_news_digest_tool(cfg, workspace) -> ToolSpec:
    c = _read_cfg(cfg)
    web_search = make_web_search_tool(cfg, workspace)
    sandbox_web = make_sandbox_web_tool(cfg)

    async def _handler(args: NewsDigestArgs) -> dict:
        if not c.enabled:
            return tool_error("news_digest disabled (web.enabled=false)")

        q = (args.query or "").strip()
        n = min(max(int(args.count or 6), 1), 8)
        fetch_chars = int(args.fetch_chars or 12000)

        sr = await web_search.handler(WebSearchArgs(query=q, count=max(n, 8)))
        if not sr.get("ok"):
            return tool_error(sr.get("error") or "web_search failed")

        results = (sr.get("data") or {}).get("results") or []
        if not results:
            return tool_ok({"query": q, "items": []}, language=detect_language(q, default=getattr(cfg, "default_language", "it")))

        results = sorted(results, key=lambda r: _source_score((r.get("url") or "").strip()), reverse=True)

        items = []
        seen_urls: set[str] = set()
        seen_titles: set[str] = set()

        for r in results:
            if len(items) >= 5:
                break

            url = (r.get("url") or "").strip()
            title = (r.get("title") or "").strip()
            snippet = (r.get("snippet") or "").strip()

            if not url or url in seen_urls:
                continue

            fr = await sandbox_web.handler(SandboxWebArgs(url=url, max_chars=fetch_chars))
            if not fr.get("ok"):
                continue

            data = fr.get("data") or {}
            fetched_title = (data.get("title") or "").strip()
            description = (data.get("description") or "").strip()
            text = _clean_excerpt(data.get("text") or "", max_chars=900)

            final_title = fetched_title or title
            norm_title = _norm_title(final_title)
            if norm_title and norm_title in seen_titles:
                continue

            if len(text) < 120 and len(description) < 40 and len(snippet) < 40:
                continue

            items.append(
                {
                    "title": final_title,
                    "url": url,
                    "snippet": snippet,
                    "description": description,
                    "ok": True,
                    "text": text,
                    "length": int(data.get("length") or len(text)),
                    "truncated": bool(data.get("truncated") or False),
                }
            )

            seen_urls.add(url)
            if norm_title:
                seen_titles.add(norm_title)

        lang = detect_language(q, default=getattr(cfg, "default_language", "it"))
        return tool_ok({"query": q, "items": items}, language=lang)

    return ToolSpec(
        name="news_digest",
        description="Composite: web_search (Docker SearXNG) + sandbox_web fetch top results, ranking and deduplication.",
        schema=NewsDigestArgs,
        handler=_handler,
    )
