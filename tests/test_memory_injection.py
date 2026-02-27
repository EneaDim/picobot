from pathlib import Path
import pytest
from tests.conftest import dbg

from picobot.config.schema import Config
from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse


class AssertingProvider:
    def __init__(self) -> None:
        self.last_messages = None

    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        self.last_messages = messages
        return ChatResponse(content="ok", tool_calls=[])


@pytest.mark.asyncio
async def test_memory_is_injected_into_prompt(tmp_path: Path):
    cfg = Config(workspace=str(tmp_path))
    sm = SessionManager(tmp_path)
    s = sm.get("s1")
    provider = AssertingProvider()
    orch = Orchestrator(cfg, provider, tmp_path)

    # deterministic write (general remember)
    await orch.one_turn(s, "remember paprika", status=None)
    assert "paprika" in s.memory_file.read_text(encoding="utf-8").lower()

    # now a normal chat turn should inject memory
    await orch.one_turn(s, "what did i ask you to remember?", status=None)
    assert provider.last_messages is not None
    dbg('last_messages=', provider.last_messages)
    joined = "\n".join(m.get("content","") for m in provider.last_messages)
    assert "SESSION MEMORY" in joined
    assert "paprika" in joined.lower()
