from __future__ import annotations

from typing import Any

from picobot.runtime_config import cfg_get


class LocalReranker:
    def __init__(self) -> None:
        self._enabled = bool(cfg_get("router.reranker.enabled", False))

    def enabled(self) -> bool:
        return self._enabled

    def rerank(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for c in candidates:
            c["rerank_score"] = float(c.get("vector_score", 0.0))
        return sorted(candidates, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
