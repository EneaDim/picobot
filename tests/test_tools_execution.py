from __future__ import annotations

from pathlib import Path
import pytest

from picobot.config.schema import Config
from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(content="SUMMARY_OK", tool_calls=[])


@pytest.mark.asyncio
async def test_tool_path_yt_summary_runs_without_network(tmp_path: Path, monkeypatch):
    cfg = Config(workspace=str(tmp_path))
    cfg.retrieval.enabled = True

    # stub config.tools.ytdlp_bin if needed
    if not hasattr(cfg, "tools"):
        # Config in your project likely has it; if not, this test will be adjusted later
        pass

    sm = SessionManager(tmp_path)
    s = sm.get("s1")

    orch = Orchestrator(cfg, DummyProvider(), tmp_path)

    # monkeypatch transcript tool handler to avoid calling yt-dlp
    from picobot.tools import youtube as yt_mod

    async def fake_transcript(args):
        return {"url": args.url, "lang": args.lang, "transcript": "hello world transcript"}

    # Replace factory to return a tool whose handler is fake
    real_make = yt_mod.make_yt_transcript_tool

    def patched_make(binpath: str):
        tool = real_make(binpath)
        object.__setattr__(tool, "handler", fake_transcript)  # dataclass frozen -> but ToolSpec isn't frozen; still safe
        return tool

    monkeypatch.setattr(yt_mod, "make_yt_transcript_tool", patched_make)

    r = await orch.one_turn(s, "summarize this youtube video: https://www.youtube.com/watch?v=abc", status=None)
    assert r.action == "tool"
    assert "SUMMARY_OK" in r.content


@pytest.mark.asyncio
async def test_tool_path_kb_ingest_validates_pdf_path(tmp_path: Path):
    cfg = Config(workspace=str(tmp_path))
    sm = SessionManager(tmp_path)
    s = sm.get("s1")
    orch = Orchestrator(cfg, DummyProvider(), tmp_path)

    r = await orch.one_turn(s, "ingest pdf ./does-not-exist.pdf", status=None)
    assert r.action == "tool"
    assert "Tool error" in r.content or "Missing" in r.content
