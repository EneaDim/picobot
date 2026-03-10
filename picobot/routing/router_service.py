from __future__ import annotations

import logging

from picobot.routing.router_index import load_router_records
from picobot.routing.router_policy import RouterPolicy
from picobot.routing.router_retriever import RouterRetriever
from picobot.routing.schemas import RouteDecision, SessionRouteContext

logger = logging.getLogger(__name__)


class RouterService:
    def __init__(self) -> None:
        self.records = load_router_records()
        self.policy = RouterPolicy()
        self.retriever = RouterRetriever()

        try:
            self.retriever.rebuild_index(self.records)
        except Exception as e:
            logger.warning("Router retriever rebuild failed, continuing in degraded mode: %s", e)

    def route(self, user_text: str, ctx: SessionRouteContext) -> RouteDecision:
        try:
            candidates = self.retriever.retrieve(user_text, top_k=5)
        except Exception as e:
            logger.warning("Router retrieval failed, falling back to empty candidates: %s", e)
            candidates = []

        return self.policy.decide(
            user_text=user_text,
            candidates=candidates,
            ctx=ctx,
        )
