from pathlib import Path

import pytest

from picobot.channels.telegram import TelegramSessionMap
from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(content="ok", tool_calls=[])


@pytest.mark.asyncio
async def test_telegram_session_map_roundtrip(tmp_path: Path):
    m = TelegramSessionMap(tmp_path / "session_map.json")
    assert m.get_session_for_chat("123") == "tg-123"
    sid = m.set_session_for_chat("123", "My Session!!")
    assert sid == "My-Session"
    assert m.get_session_for_chat("123") == "My-Session"


@pytest.mark.asyncio
async def test_orchestrator_chat_turn(tmp_path: Path):
    sm = SessionManager(tmp_path)
    s = sm.get("tg-1")
    from picobot.config.schema import Config
    cfg = Config(workspace=str(tmp_path))
    cfg.retrieval.enabled = False
    orch = Orchestrator(cfg, DummyProvider(), tmp_path)
    res = await orch.one_turn(s, "hello", status=None)
    assert res.content == "ok"
    assert res.action == "chat"
