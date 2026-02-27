from __future__ import annotations

from pathlib import Path
import pytest

from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.config.schema import Config
from picobot.providers.types import ChatResponse
from picobot.retrieval.store import KBStore


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(content="ANSWER_OK", tool_calls=[])


@pytest.mark.asyncio
async def test_no_index_never_quotes(tmp_path: Path):
    ws = tmp_path
    sm = SessionManager(ws)
    s = sm.get("s1")

    cfg = Config(workspace=str(ws))
    cfg.retrieval.enabled = True

    orch = Orchestrator(cfg, DummyProvider(), ws)
    res = await orch.one_turn(s, "pdf formats", status=None)
    assert res.action == "kb_query"
    assert res.retrieval_hits == 0
    assert "> \"" not in res.content


@pytest.mark.asyncio
async def test_hits_must_include_quote(tmp_path: Path):
    ws = tmp_path
    sm = SessionManager(ws)
    s = sm.get("s1")

    # Create new KB layout: workspace/docs/default/kb
    kb_dir = ws / "docs" / "default" / "kb"
    chunks = kb_dir / "chunks"
    chunks.mkdir(parents=True, exist_ok=True)

    chunk_id = "doc-0000-aaaa"
    chunk_text = "This is a retrieved fact about formats."
    (chunks / f"{chunk_id}.md").write_text(chunk_text, encoding="utf-8")

    # Build index.json
    KBStore(kb_dir).rebuild_index()

    cfg = Config(workspace=str(ws))
    cfg.retrieval.enabled = True
    orch = Orchestrator(cfg, DummyProvider(), ws)

    res = await orch.one_turn(s, "pdf formats", status=None)
    assert res.action == "kb_query"
    assert res.retrieval_hits > 0
    assert "> \"" in res.content
    assert "formats" in res.content.lower()
