from pathlib import Path

import pytest

from picobot.agent.orchestrator import Orchestrator
from picobot.config.schema import Config
from picobot.providers.types import ChatResponse
from picobot.session.manager import SessionManager


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=512, temperature=0.1):
        return ChatResponse(content="ok", tool_calls=[])


@pytest.mark.asyncio
async def test_news_digest_render_output(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    cfg = Config(workspace=str(workspace))
    sm = SessionManager(workspace)
    session = sm.get("news-test")

    orch = Orchestrator(cfg, DummyProvider(), workspace)

    async def fake_run_tool(tool_name: str, args: dict):
        assert tool_name == "news_digest"
        return {
            "ok": True,
            "data": {
                "items": [
                    {
                        "title": "AI Act updates in Europe",
                        "url": "https://example.com/ai-act",
                        "description": "A short summary of the latest European AI policy updates.",
                        "source": "example",
                    },
                    {
                        "title": "Open source local models improve",
                        "url": "https://example.com/local-models",
                        "description": "Local-first AI tooling is improving rapidly.",
                        "source": "example",
                    },
                ]
            },
        }

    orch._run_tool = fake_run_tool  # type: ignore[attr-defined]

    result = await orch._workflow_news_digest(
        user_text="/news intelligenza artificiale",
        lang="it",
        status=None,
    )

    assert result.action == "workflow"
    assert result.reason == "news_digest"
    assert "News digest" in result.content
    assert "AI Act updates in Europe" in result.content
    assert "https://example.com/ai-act" in result.content


@pytest.mark.asyncio
async def test_news_digest_empty_items(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    cfg = Config(workspace=str(workspace))
    sm = SessionManager(workspace)
    session = sm.get("news-empty")

    orch = Orchestrator(cfg, DummyProvider(), workspace)

    async def fake_run_tool(tool_name: str, args: dict):
        assert tool_name == "news_digest"
        return {"ok": True, "data": {"items": []}}

    orch._run_tool = fake_run_tool  # type: ignore[attr-defined]

    result = await orch._workflow_news_digest(
        user_text="/news intelligenza artificiale",
        lang="it",
        status=None,
    )

    assert result.action == "workflow"
    assert result.reason == "news no items"
