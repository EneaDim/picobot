from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.query import query_kb
from picobot.retrieval.store import ensure_kb_dirs
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class KBIngestPdfArgs(BaseModel):
    text: str = Field(..., min_length=1)
    lang: str | None = None


class KBQueryArgs(BaseModel):
    kb_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)


def make_kb_ingest_pdf_tool(docs_root: Path) -> ToolSpec:
    async def _handler(args: KBIngestPdfArgs) -> dict:
        return tool_error("Use /kb ingest <pdf_path> from the CLI")

    return ToolSpec(
        name="kb_ingest_pdf",
        description="CLI-managed KB PDF ingest.",
        schema=KBIngestPdfArgs,
        handler=_handler,
    )


def make_kb_query_tool(docs_root: Path) -> ToolSpec:
    workspace = docs_root.parent

    async def _handler(args: KBQueryArgs) -> dict:
        ensure_kb_dirs(workspace, args.kb_name)
        qr = query_kb(workspace, args.kb_name, args.query, top_k=args.top_k)
        return tool_ok(
            {
                "kb_name": args.kb_name,
                "hits": len(qr.hits),
                "max_score": qr.max_score,
                "context": qr.context,
                "items": [
                    {
                        "chunk_id": h.chunk_id,
                        "score": h.score,
                        "source_file": h.source_file,
                        "text": h.text,
                        "page": h.page,
                        "section": h.section,
                    }
                    for h in qr.hits
                ],
            },
            language=None,
        )

    return ToolSpec(
        name="kb_query",
        description="Query a local KB stored in Qdrant.",
        schema=KBQueryArgs,
        handler=_handler,
    )
