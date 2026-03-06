from __future__ import annotations

import math
import re
from collections import Counter

from picobot.router.documents import router_doc_text
from picobot.router.embedder import LocalEmbedder
from picobot.router.qdrant_router_store import RouterQdrantStore
from picobot.router.reranker import LocalReranker
from picobot.router.schemas import RouteCandidate, RouteRecord
from picobot.runtime_config import cfg_get


_WORD_RX = re.compile(r"[A-Za-z0-9_àèéìòù_-]+", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RX.findall(text or "")]


class _BM25:
    def __init__(self, docs: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.N = len(docs)
        self.avgdl = (sum(len(d) for d in docs) / self.N) if self.N else 0.0

        df: dict[str, int] = {}
        self.tf: list[Counter[str]] = []

        for doc in docs:
            tf = Counter(doc)
            self.tf.append(tf)
            for w in tf.keys():
                df[w] = df.get(w, 0) + 1

        self.idf = {
            w: math.log(1 + (self.N - n + 0.5) / (n + 0.5))
            for w, n in df.items()
        }

    def scores(self, query_tokens: list[str]) -> list[float]:
        if not self.docs:
            return []
        out = [0.0 for _ in self.docs]
        for i, doc in enumerate(self.docs):
            dl = len(doc) or 1
            tf = self.tf[i]
            denom_const = self.k1 * (1 - self.b + self.b * (dl / (self.avgdl or 1)))
            score = 0.0
            for w in query_tokens:
                if w not in tf:
                    continue
                f = tf[w]
                score += self.idf.get(w, 0.0) * (f * (self.k1 + 1)) / (f + denom_const)
            out[i] = score
        return out


class RouterRetriever:
    def __init__(self, *, store=None, embedder=None, reranker=None) -> None:
        self.store = store or RouterQdrantStore()
        self.embedder = embedder or LocalEmbedder()
        self.reranker = reranker or LocalReranker()
        self._records: list[RouteRecord] = []
        self._text_by_id: dict[str, str] = {}
        self._bm25: _BM25 | None = None
        self._record_by_id: dict[str, RouteRecord] = {}

        self.vector_w = float(cfg_get("router.score_weights.vector", 0.45))
        self.bm25_w = float(cfg_get("router.score_weights.bm25", 0.25))
        self.rerank_w = float(cfg_get("router.score_weights.rerank", 0.25))
        self.priority_w = float(cfg_get("router.score_weights.priority", 0.05))

    def seed_if_empty(self, records: list[RouteRecord]) -> None:
        self._records = list(records)
        self._record_by_id = {r.id: r for r in self._records}
        self._text_by_id = {r.id: router_doc_text(r) for r in self._records}
        self._bm25 = _BM25([_tokens(self._text_by_id[r.id]) for r in self._records])

        if self.store.count() > 0:
            return

        texts = [self._text_by_id[r.id] for r in records]
        vectors = self.embedder.embed(texts)
        self.store.ensure_collection(len(vectors[0]))

        points = []
        for rec, txt, vec in zip(records, texts, vectors):
            points.append(
                {
                    "id": rec.id,
                    "vector": vec,
                    "payload": {
                        "kind": rec.kind,
                        "name": rec.name,
                        "title": rec.title,
                        "description": rec.description,
                        "capabilities": rec.capabilities,
                        "limitations": rec.limitations,
                        "tags": rec.tags,
                        "example_queries": rec.example_queries,
                        "requires_kb": rec.requires_kb,
                        "requires_network": rec.requires_network,
                        "enabled": rec.enabled,
                        "priority": rec.priority,
                        "text": txt,
                    },
                }
            )
        self.store.upsert(points)

    def retrieve(self, user_text: str, *, top_k: int = 5) -> list[RouteCandidate]:
        if not (user_text or "").strip():
            return []

        qvec = self.embedder.embed([user_text])[0]
        hits = self.store.search(vector=qvec, top_k=max(8, int(top_k)))
        vector_map: dict[str, float] = {}

        for hit in hits:
            payload = dict(hit.payload or {})
            source_id = str(payload.get("_source_id") or "")
            if not source_id:
                continue
            if payload.get("enabled") is False:
                continue
            vector_map[source_id] = float(hit.score)

        bm25_map: dict[str, float] = {}
        if self._bm25 and self._records:
            qtok = _tokens(user_text)
            bm_scores = self._bm25.scores(qtok)
            bm_max = max(bm_scores) if bm_scores else 0.0
            for rec, s in zip(self._records, bm_scores):
                bm25_map[rec.id] = (float(s) / bm_max) if bm_max > 0 else 0.0

        candidate_ids = set(vector_map.keys()) | {rid for rid, s in bm25_map.items() if s > 0.0}
        if not candidate_ids:
            return []

        raw_candidates = []
        for rid in candidate_ids:
            rec = self._record_by_id.get(rid)
            if not rec or not rec.enabled:
                continue
            txt = self._text_by_id.get(rid, "")
            raw_candidates.append(
                {
                    "id": rid,
                    "vector_score": float(vector_map.get(rid, 0.0)),
                    "bm25_score": float(bm25_map.get(rid, 0.0)),
                    "rerank_score": float(vector_map.get(rid, 0.0)),
                    "payload": {
                        "kind": rec.kind,
                        "name": rec.name,
                        "title": rec.title,
                        "description": rec.description,
                        "capabilities": rec.capabilities,
                        "limitations": rec.limitations,
                        "tags": rec.tags,
                        "example_queries": rec.example_queries,
                        "requires_kb": rec.requires_kb,
                        "requires_network": rec.requires_network,
                        "enabled": rec.enabled,
                        "priority": rec.priority,
                    },
                    "text": txt,
                }
            )

        raw_candidates = self.reranker.rerank(user_text, raw_candidates)

        out: list[RouteCandidate] = []
        for c in raw_candidates:
            payload = c["payload"]
            rec = RouteRecord(
                id=str(c["id"]),
                kind=str(payload.get("kind") or "workflow"),
                name=str(payload.get("name") or ""),
                title=str(payload.get("title") or ""),
                description=str(payload.get("description") or ""),
                capabilities=list(payload.get("capabilities") or []),
                limitations=list(payload.get("limitations") or []),
                tags=list(payload.get("tags") or []),
                example_queries=list(payload.get("example_queries") or []),
                requires_kb=bool(payload.get("requires_kb", False)),
                requires_network=bool(payload.get("requires_network", False)),
                enabled=bool(payload.get("enabled", True)),
                priority=int(payload.get("priority", 50)),
                metadata={},
            )
            final = (
                self.vector_w * float(c.get("vector_score", 0.0)) +
                self.bm25_w * float(c.get("bm25_score", 0.0)) +
                self.rerank_w * float(c.get("rerank_score", 0.0)) +
                self.priority_w * (rec.priority / 100.0)
            )
            out.append(
                RouteCandidate(
                    record=rec,
                    vector_score=float(c.get("vector_score", 0.0)),
                    rerank_score=float(c.get("rerank_score", 0.0)),
                    final_score=float(final),
                    reason=(
                        f"vector={c.get('vector_score',0.0):.4f} "
                        f"bm25={c.get('bm25_score',0.0):.4f} "
                        f"rerank={c.get('rerank_score',0.0):.4f} "
                        f"priority={rec.priority}"
                    ),
                )
            )

        out.sort(key=lambda x: x.final_score, reverse=True)
        return out[: max(1, top_k)]
