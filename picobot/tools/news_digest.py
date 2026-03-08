from __future__ import annotations

from pydantic import BaseModel, Field

from picobot.services.search_backend import WebSearchUnavailableError
from picobot.services.web_search_service import WebSearchService
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class NewsDigestArgs(BaseModel):
    query: str = Field(..., min_length=1)
    count: int = Field(default=6, ge=1, le=12)
    fetch_chars: int = Field(default=12000, ge=1000, le=50000)
    language: str = Field(default="auto")


def make_news_digest_tool(cfg, workspace) -> ToolSpec:
    _ = workspace
    service = WebSearchService(cfg)

    async def _handler(args: NewsDigestArgs) -> dict:
        try:
            items = service.search_news(
                query=args.query,
                count=args.count,
                language=args.language,
            )
        except WebSearchUnavailableError as e:
            return tool_error(str(e))
        except Exception as e:
            return tool_error(f"news digest failed: {e}")

        digest_items = [
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
                "count": len(digest_items),
                "items": digest_items,
            },
            language=args.language,
        )

    return ToolSpec(
        name="news_digest",
        description="Current-news digest through the configured local web-search backend.",
        schema=NewsDigestArgs,
        handler=_handler,
    )
