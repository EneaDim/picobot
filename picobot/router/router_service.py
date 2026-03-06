from __future__ import annotations

import json
import os
from pathlib import Path

from picobot.retrieval.query import query_kb
from picobot.router.embedder import LocalEmbedder
from picobot.router.qdrant_router_store import RouterQdrantStore
from picobot.router.reranker import LocalReranker
from picobot.router.router_index import default_router_records
from picobot.router.router_policy import RouterPolicy
from picobot.router.router_retriever import RouterRetriever
from picobot.router.schemas import RouteDecision, SessionRouteContext
from picobot.runtime_config import cfg_get


DEFAULT_WORKSPACE = Path(os.environ.get("PICOBOT_WORKSPACE", ".picobot/workspace")).resolve()


class RouterService:
    def __init__(self) -> None:
        self.records = default_router_records()
        self.store = RouterQdrantStore()
        self.embedder = LocalEmbedder()
        self.reranker = LocalReranker()
        self.retriever = RouterRetriever(store=self.store, embedder=self.embedder, reranker=self.reranker)
        self.retriever.seed_if_empty(self.records)
        self.policy = RouterPolicy()
        self.kb_probe_top_k = int(cfg_get("router.kb_probe_top_k", 2))
        self.kb_probe_threshold = float(cfg_get("router.kb_probe_threshold", 0.55))
        self.top_k = int(cfg_get("router.top_k", 5))

    def _kb_probe(self, text: str, ctx: SessionRouteContext) -> bool:
        if not ctx.has_kb or not ctx.kb_name:
            return False
        try:
            qr = query_kb(DEFAULT_WORKSPACE, ctx.kb_name, text, top_k=self.kb_probe_top_k)
            return len(qr.hits) > 0 and float(qr.max_score) >= self.kb_probe_threshold
        except Exception:
            return False

    def route(self, user_text: str, ctx: SessionRouteContext) -> RouteDecision:
        candidates = self.retriever.retrieve(user_text, top_k=self.top_k)
        return self.policy.decide(
            user_text=user_text,
            candidates=candidates,
            ctx=ctx,
            kb_probe=self._kb_probe,
        )

    def route_json_one_line(self, user_text: str, ctx: SessionRouteContext) -> str:
        d = self.route(user_text, ctx)
        payload = {
            "route": "tool" if d.action == "tool" else "workflow",
            "tool_name": d.name if d.action == "tool" else "",
            "workflow": d.name if d.action != "tool" else "",
            "args": d.args if d.action == "tool" else {},
            "score": d.score,
            "reason": d.reason,
            "lang": ctx.input_lang,
        }
        return json.dumps(payload, separators=(",", ":"))
