from pathlib import Path

from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.query import query_kb
from picobot.retrieval.store import ensure_kb_dirs


def test_no_index_returns_no_hits(tmp_path: Path):
    workspace = tmp_path
    ensure_kb_dirs(workspace, "emptykb")

    qr = query_kb(workspace, "emptykb", "how --trace works", top_k=4)

    assert qr.hits == []
    assert qr.context == ""


def test_hits_return_context_for_relevant_query(tmp_path: Path, monkeypatch):
    workspace = tmp_path
    p = ensure_kb_dirs(workspace, "verilator")

    pdf_path = p.source_dir / "verilator.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

    monkeypatch.setattr(
        "picobot.retrieval.ingest._read_pdf_text",
        lambda _pdf: """
        Verilator documentation.

        The --trace option enables waveform tracing.
        Use --trace-fst to write FST waveforms.
        Tracing is useful for debugging simulations.
        """.strip(),
    )

    ingest_kb(workspace, "verilator")

    qr = query_kb(workspace, "verilator", "how --trace works in verilator", top_k=4)

    assert len(qr.hits) > 0
    assert "--trace" in qr.context.lower()
    assert "waveform" in qr.context.lower() or "tracing" in qr.context.lower()
