from __future__ import annotations

import importlib
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from picobot.routing.schemas import RouteCandidate, RouteRecord

logger = logging.getLogger(__name__)

_TOKEN_RX = re.compile(r"[a-zA-Z0-9_:-]+")


@dataclass(slots=True)
class RouteRetrieverResult:
    candidates: list[RouteCandidate]


def _normalize_vector(value: Any) -> list[float]:
    if value is None:
        return []
    if isinstance(value, list):
        try:
            return [float(x) for x in value]
        except Exception:
            return []
    try:
        return [float(x) for x in list(value)]
    except Exception:
        return []


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _TOKEN_RX.finditer(text or "")]


class _OptionalEmbedderAdapter:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def embed(self, texts: list[str]) -> list[list[float]]:
        if self.inner is None:
            raise RuntimeError("embedder unavailable")

        if hasattr(self.inner, "embed"):
            out = self.inner.embed(texts)
        elif callable(self.inner):
            out = self.inner(texts)
        else:
            raise RuntimeError("embedder object is not callable and has no embed()")

        if out is None:
            return []

        vectors: list[list[float]] = []
        for item in out:
            vec = _normalize_vector(item)
            if vec:
                vectors.append(vec)
        return vectors


def _try_build_embedder() -> _OptionalEmbedderAdapter | None:
    module_candidates = [
        "picobot.router.embedder",
        "picobot.retrieval.embedder",
    ]

    factory_names = [
        "make_embedder",
        "create_embedder",
        "get_embedder",
    ]

    class_names = [
        "RouterEmbedder",
        "OllamaEmbedder",
        "Embedder",
    ]

    for mod_name in module_candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            logger.debug("embedder module unavailable: %s (%s)", mod_name, e)
            continue

        for name in factory_names:
            factory = getattr(mod, name, None)
            if callable(factory):
                try:
                    return _OptionalEmbedderAdapter(factory())
                except TypeError:
                    try:
                        return _OptionalEmbedderAdapter(factory(None))
                    except Exception:
                        pass
                except Exception:
                    pass

        for name in class_names:
            cls = getattr(mod, name, None)
            if cls is None:
                continue
            try:
                return _OptionalEmbedderAdapter(cls())
            except TypeError:
                try:
                    return _OptionalEmbedderAdapter(cls(None))
                except Exception:
                    pass
            except Exception:
                pass

        embed_fn = getattr(mod, "embed", None)
        if callable(embed_fn):
            return _OptionalEmbedderAdapter(embed_fn)

    return None


class RouterRetriever:
    """
    Retriever ibrido per routing.

    Regole:
    - lexical scorer interno sempre disponibile
    - vector opzionale
    - nessuna dipendenza diretta da BM25Index
    - se embeddings non funzionano, degraded mode lexical-only
    """

    def __init__(self) -> None:
        self.embedder = _try_build_embedder()
        self.records: list[RouteRecord] = []
        self._record_texts: dict[str, str] = {}
        self._record_tokens: dict[str, list[str]] = {}
        self._record_tf: dict[str, Counter[str]] = {}
        self._doc_freq: Counter[str] = Counter()
        self._vectors: dict[str, list[float]] = {}
        self.vector_available = False

    def rebuild_index(self, records: list[RouteRecord]) -> None:
        self.records = list(records or [])
        self._record_texts = {}
        self._record_tokens = {}
        self._record_tf = {}
        self._doc_freq = Counter()
        self._vectors = {}
        self.vector_available = False

        for record in self.records:
            text = self._render_record_text(record)
            tokens = _tokenize(text)
            tf = Counter(tokens)

            self._record_texts[record.id] = text
            self._record_tokens[record.id] = tokens
            self._record_tf[record.id] = tf

            for token in tf.keys():
                self._doc_freq[token] += 1

        if not self.records or self.embedder is None:
            if self.embedder is None:
                logger.info("Router retriever running in lexical-only mode: no embedder available")
            return

        ids = [r.id for r in self.records]
        texts = [self._record_texts[rid] for rid in ids]

        try:
            vectors = self.embedder.embed(texts)
            if vectors and len(vectors) == len(ids):
                self._vectors = {rid: vec for rid, vec in zip(ids, vectors)}
                self.vector_available = True
            else:
                logger.warning("Router embedder returned invalid vectors; using lexical-only mode")
        except Exception as e:
            logger.warning("Router vector index unavailable, falling back to lexical-only mode: %s", e)
            self._vectors = {}
            self.vector_available = False

    def retrieve(self, query: str, top_k: int = 5) -> list[RouteCandidate]:
        query = (query or "").strip()
        if not query or not self.records:
            return []

        lexical_scores = self._lexical_scores(query)
        vector_scores = self._vector_scores(query) if self.vector_available else {}

        by_id: dict[str, RouteRecord] = {record.id: record for record in self.records}
        candidate_ids = set(lexical_scores.keys()) | set(vector_scores.keys())

        candidates: list[RouteCandidate] = []

        for route_id in candidate_ids:
            record = by_id.get(route_id)
            if record is None:
                continue

            lexical = float(lexical_scores.get(route_id, 0.0))
            vector = float(vector_scores.get(route_id, 0.0))
            rerank = 0.0
            priority = self._priority_score(record)

            if self.vector_available:
                final_score = (0.45 * vector) + (0.45 * lexical) + (0.10 * priority)
                reason = f"vector={vector:.4f} lexical={lexical:.4f} rerank={rerank:.4f} priority={priority:.0f}"
            else:
                final_score = (0.85 * lexical) + (0.15 * priority)
                reason = f"lexical={lexical:.4f} priority={priority:.0f} degraded=lexical-only"

            candidates.append(
                RouteCandidate(
                    record=record,
                    vector_score=vector,
                    lexical_score=lexical,
                    rerank_score=rerank,
                    final_score=float(final_score),
                    reason=reason,
                )
            )

        candidates.sort(key=lambda c: c.final_score, reverse=True)
        return candidates[: max(1, int(top_k))]

    def _lexical_scores(self, query: str) -> dict[str, float]:
        q_tokens = _tokenize(query)
        if not q_tokens:
            return {}

        q_tf = Counter(q_tokens)
        n_docs = max(1, len(self.records))

        raw_scores: dict[str, float] = {}

        for route_id, doc_tf in self._record_tf.items():
            score = 0.0

            # TF-IDF-like overlap score semplice ma efficace
            for token, q_count in q_tf.items():
                tf = float(doc_tf.get(token, 0))
                if tf <= 0:
                    continue

                df = float(self._doc_freq.get(token, 1))
                idf = math.log(1.0 + (n_docs / df))
                score += (1.0 + math.log(1.0 + tf)) * idf * float(q_count)

            # bonus frase/esempio
            doc_text = self._record_texts.get(route_id, "").lower()
            q_low = query.lower()
            if q_low and q_low in doc_text:
                score += 1.5

            # bonus overlap percentuale
            doc_tokens = set(self._record_tokens.get(route_id, []))
            q_token_set = set(q_tokens)
            if doc_tokens and q_token_set:
                overlap = len(doc_tokens & q_token_set) / max(1, len(q_token_set))
                score += 0.75 * overlap

            raw_scores[route_id] = score

        positives = {k: v for k, v in raw_scores.items() if v > 0.0}
        if not positives:
            return {}

        best = max(positives.values()) or 1.0
        return {k: v / best for k, v in positives.items()}

    def _vector_scores(self, query: str) -> dict[str, float]:
        if self.embedder is None:
            self.vector_available = False
            return {}

        try:
            qvecs = self.embedder.embed([query])
        except Exception as e:
            logger.warning("Router query embedding unavailable, using lexical-only retrieval: %s", e)
            self.vector_available = False
            return {}

        if not qvecs:
            return {}

        qvec = qvecs[0]
        raw: dict[str, float] = {}

        for route_id, vec in self._vectors.items():
            score = self._cosine_similarity(qvec, vec)
            raw[route_id] = float(max(0.0, score))

        if not raw:
            return {}

        best = max(raw.values()) or 1.0
        return {k: v / best for k, v in raw.items()}

    @staticmethod
    def _priority_score(record: RouteRecord) -> float:
        try:
            raw = float(record.priority or 0.0)
        except Exception:
            raw = 0.0

        # normalizzazione leggera su range ~0..100
        return max(0.0, min(raw / 100.0, 1.0))

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        if not a or not b or len(a) != len(b):
            return 0.0

        dot = 0.0
        na = 0.0
        nb = 0.0

        for x, y in zip(a, b):
            fx = float(x)
            fy = float(y)
            dot += fx * fy
            na += fx * fx
            nb += fy * fy

        if na <= 0.0 or nb <= 0.0:
            return 0.0

        return dot / ((na ** 0.5) * (nb ** 0.5))

    @staticmethod
    def _render_record_text(record: RouteRecord) -> str:
        parts: list[str] = [
            str(record.name or "").strip(),
            str(record.title or "").strip(),
            str(record.description or "").strip(),
            " ".join([str(x).strip() for x in (record.capabilities or []) if str(x).strip()]),
            " ".join([str(x).strip() for x in (record.tags or []) if str(x).strip()]),
            " ".join([str(x).strip() for x in (record.example_queries or []) if str(x).strip()]),
        ]
        return "\n".join([p for p in parts if p])
