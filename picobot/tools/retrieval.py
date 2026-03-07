from __future__ import annotations

# Tool wrapper per la KB.
#
# Manteniamo la struttura tool attuale, come richiesto,
# ma rendiamo il contratto più pulito:
# - kb_ingest_pdf resta CLI-managed
# - kb_query usa il nuovo QueryService sotto al cofano
from pathlib import Path

from pydantic import BaseModel, Field

from picobot.retrieval.query import query_kb
from picobot.retrieval.store import ensure_kb_dirs
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class KBIngestPdfArgs(BaseModel):
    """
    Tool placeholder: l'ingest vero continua a passare dalla CLI/UI.
    """
    text: str = Field(..., min_length=1)
    lang: str | None = None


class KBQueryArgs(BaseModel):
    """
    Argomenti del tool kb_query.
    """
    kb_name: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=4, ge=1, le=10)


def make_kb_ingest_pdf_tool(docs_root: Path) -> ToolSpec:
    """
    Tool compatibile con il registry, ma l'ingest resta esplicitamente CLI-managed.
    """
    async def _handler(args: KBIngestPdfArgs) -> dict:
        return tool_error("Use /kb ingest <pdf_path> from the CLI")

    return ToolSpec(
        name="kb_ingest_pdf",
        description="CLI-managed KB PDF ingest.",
        schema=KBIngestPdfArgs,
        handler=_handler,
    )


def make_kb_query_tool(docs_root: Path) -> ToolSpec:
    """
    Tool di query della knowledge base locale.
    """
    workspace = docs_root.parent

    async def _handler(args: KBQueryArgs) -> dict:
        # Garantiamo il layout minimo della KB.
        ensure_kb_dirs(workspace, args.kb_name)

        # Eseguiamo query hybrid.
        result = query_kb(
            workspace=workspace,
            kb_name=args.kb_name,
            query=args.query,
            top_k=args.top_k,
        )

        # Ritorniamo dati strutturati, non testo "magico".
        return tool_ok(
            {
                "kb_name": args.kb_name,
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
