from __future__ import annotations

# Tool news_digest basato su SearXNG gestito automaticamente.
#
# Scelta semplice:
# - usa i risultati news di SearXNG
# - produce items già pronti per l'orchestrator
# - niente fetch pesante delle pagine in questo passaggio
#
# Questo è sufficiente per:
# - rassegna rapida
# - risposta leggibile
# - fallimento chiaro se il servizio web locale non parte

from pydantic import BaseModel, Field

from picobot.services.searxng import SearxngManager, SearxngUnavailableError
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class NewsDigestArgs(BaseModel):
    query: str = Field(..., min_length=1)
    count: int = Field(default=6, ge=1, le=12)
    fetch_chars: int = Field(default=12000, ge=1000, le=50000)
    language: str = Field(default="auto")


def make_news_digest_tool(cfg, workspace) -> ToolSpec:
    """
    Tool di news digest via SearXNG locale.
    """
    manager = SearxngManager(cfg)

    async def _handler(args: NewsDigestArgs) -> dict:
        try:
            items = manager.search(
                query=args.query,
                count=args.count,
                categories="news",
                language=args.language,
            )
        except SearxngUnavailableError as e:
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
        description="Current-news digest through locally managed SearXNG.",
        schema=NewsDigestArgs,
        handler=_handler,
    )
