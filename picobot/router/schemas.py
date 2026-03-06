from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


RouteKind = Literal["tool", "workflow", "agent"]


@dataclass(frozen=True)
class RouteRecord:
    id: str
    kind: RouteKind
    name: str
    title: str
    description: str
    capabilities: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    example_queries: list[str] = field(default_factory=list)
    requires_kb: bool = False
    requires_network: bool = False
    enabled: bool = True
    priority: int = 50
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteCandidate:
    record: RouteRecord
    vector_score: float
    rerank_score: float
    final_score: float
    reason: str


@dataclass(frozen=True)
class SessionRouteContext:
    kb_name: str = ""
    kb_enabled: bool = True
    has_kb: bool = False
    input_lang: str = "it"


@dataclass(frozen=True)
class RouteDecision:
    action: Literal["chat", "tool", "workflow"]
    name: str
    reason: str
    args: dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    candidates: list[RouteCandidate] = field(default_factory=list)
