from __future__ import annotations

# Questo file contiene gli oggetti dati principali del blocco retrieval.
# L'idea è semplice:
# - un formato chiaro per i chunk documentali
# - un formato chiaro per gli hit di query
# - un formato chiaro per il risultato finale
# - un formato chiaro per il risultato di ingest
#
# Uso dataclass perché:
# - sono leggere
# - leggibili
# - ottime per development locale
# - evitano oggetti "magici" inutilmente complessi

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentChunk:
    """
    Rappresenta un chunk persistito della KB.

    Campi importanti:
    - chunk_id: ID globale e stabile del chunk
    - kb_name: namespace KB
    - doc_id: identificatore del documento dentro la KB
    - source_file: nome file sorgente
    - text: testo del chunk
    - chunk_index: indice progressivo del chunk dentro il documento
    - page_start/page_end: range pagine, utile per citazioni
    - metadata: contenitore estendibile per il futuro
    """

    chunk_id: str
    kb_name: str
    doc_id: str
    source_file: str
    text: str
    chunk_index: int
    page_start: int | None = None
    page_end: int | None = None
    section: str = ""
    mime_type: str = "application/pdf"
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """
        Converte il chunk nel payload standard da salvare:
        - nei JSON chunk su filesystem
        - dentro Qdrant payload
        """
        return {
            "id": self.chunk_id,
            "chunk_id": self.chunk_id,
            "kb_name": self.kb_name,
            "doc_id": self.doc_id,
            "source_file": self.source_file,
            "text": self.text,
            "chunk_index": self.chunk_index,
            "page_start": self.page_start,
            "page_end": self.page_end,
            "section": self.section,
            "mime_type": self.mime_type,
            "metadata": dict(self.metadata or {}),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "DocumentChunk":
        """
        Ricostruisce un DocumentChunk da payload serializzato.
        """
        return cls(
            chunk_id=str(payload.get("chunk_id") or payload.get("id") or ""),
            kb_name=str(payload.get("kb_name") or ""),
            doc_id=str(payload.get("doc_id") or ""),
            source_file=str(payload.get("source_file") or ""),
            text=str(payload.get("text") or ""),
            chunk_index=int(payload.get("chunk_index") or 0),
            page_start=payload.get("page_start"),
            page_end=payload.get("page_end"),
            section=str(payload.get("section") or ""),
            mime_type=str(payload.get("mime_type") or "application/pdf"),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class LexicalHit:
    """
    Hit prodotto dal retriever lessicale BM25.
    """
    chunk_id: str
    score: float
    text: str
    source_file: str
    page_start: int | None = None
    page_end: int | None = None
    section: str = ""


@dataclass(frozen=True)
class VectorHit:
    """
    Hit prodotto dal retriever vettoriale.
    """
    chunk_id: str
    score: float
    text: str
    source_file: str
    page_start: int | None = None
    page_end: int | None = None
    section: str = ""


@dataclass(frozen=True)
class QueryHit:
    """
    Hit finale dopo fusione hybrid.

    Conserviamo:
    - fused_score: score finale dopo rank fusion
    - vector_score: score grezzo dal retriever vettoriale
    - lexical_score: score grezzo BM25
    - ranks: debug leggero utile per capire come è stato scelto il chunk
    """
    chunk_id: str
    fused_score: float
    text: str
    source_file: str
    page_start: int | None = None
    page_end: int | None = None
    section: str = ""
    vector_score: float = 0.0
    lexical_score: float = 0.0
    ranks: dict[str, int] = field(default_factory=dict)

    @property
    def score(self) -> float:
        """
        Compatibilità con il codice esistente che usa ancora .score.
        """
        return self.fused_score


@dataclass(frozen=True)
class QueryResult:
    """
    Risultato finale restituito a chi interroga la KB.
    """
    hits: list[QueryHit]
    context: str
    max_score: float = 0.0


@dataclass(frozen=True)
class IngestResult:
    """
    Risultato di una ingest KB completa.
    """
    kb_name: str
    source_files: int
    chunk_files: int
    indexed_points: int
    manifest_path: str
