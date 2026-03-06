from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryHit:
    chunk_id: str
    score: float
    text: str
    source_file: str
    page: int | None = None
    section: str = ""


@dataclass(frozen=True)
class QueryResult:
    hits: list[QueryHit]
    context: str
    max_score: float = 0.0
