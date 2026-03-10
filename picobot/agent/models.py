from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

StatusCb = Callable[[str], Awaitable[None]]
HookCb = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(slots=True)
class RuntimeHooks:
    on_route_selected: HookCb | None = None
    on_context_built: HookCb | None = None
    on_tool_started: HookCb | None = None
    on_tool_completed: HookCb | None = None
    on_tool_failed: HookCb | None = None
    on_retrieval_started: HookCb | None = None
    on_retrieval_completed: HookCb | None = None
    on_memory_updated: HookCb | None = None
    on_audio_generated: HookCb | None = None


@dataclass(slots=True)
class TurnResult:
    content: str
    action: str
    reason: str
    score: float = 0.0
    retrieval_hits: int = 0
    audio_path: str | None = None
    script: str | None = None

    route_name: str | None = None
    route_action: str | None = None
    route_reason: str | None = None
    route_score: float = 0.0
    route_candidates: list[str] | None = None
