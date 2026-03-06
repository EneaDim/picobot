from __future__ import annotations

import json

from picobot.router.documents import router_records_fingerprint
from picobot.router.embedder import LocalEmbedder
from picobot.router.qdrant_router_store import RouterQdrantStore
from picobot.router.router_index import load_router_records
from picobot.router.router_policy import RouterPolicy
from picobot.router.router_retriever import RouterRetriever
from picobot.router.schemas import RouteDecision, SessionRouteContext
from picobot.runtime_config import cfg_get


class RouterService:
    def __init__(self) -> None:
        self.store = RouterQdrantStore()
        self.embedder = LocalEmbedder()
        self.retriever = RouterRetriever(store=self.store, embedder=self.embedder)
        self.policy = RouterPolicy()

        self.top_k = int(cfg_get("router.top_k", 5))

        self.records = load_router_records()
        self.records_fingerprint = router_records_fingerprint(self.records)

        self.retriever.rebuild_index(self.records)

    def close(self) -> None:
        """
        Chiusura esplicita delle risorse del router.
        """
        try:
            self.store.close()
        except Exception:
            pass

    def route(self, user_text: str, ctx: SessionRouteContext) -> RouteDecision:
        candidates = self.retriever.retrieve(
            user_text=user_text,
            top_k=max(1, self.top_k),
        )

        return self.policy.decide(
            user_text=user_text,
            candidates=candidates,
            ctx=ctx,
        )

    def route_json_one_line(self, user_text: str, ctx: SessionRouteContext) -> str:
        decision = self.route(user_text, ctx)

        payload = {
            "route": "tool" if decision.action == "tool" else "workflow",
            "tool_name": decision.name if decision.action == "tool" else "",
            "workflow": decision.name if decision.action != "tool" else "",
            "args": dict(decision.args or {}),
            "score": float(decision.score),
            "reason": decision.reason,
            "lang": ctx.input_lang,
            "router_fingerprint": self.records_fingerprint,
        }

        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
