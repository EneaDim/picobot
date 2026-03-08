from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class WebSearchError(RuntimeError):
    pass


class WebSearchUnavailableError(WebSearchError):
    pass


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    description: str
    source: str = ""


class SearchBackend(Protocol):
    def search(
        self,
        *,
        query: str,
        count: int | None = None,
        category: str = "general",
        language: str = "auto",
    ) -> list[SearchResult]:
        ...
