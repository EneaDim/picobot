from pathlib import Path

import pytest

from picobot.config.schema import Config
from picobot.tools.web_search import make_web_search_tool, WebSearchArgs


@pytest.mark.asyncio
async def test_web_search_uses_container_service(tmp_path: Path, monkeypatch):
    cfg = Config(workspace=str(tmp_path))
    cfg.web.enabled = True
    cfg.web.max_results = 5

    called = {"ok": False}

    def fake_search_in_container(cfg_obj, workspace, *, query: str, count: int):
        called["ok"] = True
        assert str(workspace) == str(tmp_path)
        assert query == "intelligenza artificiale europa"
        assert count == 3
        return {
            "ok": True,
            "results": [
                {
                    "title": "Titolo test",
                    "url": "https://example.com/a",
                    "snippet": "Snippet test",
                    "engine": "",
                }
            ],
        }

    monkeypatch.setattr("picobot.tools.web_search.search_in_container", fake_search_in_container)

    tool = make_web_search_tool(cfg, tmp_path)
    res = await tool.handler(WebSearchArgs(query="intelligenza artificiale europa", count=3))

    assert called["ok"] is True
    assert res["ok"] is True
    data = res["data"]
    assert data["query"] == "intelligenza artificiale europa"
    assert len(data["results"]) == 1
    assert data["results"][0]["url"] == "https://example.com/a"
