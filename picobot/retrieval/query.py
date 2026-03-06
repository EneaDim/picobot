from __future__ import annotations

import re
from pathlib import Path

from picobot.retrieval.embedder import LocalEmbedder
from picobot.retrieval.qdrant_docs_store import DocsQdrantStore
from picobot.retrieval.schemas import QueryHit, QueryResult
from picobot.runtime_config import cfg_get


def _boost_score(query: str, text: str, base: float) -> float:
    q = (query or "").lower()
    t = (text or "").lower()
    score = float(base)

    token_boost = float(cfg_get("retrieval.exact_match_boost", 0.03))
    boosts = dict(cfg_get("retrieval.special_token_boosts", {"--trace": 0.20, "trace-fst": 0.20}) or {})

    q_tokens = [x for x in re.findall(r"[A-Za-z0-9_àèéìòù\-]+", q) if len(x) >= 2]
    for tok in q_tokens:
        if tok in t:
            score += token_boost

    for tok, val in boosts.items():
        if tok in q and tok in t:
            score += float(val)

    return score


def query_kb(workspace: Path, kb_name: str, query: str, top_k: int = 4) -> QueryResult:
    if not (query or "").strip():
        return QueryResult(hits=[], context="", max_score=0.0)

    vector_top_k = int(cfg_get("retrieval.vector_top_k", 8))
    final_top_k = int(cfg_get("retrieval.final_top_k", top_k))

    embedder = LocalEmbedder()
    store = DocsQdrantStore()
    qvec = embedder.embed([query])[0]

    hits = store.search(vector=qvec, kb_name=kb_name, top_k=max(8, vector_top_k))
    raw = []

    for hit in hits:
        payload = dict(hit.payload or {})
        text = str(payload.get("text") or "")
        boosted = _boost_score(query, text, float(hit.score))
        raw.append((boosted, payload))

    raw.sort(key=lambda x: x[0], reverse=True)
    raw = raw[: max(1, final_top_k)]

    out: list[QueryHit] = []
    max_score = 0.0

    for score, payload in raw:
        max_score = max(max_score, float(score))
        out.append(
            QueryHit(
                chunk_id=str(payload.get("id") or payload.get("_source_id") or ""),
                score=float(score),
                text=str(payload.get("text") or ""),
                source_file=str(payload.get("source_file") or ""),
                page=payload.get("page"),
                section=str(payload.get("section") or ""),
            )
        )

    context = "\n\n".join([h.text for h in out if h.text]).strip()
    return QueryResult(hits=out, context=context, max_score=max_score)
