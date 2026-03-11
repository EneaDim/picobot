from pathlib import Path

import pytest

from picobot.agent.application import Orchestrator
from picobot.config.schema import Config
from picobot.providers.types import ChatResponse
from picobot.session.manager import SessionManager


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=512, temperature=0.1):
        return ChatResponse(content="ok", tool_calls=[])


@pytest.mark.asyncio
async def test_turn_result_exposes_audit_metadata(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    cfg = Config(workspace=str(workspace))
    sm = SessionManager(workspace)
    session = sm.get("audit-test")

    orch = Orchestrator(cfg, DummyProvider(), workspace)
    result = await orch.one_turn(
        session=session,
        user_text="ciao",
        status=None,
    )

    assert result.route_name == "chat"
    assert result.route_action == "workflow"
    assert result.route_source is not None
    assert isinstance(result.audit, dict)
    assert result.audit.get("route_name") == "chat"
    assert "route_source" in result.audit


@pytest.mark.asyncio
async def test_chat_result_contains_provider_name(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    cfg = Config(workspace=str(workspace))
    sm = SessionManager(workspace)
    session = sm.get("provider-audit")

    orch = Orchestrator(cfg, DummyProvider(), workspace)
    result = await orch.one_turn(
        session=session,
        user_text="ciao",
        status=None,
    )

    assert result.provider_name in {"dummy", "dummyprovider"}
