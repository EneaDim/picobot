from __future__ import annotations

import shutil
from pathlib import Path
from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
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
        try:
            kb_name = args.kb_name.strip() or "default"

            doc_root = docs_root / kb_name
            source_dir = doc_root / "source"
            kb_dir = doc_root / "kb"

            source_dir.mkdir(parents=True, exist_ok=True)
            kb_dir.mkdir(parents=True, exist_ok=True)

            pdfp = Path(args.pdf_path).expanduser()
            if not pdfp.exists() or not pdfp.is_file():
                return tool_error("pdf_path must exist and be a file")
            if pdfp.suffix.lower() != ".pdf":
                return tool_error("pdf_path must be a .pdf")

            # copy pdf into source/
            dest = source_dir / pdfp.name
            shutil.copy2(pdfp, dest)

            text = pdf_to_text(dest)
            chunks = chunk_text(text, chunk_chars=args.chunk_chars, overlap=args.overlap)
            if not chunks:
                return tool_error("no extractable text from pdf")

            meta = add_document_chunks(kb_dir, args.doc_name, chunks)

            # rebuild BM25 index inside kb_dir
            KBStore(kb_dir).rebuild_index()

            return tool_ok(
                {
                    "kb_name": kb_name,
                    "source_pdf": str(dest),
                    "kb_dir": str(kb_dir),
                    "doc": meta,
                    "chunks": len(chunks),
                }
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="kb_ingest_pdf",
        description="Ingest a PDF into workspace/docs/<kb>/source and index into workspace/docs/<kb>/kb.",
        schema=KBIngestPDFArgs,
        handler=_handler,
    )


class KBQueryArgs(BaseModel):
    kb_name: str = Field(default="default", min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


def make_kb_query_tool(docs_root: Path):
    async def _handler(args: KBQueryArgs) -> dict:
        try:
            kb_name = (args.kb_name or "default").strip() or "default"
            kb_dir = Path(docs_root) / kb_name / "kb"
            store = KBStore(kb_dir)
            hits = store.search(args.query, top_k=int(args.top_k))
            chunks = []
            for h in hits or []:
                txt = (h.get("text") or "").strip()
                if txt:
                    chunks.append(txt)
            context = "\n\n".join(chunks)
            return tool_ok(
                {
                    "kb_name": kb_name,
                    "hits": len(hits or []),
                    "context": context,
                }
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="kb_query",
        description="Search the local KB index and return concatenated context.",
        schema=KBQueryArgs,
        handler=_handler,
    )
