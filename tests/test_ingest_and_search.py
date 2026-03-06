from pathlib import Path

from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.query import query_kb
from picobot.retrieval.store import ensure_kb_dirs, kb_paths, read_manifest


def test_ingest_kb_creates_new_layout_and_query_works(tmp_path: Path, monkeypatch):
    workspace = tmp_path
    p = ensure_kb_dirs(workspace, "verilator")

    # fake source pdf
    pdf_path = p.source_dir / "verilator.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake pdf content")

    # monkeypatch PDF extraction so the test does not depend on real PDF text extraction
    monkeypatch.setattr(
        "picobot.retrieval.ingest._read_pdf_text",
        lambda _pdf: """
        Verilator tracing documentation.

        The --trace option enables waveform tracing.
        You can use --trace-fst for FST tracing.
        Tracing is useful for debugging generated simulations.
        """.strip(),
    )

    res = ingest_kb(workspace, "verilator")

    paths = kb_paths(workspace, "verilator")
    manifest = read_manifest(workspace, "verilator")

    assert res.kb_name == "verilator"
    assert res.source_files == 1
    assert res.chunk_files > 0

    assert paths.source_dir.exists()
    assert paths.store_dir.exists()
    assert paths.chunks_dir.exists()
    assert paths.index_dir.exists()
    assert paths.manifest_path.exists()

    chunk_files = sorted(paths.chunks_dir.glob("*.json"))
    assert len(chunk_files) > 0

    assert (paths.index_dir / "postings.json").exists()
    assert (paths.index_dir / "idf.json").exists()

    assert manifest["kb_name"] == "verilator"
    assert manifest["source_files"] == 1
    assert manifest["chunk_files"] > 0

    qr = query_kb(workspace, "verilator", "how --trace works in verilator", top_k=4)
    assert len(qr.hits) > 0
    assert "--trace" in qr.context.lower()
