from pathlib import Path

import pytest

from picobot.agent.application import Orchestrator
from picobot.config.schema import Config
from picobot.providers.types import ChatResponse
from picobot.routing.router_policy import RouterPolicy
from picobot.routing.schemas import RouteCandidate, RouteRecord, SessionRouteContext
from picobot.session.manager import SessionManager
from picobot.ui import handle_local_command


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=512, temperature=0.1):
        return ChatResponse(content="Ciao! Come posso aiutarti oggi?", tool_calls=[])


def _candidate(*, name: str, kind: str = "workflow", score: float = 0.8) -> RouteCandidate:
    return RouteCandidate(
        record=RouteRecord(
            id=f"{kind}:{name}",
            kind=kind,
            name=name,
            title=name,
            description=name,
        ),
        vector_score=score,
        lexical_score=score,
        rerank_score=0.0,
        final_score=score,
        reason="test",
    )


@pytest.mark.asyncio
async def test_orchestrator_injected_provider_is_honored(tmp_path: Path):
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
    assert "Ciao" in result.content


def test_cli_passthrough_unknown_runtime_slash_command(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = Config(workspace=str(workspace))

    result = handle_local_command(
        raw_text="/fetch https://example.com",
        cfg=cfg,
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.text is None
    assert result.bus_text == "/fetch https://example.com"


def test_cli_route_debug_is_local(tmp_path: Path):
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    cfg = Config(workspace=str(workspace))

    result = handle_local_command(
        raw_text="/route ciao",
        cfg=cfg,
        workspace=workspace,
        session_id="test",
    )

    assert result.handled is True
    assert result.bus_text is None
    assert result.text is not None
    assert '"name"' in result.text


def test_active_kb_generic_question_routes_to_kb_query_when_confident():
    policy = RouterPolicy()
    ctx = SessionRouteContext(kb_name="demo", kb_enabled=True, has_kb=True, input_lang="it")

    decision = policy.decide(
        user_text="Qual è l'architettura del sistema?",
        candidates=[
            _candidate(name="kb_query", score=0.77),
            _candidate(name="chat", score=0.60),
        ],
        ctx=ctx,
    )

    assert decision.name == "kb_query"
    assert decision.action == "workflow"
    assert "active kb question" in decision.reason


def test_active_kb_generic_question_falls_back_when_probe_is_weak():
    policy = RouterPolicy()
    ctx = SessionRouteContext(kb_name="demo", kb_enabled=True, has_kb=True, input_lang="it")

    decision = policy.decide(
        user_text="Qual è l'architettura del sistema?",
        candidates=[
            _candidate(name="kb_query", score=0.31),
            _candidate(name="chat", score=0.40),
        ],
        ctx=ctx,
    )

    assert decision.name == "chat"
