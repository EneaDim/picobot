from __future__ import annotations

from dataclasses import dataclass

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


def make_news_digest_tool(cfg) -> ToolSpec:
    """
    Composite tool:
      1) web_search (via sandbox runner)
      2) sandbox_web fetch each URL (via sandbox runner + caps/whitelist)
      Returns structured bundle for LLM summarization (or deterministic summarizer).
    """
    c = _read_cfg(cfg)
    web_search = make_web_search_tool(cfg)
    sandbox_web = make_sandbox_web_tool(cfg)

    async def _handler(args: NewsDigestArgs) -> dict:
        if not c.enabled:
            return tool_error("news_digest disabled (web.enabled=false)")

        q = (args.query or "").strip()
        n = min(max(int(args.count or 6), 1), 8)
        fetch_chars = int(args.fetch_chars or 12000)

        sr = await web_search.handler(WebSearchArgs(query=q, count=n))
        if not sr.get("ok"):
            return tool_error(sr.get("error") or "web_search failed")

        results = (sr.get("data") or {}).get("results") or []
        if not results:
            return tool_ok({"query": q, "items": []}, language=detect_language(q, default=getattr(cfg, "default_language", "it")))

        items = []
        for r in results[:n]:
            url = (r.get("url") or "").strip()
            title = (r.get("title") or "").strip()
            snippet = (r.get("snippet") or "").strip()
            if not url:
                continue

            fr = await sandbox_web.handler(SandboxWebArgs(url=url, max_chars=fetch_chars))
            if not fr.get("ok"):
                items.append({"title": title, "url": url, "snippet": snippet, "ok": False, "error": fr.get("error") or "fetch failed"})
                continue

            data = fr.get("data") or {}
            text = (data.get("text") or "").strip()
            items.append(
                {
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "ok": True,
                    "text": text,
                    "length": int(data.get("length") or len(text)),
                    "truncated": bool(data.get("truncated") or False),
                }
            )

        lang = detect_language(q, default=getattr(cfg, "default_language", "it"))
        return tool_ok({"query": q, "items": items}, language=lang)

    return ToolSpec(
        name="news_digest",
        description="Composite: web_search + sandbox_web fetch top results. Returns structured texts for summarization.",
        schema=NewsDigestArgs,
        handler=_handler,
    )
