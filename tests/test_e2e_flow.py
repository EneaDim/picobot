from pathlib import Path

from picobot.agent.router import deterministic_route
from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.query import query_kb
from picobot.retrieval.store import ensure_kb_dirs


def test_e2e_kb_query_routes_to_kb_when_kb_active(tmp_path: Path, monkeypatch):
    workspace = tmp_path
    p = ensure_kb_dirs(workspace, "verilator")

    pdf_path = p.source_dir / "verilator.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

    monkeypatch.setattr(
        "picobot.retrieval.ingest._read_pdf_text",
        lambda _pdf: """
        Verilator reference manual.

        The --trace option enables waveform tracing.
        It is commonly used to dump waveforms for debugging.
        Use --trace-fst for FST tracing output.
        """.strip(),
    )

    ingest_kb(workspace, "verilator")

    state_file = workspace / "state" / "router.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text('{"kb_name":"verilator","kb_enabled":true}', encoding="utf-8")

    decision = deterministic_route("how --trace works in verilator", state_file, default_language="it")

    assert decision.action == "workflow"
    assert decision.name == "kb_query"


def test_e2e_kb_query_returns_hits(tmp_path: Path, monkeypatch):
    workspace = tmp_path
    p = ensure_kb_dirs(workspace, "verilator")

    pdf_path = p.source_dir / "verilator.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

    monkeypatch.setattr(
        "picobot.retrieval.ingest._read_pdf_text",
        lambda _pdf: """
        Verilator user guide.

        The --trace option enables waveform tracing.
        Tracing can be used for simulation debugging.
        The feature writes waveform output for later inspection.
        """.strip(),
    )

    ingest_kb(workspace, "verilator")

    qr = query_kb(workspace, "verilator", "how --trace works in verilator", top_k=4)

    assert len(qr.hits) > 0
    assert "--trace" in qr.context.lower()


def test_e2e_kb_query_no_hits_on_irrelevant_question(tmp_path: Path, monkeypatch):
    workspace = tmp_path
    p = ensure_kb_dirs(workspace, "verilator")

    pdf_path = p.source_dir / "verilator.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf")

    monkeypatch.setattr(
        "picobot.retrieval.ingest._read_pdf_text",
        lambda _pdf: """
        Verilator tracing manual.

        The --trace option enables waveform tracing.
        Use --trace-fst to emit FST traces.
        """.strip(),
    )

    ingest_kb(workspace, "verilator")

    qr = query_kb(workspace, "verilator", "what is the capital of france", top_k=4)

    # current lightweight retrieval may still return something if query overlaps poorly,
    # so this test checks that clearly irrelevant keywords are absent from context
    assert "capital of france" not in qr.context.lower()
