from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from picobot.prompts import detect_language
from picobot.routing.deterministic import deterministic_route
from picobot.session.manager import Session


@dataclass(slots=True)
class RouteSelectionResult:
    lang: str
    route_name: str | None
    route_action: str | None
    route_reason: str | None
    route_score: float
    route_candidates: list[str]
    raw_decision: Any


def _format_candidates(decision: Any, limit: int = 3) -> list[str]:
    out: list[str] = []
    for idx, cand in enumerate(list(getattr(decision, "candidates", []) or [])[:limit], start=1):
        record = getattr(cand, "record", None)
        name = getattr(record, "name", "?")
        kind = getattr(record, "kind", "?")
        score = getattr(cand, "final_score", 0.0)
        out.append(f"{idx}. {kind}:{name} score={float(score):.3f}")
    return out


class RouteSelectionService:
    """
    Boundary esplicito per la route selection.

    Oggi usa ancora deterministic_route(...) sotto, quindi non cambia
    il comportamento reale del router.
    Ma isola il turn pipeline dal dettaglio di implementazione.
    """

    def __init__(self, *, default_language: str = "it") -> None:
        self.default_language = default_language

    def select(self, *, session: Session, user_text: str) -> RouteSelectionResult:
        text = (user_text or "").strip()
        lang = detect_language(text, default=self.default_language)

        decision = deterministic_route(
            user_text=text,
            state_file=session.state_file,
            default_language=lang,
        )

        return RouteSelectionResult(
            lang=lang,
            route_name=getattr(decision, "name", None),
            route_action=getattr(decision, "action", None),
            route_reason=getattr(decision, "reason", None),
            route_score=float(getattr(decision, "score", 0.0) or 0.0),
            route_candidates=_format_candidates(decision),
            raw_decision=decision,
        )
