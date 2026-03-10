import asyncio
from pathlib import Path

from pypdf import PdfWriter

from picobot.retrieval.schemas import IngestResult
from picobot.tools.retrieval import make_kb_ingest_pdf_tool


def _write_valid_pdf(path: Path) -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=595, height=842)
    with path.open("wb") as f:
        writer.write(f)


def test_kb_ingest_tool_is_real_and_deterministic(tmp_path: Path, monkeypatch):
    workspace = tmp_path / "workspace"
    docs_root = workspace / "docs"
    docs_root.mkdir(parents=True, exist_ok=True)

    pdf = tmp_path / "invented.pdf"
    _write_valid_pdf(pdf)

    calls: dict[str, object] = {}

    def fake_ingest_kb(*, workspace: Path, kb_name: str) -> IngestResult:
        calls["workspace"] = workspace
        calls["kb_name"] = kb_name
        return IngestResult(
            kb_name=kb_name,
            source_files=1,
            chunk_files=2,
            indexed_points=2,
            manifest_path=str(workspace / "docs" / kb_name / "kb" / "manifest.json"),
        )

    monkeypatch.setattr("picobot.tools.retrieval.ingest_kb", fake_ingest_kb)

    tool = make_kb_ingest_pdf_tool(docs_root)
    model = tool.validate({"kb_name": "Demo KB", "file_path": str(pdf)})
    result = asyncio.run(tool.handler(model))

    assert result["ok"] is True
    data = result["data"]

    assert data["kb_name"] == "Demo-KB"
    assert data["source_files"] == 1
    assert calls == {
        "workspace": workspace,
        "kb_name": "Demo-KB",
    }
    assert (workspace / "docs" / "Demo-KB" / "source" / "invented.pdf").exists()
