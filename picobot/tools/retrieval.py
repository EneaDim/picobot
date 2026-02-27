from __future__ import annotations

import shutil
from pathlib import Path
from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec
from picobot.retrieval.ingest import pdf_to_text, chunk_text
from picobot.retrieval.store import add_document_chunks, KBStore


class KBIngestPDFArgs(BaseModel):
    kb_name: str = Field(default="default", min_length=1)
    pdf_path: str = Field(..., min_length=1)
    doc_name: str = Field(default="document", min_length=1)
    chunk_chars: int = Field(default=1200, ge=200, le=8000)
    overlap: int = Field(default=150, ge=0, le=1000)


def make_kb_ingest_pdf_tool(docs_root: Path):
    async def _handler(args: KBIngestPDFArgs) -> dict:
        kb_name = args.kb_name.strip() or "default"

        doc_root = docs_root / kb_name
        source_dir = doc_root / "source"
        kb_dir = doc_root / "kb"

        source_dir.mkdir(parents=True, exist_ok=True)
        kb_dir.mkdir(parents=True, exist_ok=True)

        pdfp = Path(args.pdf_path).expanduser()
        if not pdfp.exists() or not pdfp.is_file():
            raise ValueError("pdf_path must exist and be a file")
        if pdfp.suffix.lower() != ".pdf":
            raise ValueError("pdf_path must be a .pdf")

        # copy pdf into source/
        dest = source_dir / pdfp.name
        shutil.copy2(pdfp, dest)

        text = pdf_to_text(dest)
        chunks = chunk_text(text, chunk_chars=args.chunk_chars, overlap=args.overlap)
        if not chunks:
            raise RuntimeError("no extractable text from pdf")

        meta = add_document_chunks(kb_dir, args.doc_name, chunks)

        # rebuild BM25 index inside kb_dir
        KBStore(kb_dir).rebuild_index()

        return {
            "kb_name": kb_name,
            "source_pdf": str(dest),
            "kb_dir": str(kb_dir),
            "doc": meta,
            "chunks": len(chunks),
        }

    return ToolSpec(
        name="kb_ingest_pdf",
        description="Ingest a PDF into workspace/docs/<kb>/source and index into workspace/docs/<kb>/kb.",
        schema=KBIngestPDFArgs,
        handler=_handler,
    )
