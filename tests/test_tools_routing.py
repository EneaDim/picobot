from pathlib import Path

from picobot.agent.router import deterministic_route


def test_router_youtube_goes_to_workflow(tmp_path: Path):
    st = tmp_path / "state.json"
    r = deterministic_route("summarize this youtube video: https://www.youtube.com/watch?v=abc", st)
    assert r.workflow == "youtube_summarizer"


def test_router_pdf_ingest_goes_to_tool_or_workflow(tmp_path: Path):
    """
    Repo: alcune versioni trattano ingest come tool esplicito, altre come workflow.
    Accettiamo entrambi finché resta deterministico.
    """
    st = tmp_path / "state.json"
    r = deterministic_route("ingest pdf ./docs/a.pdf", st)
    assert r.workflow in ("tool", "kb_ingest_pdf", "retrieve_only")
