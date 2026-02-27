from pathlib import Path

from picobot.agent.router import deterministic_route


def test_router_kb_signal(tmp_path: Path):
    state = tmp_path / "state.json"
    d = deterministic_route("check this pdf", state)
    assert d.action == "kb_query"


def test_router_followup_keeps_kb(tmp_path: Path):
    state = tmp_path / "state.json"
    deterministic_route("kb question", state)
    d = deterministic_route("more detail", state)
    assert d.action == "kb_query"


def test_router_default_chat(tmp_path: Path):
    state = tmp_path / "state.json"
    d = deterministic_route("hello", state)
    assert d.action == "chat"
