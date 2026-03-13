from __future__ import annotations

import logging

from picobot.runtime_config import cfg_get
from picobot.services.search_backend import SearchResult, WebSearchUnavailableError
from picobot.services.searxng_backend import SearxngBackend

logger = logging.getLogger(__name__)


class WebSearchService:
    """
    Facade ordinata per la ricerca web locale.

    Il runtime e i tool non devono conoscere SearXNG direttamente.
    Questa versione è resiliente:
    - normalizza input
    - prova fallback sensati
    - evita di far esplodere tutto il workflow news se il backend locale fallisce
    """

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg
        self.backend_name = str(self._cfg("web_search.backend", "searxng") or "searxng").strip().lower()
        self.raise_on_error = bool(self._cfg("web_search.raise_on_error", False))
        self.default_max_results = int(self._cfg("web_search.max_results", 5) or 5)
        self.backend = self._build_backend()

    def _cfg(self, path: str, default):
        if self.cfg is not None:
            current = self.cfg
            for part in path.split("."):
                if hasattr(current, part):
                    current = getattr(current, part)
                else:
                    return cfg_get(path, default)
            return current
        return cfg_get(path, default)

    def _build_backend(self):
        if self.backend_name == "searxng":
            return SearxngBackend(self.cfg)
        raise WebSearchUnavailableError(f"backend di ricerca web non supportato: {self.backend_name}")

    def _normalize_count(self, count: int | None) -> int:
        try:
            value = int(count if count is not None else self.default_max_results)
        except Exception:
            value = self.default_max_results
        return max(1, min(value, 10))

    def _normalize_language(self, language: str | None) -> str:
        raw = str(language or "").strip().lower()
        if not raw or raw == "auto":
            return "auto"
        if raw.startswith("it"):
            return "it"
        if raw.startswith("en"):
            return "en"
        return raw

    def _safe_backend_search(
        self,
        *,
        query: str,
        count: int,
        category: str,
        language: str,
    ) -> list[SearchResult]:
        try:
            return self.backend.search(
                query=query,
                count=count,
                category=category,
                language=language,
            )
        except WebSearchUnavailableError as exc:
            logger.warning(
                "Web search backend unavailable",
                extra={
                    "query": query,
                    "category": category,
                    "language": language,
                    "backend": self.backend_name,
                    "error": str(exc),
                },
            )
            if self.raise_on_error:
                raise
            return []
        except Exception as exc:
            logger.exception(
                "Unexpected web search backend failure",
                extra={
                    "query": query,
                    "category": category,
                    "language": language,
                    "backend": self.backend_name,
                },
            )
            if self.raise_on_error:
                raise WebSearchUnavailableError(str(exc)) from exc
            return []

    def search(
        self,
        *,
        query: str,
        count: int | None = None,
        category: str = "general",
        language: str = "auto",
    ) -> list[SearchResult]:
        q = str(query or "").strip()
        if not q:
            return []

        limit = self._normalize_count(count)
        lang = self._normalize_language(language)
        cat = str(category or "general").strip().lower() or "general"

        results = self._safe_backend_search(
            query=q,
            count=limit,
            category=cat,
            language=lang,
        )
        if results:
            return results

        # Fallback sensato: se la category news fallisce o non produce nulla,
        # prova general invece di interrompere il workflow.
        if cat == "news":
            fallback_results = self._safe_backend_search(
                query=q,
                count=limit,
                category="general",
                language=lang,
            )
            if fallback_results:
                return fallback_results

        return []

    def search_general(
        self,
        *,
        query: str,
        count: int | None = None,
        language: str = "auto",
    ) -> list[SearchResult]:
        return self.search(
            query=query,
            count=count,
            category="general",
            language=language,
        )

    def search_news(
        self,
        *,
        query: str,
        count: int | None = None,
        language: str = "auto",
    ) -> list[SearchResult]:
        return self.search(
            query=query,
            count=count,
            category="news",
            language=language,
        )
