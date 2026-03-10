from pathlib import Path

import pytest

from picobot.agent.application import Orchestrator
from picobot.config.schema import Config
from picobot.providers.types import ChatResponse
from picobot.session.manager import SessionManager


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=512, temperature=0.1):
        return ChatResponse(content="Ciao! Come posso aiutarti oggi?", tool_calls=[])


@pytest.mark.asyncio
async def test_orchestrator_chat_one_turn(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    cfg = Config(workspace=str(workspace))
    sm = SessionManager(workspace)
    session = sm.get("chat-test")

    orch = Orchestrator(cfg, DummyProvider(), workspace)

    result = await orch.one_turn(
        session=session,
        user_text="ciao",
        status=None,
    )

    assert result.action == "chat"
    assert result.content
    assert "Ciao" in result.content or "aiut" in result.content
