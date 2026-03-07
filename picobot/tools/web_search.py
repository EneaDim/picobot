from __future__ import annotations

# Tool web_search basato su SearXNG gestito automaticamente.
from pydantic import BaseModel, Field

from picobot.services.searxng import SearxngManager, SearxngUnavailableError
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1)
    count: int = Field(default=5, ge=1, le=10)
    language: str = Field(default="auto")


def make_web_search_tool(cfg, workspace) -> ToolSpec:
    """
    Tool di ricerca web via SearXNG locale.

    workspace è mantenuto nella signature per compatibilità col resto del progetto.
    """
    manager = SearxngManager(cfg)

    async def _handler(args: WebSearchArgs) -> dict:
        try:
            items = manager.search(
                query=args.query,
                count=args.count,
                categories="general",
                language=args.language,
            )
        except SearxngUnavailableError as e:
            return tool_error(str(e))
        except Exception as e:
            return tool_error(f"web search failed: {e}")

        data_items = [
            {
                "title": item.title,
                "url": item.url,
                "description": item.description,
                "source": item.source,
            }
            for item in items
        ]

        return tool_ok(
            {
                "query": args.query,
                "count": len(data_items),
                "items": data_items,
                "results": data_items,
            },
            language=args.language,
        )

    return ToolSpec(
        name="web_search",
        description="Web search through locally managed SearXNG.",
        schema=WebSearchArgs,
        handler=_handler,
    )
