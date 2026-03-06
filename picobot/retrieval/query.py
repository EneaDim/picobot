from __future__ import annotations

# Query KB hybrid:
# - vector retrieval da Qdrant
# - lexical retrieval BM25 da indice locale
# - fusione rank-based semplice e trasparente
#
# Questo file espone:
# - QueryService
# - query_kb(...) per compatibilità con il resto del progetto

from pathlib import Path

from picobot.retrieval.bm25 import BM25Index
from picobot.retrieval.embedder import LocalEmbedder
from picobot.retrieval.qdrant_docs_store import DocsQdrantStore
from picobot.retrieval.schemas import QueryHit, QueryResult
from picobot.retrieval.store import kb_paths
from picobot.runtime_config import cfg_get


class QueryService:
    """
    Servizio di query documentale hybrid.
    """

    def __init__(self, workspace: Path, kb_name: str) -> None:
        self.workspace = Path(workspace).resolve()
        self.kb_name = str(kb_name or "").strip()

        self.paths = kb_paths(self.workspace, self.kb_name)

        self.embedder = LocalEmbedder()
        self.docs_store = DocsQdrantStore()

        self.vector_top_k = int(cfg_get("retrieval.vector_top_k", 12))
        self.lexical_top_k = int(cfg_get("retrieval.bm25_candidates", 12))
        self.final_top_k = int(cfg_get("retrieval.final_top_k", 4))
        self.max_context_chars = int(cfg_get("retrieval.max_context_chars", 5000))

    def _load_bm25(self) -> BM25Index | None:
        """
        Carica l'indice BM25 della KB, se presente.
        """
        bm25_path = self.paths.index_dir / "bm25.json"

        if not bm25_path.exists():
            return None

        try:
            return BM25Index.load(bm25_path)
        except Exception:
            return None

    def _vector_hits(self, query: str) -> list[dict]:
        """
        Recupera candidati vettoriali da Qdrant.
        """
        if not query.strip():
            return []

        qvec = self.embedder.embed([query])[0]
        raw_hits = self.docs_store.search(
            vector=qvec,
            kb_name=self.kb_name,
            top_k=max(1, self.vector_top_k),
        )

        out: list[dict] = []

        for hit in raw_hits:
            payload = dict(hit.payload or {})
            chunk_id = str(payload.get("chunk_id") or payload.get("id") or payload.get("_source_id") or "")
            out.append(
                {
                    "chunk_id": chunk_id,
                    "text": str(payload.get("text") or ""),
                    "source_file": str(payload.get("source_file") or ""),
                    "page_start": payload.get("page_start"),
                    "page_end": payload.get("page_end"),
                    "section": str(payload.get("section") or ""),
                    "vector_score": float(hit.score),
                }
            )

        return out

    def _lexical_hits(self, query: str) -> list[dict]:
        """
        Recupera candidati lessicali BM25.
        """
        bm25 = self._load_bm25()
        if bm25 is None:
            return []

        raw_hits = bm25.search(query, top_k=max(1, self.lexical_top_k))

        out: list[dict] = []

        for hit in raw_hits:
            out.append(
                {
                    "chunk_id": hit.chunk_id,
                    "text": hit.text,
                    "source_file": hit.source_file,
                    "page_start": hit.page_start,
                    "page_end": hit.page_end,
                    "section": hit.section,
                    "lexical_score": float(hit.score),
                }
            )

        return out

    def _merge_hits(
        self,
        *,
        vector_hits: list[dict],
        lexical_hits: list[dict],
        top_k: int,
    ) -> list[QueryHit]:
        """
        Fonde i due ranking con una rank fusion semplice.

        Scelta:
        - Reciprocal Rank Fusion-like
        - piccolo contributo dagli score grezzi
        - niente formule opache
        """
        rrf_k = 60.0

        merged: dict[str, dict] = {}

        # Indicizzazione dei candidati vettoriali.
        for rank, item in enumerate(vector_hits, start=1):
            chunk_id = item["chunk_id"]
            rec = merged.setdefault(
                chunk_id,
                {
                    "chunk_id": chunk_id,
                    "text": item.get("text") or "",
                    "source_file": item.get("source_file") or "",
                    "page_start": item.get("page_start"),
                    "page_end": item.get("page_end"),
                    "section": item.get("section") or "",
                    "vector_score": 0.0,
                    "lexical_score": 0.0,
                    "vector_rank": None,
                    "lexical_rank": None,
                    "fused_score": 0.0,
                },
            )

            rec["vector_score"] = float(item.get("vector_score") or 0.0)
            rec["vector_rank"] = rank

        # Indicizzazione dei candidati lessicali.
        lexical_max = max([float(x.get("lexical_score") or 0.0) for x in lexical_hits], default=0.0)

        for rank, item in enumerate(lexical_hits, start=1):
            chunk_id = item["chunk_id"]
            rec = merged.setdefault(
                chunk_id,
                {
                    "chunk_id": chunk_id,
                    "text": item.get("text") or "",
                    "source_file": item.get("source_file") or "",
                    "page_start": item.get("page_start"),
                    "page_end": item.get("page_end"),
                    "section": item.get("section") or "",
                    "vector_score": 0.0,
                    "lexical_score": 0.0,
                    "vector_rank": None,
                    "lexical_rank": None,
                    "fused_score": 0.0,
                },
            )

            # Se il testo non c'era dal ramo vettoriale, lo riempiamo dal lessicale.
            if not rec["text"]:
                rec["text"] = item.get("text") or ""
            if not rec["source_file"]:
                rec["source_file"] = item.get("source_file") or ""
            if rec["page_start"] is None:
                rec["page_start"] = item.get("page_start")
            if rec["page_end"] is None:
                rec["page_end"] = item.get("page_end")
            if not rec["section"]:
                rec["section"] = item.get("section") or ""

            rec["lexical_score"] = float(item.get("lexical_score") or 0.0)
            rec["lexical_rank"] = rank

        # Fusione finale.
        for rec in merged.values():
            score = 0.0

            vector_rank = rec["vector_rank"]
            lexical_rank = rec["lexical_rank"]

            if vector_rank is not None:
                score += 0.65 * (1.0 / (rrf_k + float(vector_rank)))
                score += 0.10 * float(rec["vector_score"] or 0.0)

            if lexical_rank is not None:
                score += 0.35 * (1.0 / (rrf_k + float(lexical_rank)))

                # Normalizziamo il punteggio lessicale sul massimo dei candidati.
                lexical_norm = (
                    float(rec["lexical_score"] or 0.0) / lexical_max
                    if lexical_max > 0.0 else 0.0
                )
                score += 0.05 * lexical_norm

            rec["fused_score"] = float(score)

        ranked = sorted(
            merged.values(),
            key=lambda item: item["fused_score"],
            reverse=True,
        )[: max(1, int(top_k))]

        out: list[QueryHit] = []

        for item in ranked:
            ranks: dict[str, int] = {}

            if item["vector_rank"] is not None:
                ranks["vector"] = int(item["vector_rank"])
            if item["lexical_rank"] is not None:
                ranks["lexical"] = int(item["lexical_rank"])

            out.append(
                QueryHit(
                    chunk_id=str(item["chunk_id"]),
                    fused_score=float(item["fused_score"]),
                    text=str(item["text"] or ""),
                    source_file=str(item["source_file"] or ""),
                    page_start=item.get("page_start"),
                    page_end=item.get("page_end"),
                    section=str(item.get("section") or ""),
                    vector_score=float(item.get("vector_score") or 0.0),
                    lexical_score=float(item.get("lexical_score") or 0.0),
                    ranks=ranks,
                )
            )

        return out

    def _build_context(self, hits: list[QueryHit]) -> str:
        """
        Costruisce il contesto finale da dare al modello.
        """
        parts: list[str] = []
        current_chars = 0

        for hit in hits:
            page_label = ""
            if hit.page_start is not None and hit.page_end is not None:
                if hit.page_start == hit.page_end:
                    page_label = f" p.{hit.page_start}"
                else:
                    page_label = f" p.{hit.page_start}-{hit.page_end}"

            header = f"[source: {hit.source_file}{page_label}]"
            block = f"{header}\n{hit.text.strip()}".strip()

            if not block:
                continue

            extra = len(block) + (2 if parts else 0)

            if current_chars + extra > self.max_context_chars:
                break

            parts.append(block)
            current_chars += extra

        return "\n\n".join(parts).strip()

    def query(self, query: str, top_k: int | None = None) -> QueryResult:
        """
        Esegue una query hybrid contro la KB.
        """
        query = (query or "").strip()

        if not query:
            return QueryResult(hits=[], context="", max_score=0.0)

        top_k = max(1, int(top_k or self.final_top_k))

        vector_hits = self._vector_hits(query)
        lexical_hits = self._lexical_hits(query)

        merged_hits = self._merge_hits(
            vector_hits=vector_hits,
            lexical_hits=lexical_hits,
            top_k=top_k,
        )

        context = self._build_context(merged_hits)
        max_score = max([hit.fused_score for hit in merged_hits], default=0.0)

        return QueryResult(
            hits=merged_hits,
            context=context,
            max_score=float(max_score),
        )


def query_kb(workspace: Path, kb_name: str, query: str, top_k: int = 4) -> QueryResult:
    """
    Wrapper di compatibilità con il resto del progetto.
    """
    service = QueryService(workspace=workspace, kb_name=kb_name)
    return service.query(query=query, top_k=top_k)
