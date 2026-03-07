from __future__ import annotations

# Router retriever hybrid:
# - vector search su Qdrant
# - BM25 in-memory sul corpus router
# - score finale pesato
#
# Importante:
# il router NON deve prendere decisioni finali di policy.
# Deve solo produrre candidati ordinati bene.
#
# La policy finale sta in router_policy.py.
import math
import re
from collections import Counter

from picobot.router.documents import router_doc_text
from picobot.router.embedder import LocalEmbedder
from picobot.router.qdrant_router_store import RouterQdrantStore
from picobot.router.schemas import RouteCandidate, RouteRecord
from picobot.runtime_config import cfg_get

# Tokenizzazione leggera e locale.
_WORD_RX = re.compile(r"[A-Za-z0-9_àèéìòù\-]{2,}", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    """
    Tokenizzazione minimale, stabile e sufficiente per BM25.
    """
    return [tok.lower() for tok in _WORD_RX.findall(text or "")]


class _BM25:
    """
    BM25 minimale in-memory per il corpus router.

    Non persistiamo su disco perché:
    - il corpus router è piccolo
    - si ricostruisce in millisecondi
    - è più semplice così
    """

    def __init__(self, docs: list[list[str]], *, k1: float = 1.5, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = float(k1)
        self.b = float(b)
        self.n_docs = len(docs)
        self.avg_doc_len = (
            sum(len(doc) for doc in docs) / len(docs)
            if docs else 1.0
        )

        self.term_freqs: list[Counter[str]] = []
        self.doc_freqs: dict[str, int] = {}

        for doc in docs:
            tf = Counter(doc)
            self.term_freqs.append(tf)

            for term in tf.keys():
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1

    def _idf(self, term: str) -> float:
        """
        IDF BM25 classica.
        """
        df = int(self.doc_freqs.get(term, 0))
        n_docs = max(1, self.n_docs)
        return math.log(1.0 + ((n_docs - df + 0.5) / (df + 0.5)))

    def scores(self, query_tokens: list[str]) -> list[float]:
        """
        Calcola gli score BM25 per tutti i documenti del corpus.
        """
        if not self.docs or not query_tokens:
            return []

        out = [0.0 for _ in self.docs]

        for idx, doc in enumerate(self.docs):
            tf = self.term_freqs[idx]
            doc_len = max(1, len(doc))

            score = 0.0

            for term in query_tokens:
                freq = tf.get(term, 0)
                if freq <= 0:
                    continue

                idf = self._idf(term)
                denom = freq + self.k1 * (
                    1.0 - self.b + self.b * (doc_len / max(1.0, self.avg_doc_len))
                )
                score += idf * ((freq * (self.k1 + 1.0)) / max(1e-9, denom))

            out[idx] = float(score)

        return out


class RouterRetriever:
    """
    Recupera candidati router con approccio hybrid.
    """

    def __init__(self, *, store=None, embedder=None) -> None:
        self.store = store or RouterQdrantStore()
        self.embedder = embedder or LocalEmbedder()

        # Config pesi score.
        self.vector_w = float(cfg_get("router.score_weights.vector", 0.60))
        self.bm25_w = float(cfg_get("router.score_weights.bm25", 0.30))
        self.rerank_w = float(cfg_get("router.score_weights.rerank", 0.00))
        self.priority_w = float(cfg_get("router.score_weights.priority", 0.10))

        # Stato in-memory del corpus router.
        self.records: list[RouteRecord] = []
        self.record_by_id: dict[str, RouteRecord] = {}
        self.text_by_id: dict[str, str] = {}
        self.bm25: _BM25 | None = None

    def rebuild_index(self, records: list[RouteRecord]) -> None:
        """
        Ricostruisce completamente l'indice router.

        Flusso:
        - materializza testi canonici
        - costruisce BM25 in-memory
        - genera embeddings
        - ricrea collection Qdrant
        - upsert completo
        """
        self.records = list(records)
        self.record_by_id = {record.id: record for record in self.records}
        self.text_by_id = {record.id: router_doc_text(record) for record in self.records}

        # BM25 in-memory.
        tokenized_docs = [_tokens(self.text_by_id[record.id]) for record in self.records]
        self.bm25 = _BM25(tokenized_docs)

        # Se non ci sono record, non c'è nulla da indicizzare.
        if not self.records:
            return

        # Embeddings di tutto il corpus router.
        texts = [self.text_by_id[record.id] for record in self.records]
        vectors = self.embedder.embed(texts)

        if len(vectors) != len(self.records):
            raise RuntimeError(
                f"router embedding count mismatch: expected {len(self.records)}, got {len(vectors)}"
            )

        # Rebuild totale della collection.
        self.store.recreate_collection(vector_size=len(vectors[0]))

        points: list[dict] = []

        for record, text, vector in zip(self.records, texts, vectors):
            points.append(
                {
                    "id": record.id,
                    "vector": vector,
                    "payload": {
                        **record.to_payload(),
                        "text": text,
                    },
                }
            )

        self.store.upsert(points)

    def retrieve(self, user_text: str, *, top_k: int = 5) -> list[RouteCandidate]:
        """
        Recupera i migliori candidati router per una query utente.
        """
        query = (user_text or "").strip()
        if not query:
            return []

        # --- ramo vettoriale ---
        query_vector = self.embedder.embed([query])[0]
        raw_vector_hits = self.store.search(
            vector=query_vector,
            top_k=max(8, int(top_k)),
        )

        vector_map: dict[str, float] = {}

        for hit in raw_vector_hits:
            payload = dict(hit.payload or {})
            source_id = str(payload.get("_source_id") or payload.get("id") or "")

            if not source_id:
                continue

            if payload.get("enabled") is False:
                continue

            vector_map[source_id] = float(hit.score)

        # --- ramo lessicale ---
        lexical_map: dict[str, float] = {}

        if self.bm25 is not None and self.records:
            bm25_scores = self.bm25.scores(_tokens(query))
            max_bm25 = max(bm25_scores) if bm25_scores else 0.0

            for record, score in zip(self.records, bm25_scores):
                lexical_map[record.id] = (
                    float(score) / max_bm25
                    if max_bm25 > 0.0 else 0.0
                )

        # Unione candidati.
        candidate_ids = set(vector_map.keys()) | {rid for rid, score in lexical_map.items() if score > 0.0}

        if not candidate_ids:
            return []

        out: list[RouteCandidate] = []

        for route_id in candidate_ids:
            record = self.record_by_id.get(route_id)
            if record is None:
                continue

            if not record.enabled:
                continue

            vector_score = float(vector_map.get(route_id, 0.0))
            lexical_score = float(lexical_map.get(route_id, 0.0))

            # Reranker opzionale rimandato:
            # per ora lasciamo 0.0 e manteniamo il campo nel contratto.
            rerank_score = 0.0

            priority_bias = max(0.0, min(1.0, float(record.priority) / 100.0))

            final_score = (
                self.vector_w * vector_score +
                self.bm25_w * lexical_score +
                self.rerank_w * rerank_score +
                self.priority_w * priority_bias
            )

            reason = (
                f"vector={vector_score:.4f} "
                f"lexical={lexical_score:.4f} "
                f"rerank={rerank_score:.4f} "
                f"priority={record.priority}"
            )

            out.append(
                RouteCandidate(
                    record=record,
                    vector_score=vector_score,
                    lexical_score=lexical_score,
                    rerank_score=rerank_score,
                    final_score=float(final_score),
                    reason=reason,
                )
            )

        out.sort(key=lambda item: item.final_score, reverse=True)
        return out[: max(1, int(top_k))]
