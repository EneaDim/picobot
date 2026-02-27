from pathlib import Path

from picobot.agent.router import deterministic_route


def test_router_youtube_goes_to_tool(tmp_path: Path):
    st = tmp_path / "state.json"
    r = deterministic_route("summarize this youtube video: https://www.youtube.com/watch?v=abc", st)
    assert r.action == "tool"


def test_router_pdf_ingest_goes_to_tool(tmp_path: Path):
    st = tmp_path / "state.json"
    r = deterministic_route("ingest pdf ./docs/a.pdf", st)
    assert r.action == "tool"
