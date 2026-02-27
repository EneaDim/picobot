from __future__ import annotations

from pathlib import Path

from picobot.config.schema import Config
import pytest

from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse

from picobot.tools.retrieval import make_kb_ingest_pdf_tool
from picobot.retrieval.store import KBStore
from tests.conftest import dbg


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(content="ANSWER_FROM_LLM", tool_calls=[])


@pytest.mark.asyncio
async def test_ingest_pdf_creates_source_chunks_and_index(tmp_path: Path, monkeypatch):
    ws = tmp_path
    docs_root = ws / "docs"

    # dummy pdf (content doesn't matter; we monkeypatch extraction)
    pdf = ws / "sample.pdf"
    pdf.write_bytes(b"not-a-real-pdf")

    simple_text = (
        "Questo è un documento di test.\n"
        "Parla di formati di output.\n"
        "Supporta VCD e FST.\n"
        "Fine documento.\n"
    )

    def fake_pdf_to_text(_path: Path) -> str:
        return simple_text

    # Patch BOTH possible call sites
    import picobot.tools.retrieval as tool_mod
    import picobot.retrieval.ingest as ingest_mod

    monkeypatch.setattr(tool_mod, "pdf_to_text", fake_pdf_to_text)
    monkeypatch.setattr(ingest_mod, "pdf_to_text", fake_pdf_to_text)

    tool = make_kb_ingest_pdf_tool(docs_root)

    args = {"kb_name": "demo", "pdf_path": str(pdf), "doc_name": "doc-test", "chunk_chars": 200, "overlap": 20}
    model = tool.validate(args)
    out = await tool.handler(model)
    dbg('ingest out=', out)

    # copied to source/
    copied = ws / "docs" / "demo" / "source" / pdf.name
    assert copied.exists()

    # chunks exist
    chunks_dir = ws / "docs" / "demo" / "kb" / "chunks"
    assert chunks_dir.exists()
    assert any(chunks_dir.glob("*.md"))

    # index exists
    idx = ws / "docs" / "demo" / "kb" / "index.json"
    assert idx.exists()

    assert out["kb_name"] == "demo"


@pytest.mark.asyncio
async def test_search_kb_query_appends_quote_when_hits(tmp_path: Path):
    ws = tmp_path
    cfg = Config(workspace=str(ws))
    cfg.retrieval.enabled = True
    cfg.retrieval.top_k = 3

    sm = SessionManager(ws)
    s = sm.get("s1")
    s.set_state({"kb_name": "demo"})

    kb_dir = ws / "docs" / "demo" / "kb"
    chunks_dir = kb_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    cid = "doc-0000"
    text = (
        "Questo è un documento di test.\n"
        "Supporta i formati VCD e FST.\n"
        "Usa l'opzione --trace per generare waveform.\n"
        "Fine.\n"
    )
    (chunks_dir / f"{cid}.md").write_text(text, encoding="utf-8")

    KBStore(kb_dir).rebuild_index()
    dbg('kb_dir=', kb_dir)

    orch = Orchestrator(cfg, DummyProvider(), ws)
    res = await orch.one_turn(s, "Nel documento quali formati supporta? Riporta una breve citazione.", status=None)

    assert res.action == "kb_query"
    assert res.retrieval_hits > 0
    assert '\n> "' in res.content
    assert "vcd" in res.content.lower()
