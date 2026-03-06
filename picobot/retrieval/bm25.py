from __future__ import annotations

# BM25 locale semplice, trasparente e persistibile.
#
# Obiettivo:
# - dare un segnale lessicale vero alla KB
# - mantenere tutto locale
# - evitare hardcoded boost ad hoc
#
# Strategia:
# - build indice durante ingest
# - salvataggio JSON in docs/<kb>/kb/index/bm25.json
# - query BM25 a runtime
#
# Non è pensato per essere "enterprise-grade".
# È pensato per essere:
# - leggibile
# - debug-friendly
# - corretto
# - sufficiente per una KB locale-first

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from picobot.retrieval.schemas import DocumentChunk, LexicalHit


_TOKEN_RX = re.compile(r"[A-Za-z0-9_àèéìòù\-]{2,}")


def tokenize(text: str) -> list[str]:
    """
    Tokenizzazione semplice e stabile.
    """
    return [tok.lower() for tok in _TOKEN_RX.findall(text or "")]


@dataclass(frozen=True)
class BM25Doc:
    """
    Documento normalizzato dentro l'indice BM25.
    """
    chunk_id: str
    text: str
    source_file: str
    page_start: int | None
    page_end: int | None
    section: str
    length: int
    tf: dict[str, int]

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "source_file": self.source_file,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "section": self.section,
            "length": self.length,
            "tf": dict(self.tf),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BM25Doc":
        return cls(
            chunk_id=str(data.get("chunk_id") or ""),
            text=str(data.get("text") or ""),
            source_file=str(data.get("source_file") or ""),
            page_start=data.get("page_start"),
            page_end=data.get("page_end"),
            section=str(data.get("section") or ""),
            length=int(data.get("length") or 0),
            tf={str(k): int(v) for k, v in dict(data.get("tf") or {}).items()},
        )


class BM25Index:
    """
    Indice BM25 persistibile.
    """

    def __init__(
        self,
        *,
        documents: list[BM25Doc],
        doc_freq: dict[str, int],
        avg_doc_len: float,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> None:
        self.documents = documents
        self.doc_freq = doc_freq
        self.avg_doc_len = float(avg_doc_len or 1.0)
        self.k1 = float(k1)
        self.b = float(b)

        # Mappa veloce chunk_id -> documento.
        self.by_chunk_id = {doc.chunk_id: doc for doc in documents}

    @classmethod
    def build(
        cls,
        chunks: list[DocumentChunk],
        *,
        k1: float = 1.5,
        b: float = 0.75,
    ) -> "BM25Index":
        """
        Costruisce l'indice BM25 a partire dai chunk della KB.
        """
        documents: list[BM25Doc] = []
        doc_freq: dict[str, int] = {}

        for chunk in chunks:
            tokens = tokenize(chunk.text)
            tf: dict[str, int] = {}

            for tok in tokens:
                tf[tok] = tf.get(tok, 0) + 1

            for tok in tf.keys():
                doc_freq[tok] = doc_freq.get(tok, 0) + 1

            documents.append(
                BM25Doc(
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    source_file=chunk.source_file,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    section=chunk.section,
                    length=len(tokens),
                    tf=tf,
                )
            )

        avg_doc_len = (
            sum(doc.length for doc in documents) / len(documents)
            if documents else 1.0
        )

        return cls(
            documents=documents,
            doc_freq=doc_freq,
            avg_doc_len=avg_doc_len,
            k1=k1,
            b=b,
        )

    def to_dict(self) -> dict:
        """
        Serializzazione completa dell'indice.
        """
        return {
            "k1": self.k1,
            "b": self.b,
            "avg_doc_len": self.avg_doc_len,
            "doc_freq": dict(self.doc_freq),
            "documents": [doc.to_dict() for doc in self.documents],
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BM25Index":
        """
        Ricostruzione da struttura JSON.
        """
        return cls(
            documents=[BM25Doc.from_dict(x) for x in list(data.get("documents") or [])],
            doc_freq={str(k): int(v) for k, v in dict(data.get("doc_freq") or {}).items()},
            avg_doc_len=float(data.get("avg_doc_len") or 1.0),
            k1=float(data.get("k1") or 1.5),
            b=float(data.get("b") or 0.75),
        )

    def save(self, path: Path) -> None:
        """
        Salva l'indice su disco in JSON.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: Path) -> "BM25Index":
        """
        Carica l'indice da disco.
        """
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"invalid bm25 index file: {path}")
        return cls.from_dict(data)

    def _idf(self, term: str) -> float:
        """
        Formula IDF BM25 classica e stabile.
        """
        n_docs = max(1, len(self.documents))
        df = int(self.doc_freq.get(term, 0))

        return math.log(1.0 + ((n_docs - df + 0.5) / (df + 0.5)))

    def search(self, query: str, top_k: int = 8) -> list[LexicalHit]:
        """
        Cerca nell'indice BM25 e restituisce i migliori chunk.
        """
        terms = tokenize(query)
        if not terms or not self.documents:
            return []

        scored: list[tuple[float, BM25Doc]] = []

        for doc in self.documents:
            score = 0.0

            for term in terms:
                tf = doc.tf.get(term, 0)
                if tf <= 0:
                    continue

                idf = self._idf(term)
                denom = tf + self.k1 * (1.0 - self.b + self.b * (doc.length / max(1.0, self.avg_doc_len)))
                part = idf * ((tf * (self.k1 + 1.0)) / max(1e-9, denom))
                score += part

            if score > 0.0:
                scored.append((score, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        scored = scored[: max(1, int(top_k))]

        return [
            LexicalHit(
                chunk_id=doc.chunk_id,
                score=float(score),
                text=doc.text,
                source_file=doc.source_file,
                page_start=doc.page_start,
                page_end=doc.page_end,
                section=doc.section,
            )
            for score, doc in scored
        ]
