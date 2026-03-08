from __future__ import annotations

from picobot.runtime_config import cfg_get
from picobot.services.search_backend import SearchResult, WebSearchUnavailableError
from picobot.services.searxng_backend import SearxngBackend


class WebSearchService:
    """
    Facade ordinata per la ricerca web locale.

    Il runtime e i tool non devono conoscere SearXNG.
    """

    def __init__(self, cfg=None) -> None:
        self.cfg = cfg
        self.backend_name = str(self._cfg("web_search.backend", "searxng") or "searxng").strip().lower()
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

    def search(self, *, query: str, count: int | None = None, category: str = "general", language: str = "auto") -> list[SearchResult]:
        return self.backend.search(
            query=query,
            count=count,
            category=category,
            language=language,
        )

    def search_general(self, *, query: str, count: int | None = None, language: str = "auto") -> list[SearchResult]:
        return self.search(query=query, count=count, category="general", language=language)

    def search_news(self, *, query: str, count: int | None = None, language: str = "auto") -> list[SearchResult]:
        return self.search(query=query, count=count, category="news", language=language)
