from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field

from picobot.services.searxng import search_in_container
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1)
    count: int = Field(default=5, ge=1, le=10)


@dataclass(frozen=True)
class _Cfg:
    enabled: bool
    max_results: int


def _read_cfg(cfg) -> _Cfg:
    web = getattr(cfg, "web", None)
    enabled = bool(getattr(web, "enabled", False)) if web else False
    max_results = int(getattr(web, "max_results", 5) if web else 5)
    return _Cfg(enabled=enabled, max_results=max_results)


def make_web_search_tool(cfg, workspace) -> ToolSpec:
    c = _read_cfg(cfg)

    async def _handler(args: WebSearchArgs) -> dict:
        if not c.enabled:
            return tool_error("web search disabled (web.enabled=false)")

        q = (args.query or "").strip()
        n = min(max(int(args.count or c.max_results), 1), 10)
        n = min(n, int(c.max_results or 5))

        data = search_in_container(cfg, workspace, query=q, count=n)
        if not data.get("ok"):
            return tool_error(data.get("error") or "web_search failed")

        return tool_ok(
            {
                "query": q,
                "results": data.get("results") or [],
            },
            language=None,
        )

    return ToolSpec(
        name="web_search",
        description="Search the web via SearXNG in Docker; query is executed inside the container.",
        schema=WebSearchArgs,
        handler=_handler,
    )
