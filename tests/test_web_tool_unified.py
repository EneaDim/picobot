from types import SimpleNamespace

import pytest

from picobot.tools.web import make_web_tool


class DummySearchItem:
    def __init__(self, title: str, url: str, description: str, source: str) -> None:
        self.title = title
        self.url = url
        self.description = description
        self.source = source


class DummySearchService:
    def search_general(self, query: str, count: int, language: str):
        assert query == "latest ai chips"
        assert count == 3
        assert language == "en"
        return [
            DummySearchItem(
                title="AI chips roundup",
                url="https://example.com/chips",
                description="Latest chip news",
                source="example",
            )
        ]


@pytest.mark.asyncio
async def test_web_tool_search_mode(monkeypatch):
    import picobot.tools.web as web_mod

    monkeypatch.setattr(web_mod, "WebSearchService", lambda cfg: DummySearchService())

    cfg = SimpleNamespace()
    tool = make_web_tool(cfg)

    result = await tool.handler(
        {
            "operation": "search",
            "query": "latest ai chips",
            "count": 3,
            "language": "en",
        }
    )

    assert result["ok"] is True
    data = result["data"]
    assert data["operation"] == "search"
    assert len(data["items"]) == 1
    assert data["items"][0]["title"] == "AI chips roundup"


@pytest.mark.asyncio
async def test_web_tool_fetch_mode_requires_url():
    cfg = SimpleNamespace()
    tool = make_web_tool(cfg)

    result = await tool.handler({"operation": "fetch"})
    assert result["ok"] is False
    assert "url is required" in result["error"]
