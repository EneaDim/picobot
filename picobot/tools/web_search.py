from __future__ import annotations

from pydantic import BaseModel, Field

from picobot.services.search_backend import WebSearchUnavailableError
from picobot.services.web_search_service import WebSearchService
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class WebSearchArgs(BaseModel):
    query: str = Field(..., min_length=1)
    count: int = Field(default=5, ge=1, le=10)
    language: str = Field(default="auto")


def make_web_search_tool(cfg, workspace) -> ToolSpec:
    _ = workspace
    service = WebSearchService(cfg)

    async def _handler(args: WebSearchArgs) -> dict:
        try:
            items = service.search_general(
                query=args.query,
                count=args.count,
                language=args.language,
            )
        except WebSearchUnavailableError as e:
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
        description="Search the web through the configured local backend.",
        schema=WebSearchArgs,
        handler=_handler,
    )
