from pathlib import Path
import pytest

from picobot.config.schema import Config
from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(content="LLM", tool_calls=[])


@pytest.mark.asyncio
async def test_general_memory_recall_key_rest(tmp_path: Path):
    cfg = Config(workspace=str(tmp_path))
    sm = SessionManager(tmp_path)
    s = sm.get("s1")
    orch = Orchestrator(cfg, DummyProvider(), tmp_path)

    r1 = await orch.one_turn(s, "remember keyword paprika, reply only with ok", status=None)
    assert r1.content.strip().lower() == "ok"

    r2 = await orch.one_turn(s, "which is the keyword", status=None)
    # general key/rest heuristic should return the "rest" (paprika)
    assert r2.content.strip().lower() == "paprika"
