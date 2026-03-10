from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.query import query_kb
from picobot.retrieval.store import copy_source_file, ensure_kb_dirs, sanitize_kb_name
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class KBIngestPdfArgs(BaseModel):
    kb_name: str = Field(..., min_length=1)
    file_path: str = Field(..., min_length=1)


class KBQueryArgs(BaseModel):
    kb_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)


def make_kb_ingest_pdf_tool(docs_root: Path) -> ToolSpec:
    workspace = docs_root.parent

    async def _handler(args: KBIngestPdfArgs) -> dict:
        src = Path(args.file_path).expanduser().resolve()
        kb_name = sanitize_kb_name(args.kb_name)

        if not src.exists() or not src.is_file():
            return tool_error(f"PDF non trovato: {src}")

        if src.suffix.lower() != ".pdf":
            return tool_error("kb_ingest_pdf supporta solo PDF")

        try:
            ensure_kb_dirs(workspace, kb_name)
            copied = copy_source_file(workspace, kb_name, src)
            result = ingest_kb(workspace=workspace, kb_name=kb_name)
        except Exception as exc:
            return tool_error(str(exc))

        return tool_ok(
            {
                "kb_name": result.kb_name,
                "copied_file": str(copied),
                "source_files": result.source_files,
                "chunk_files": result.chunk_files,
                "indexed_points": result.indexed_points,
                "manifest_path": result.manifest_path,
            }
        )

    return ToolSpec(
        name="kb_ingest_pdf",
        description="Ingest a PDF into the local knowledge base.",
        schema=KBIngestPdfArgs,
        handler=_handler,
    )


def make_kb_query_tool(docs_root: Path) -> ToolSpec:
    workspace = docs_root.parent

    async def _handler(args: KBQueryArgs) -> dict:
        kb_name = sanitize_kb_name(args.kb_name)

        try:
            ensure_kb_dirs(workspace, kb_name)
            result = query_kb(
                workspace=workspace,
                kb_name=kb_name,
                query=args.query,
                top_k=args.top_k,
            )
        except Exception as exc:
            return tool_error(str(exc))

        return tool_ok(
            {
                "kb_name": kb_name,
                "hits": len(result.hits),
                "max_score": result.max_score,
                "context": result.context,
                "items": [
                    {
                        "chunk_id": hit.chunk_id,
                        "score": hit.score,
                        "fused_score": hit.fused_score,
                        "vector_score": hit.vector_score,
                        "lexical_score": hit.lexical_score,
                        "source_file": hit.source_file,
                        "text": hit.text,
                        "page_start": hit.page_start,
                        "page_end": hit.page_end,
                        "section": hit.section,
                        "ranks": dict(hit.ranks),
                    }
                    for hit in result.hits
                ],
            },
            language=None,
        )

    return ToolSpec(
        name="kb_query",
        description="Query a local KB using hybrid retrieval over local indexes.",
        schema=KBQueryArgs,
        handler=_handler,
    )
