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
    route_source: str | None
    kb_probe_score: float | None
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


def _candidate_score(candidate: Any) -> float:
    for attr in ("final_score", "score", "combined_score"):
        value = getattr(candidate, attr, None)
        if value is not None:
            try:
                return float(value)
            except Exception:
                pass
    return 0.0


def _best_kb_probe_score(decision: Any) -> float | None:
    best: float | None = None
    for cand in list(getattr(decision, "candidates", []) or []):
        record = getattr(cand, "record", None)
        if getattr(record, "name", None) != "kb_query":
            continue
        score = _candidate_score(cand)
        if best is None or score > best:
            best = score
    return best


def _route_source(decision: Any) -> str:
    reason = str(getattr(decision, "reason", "") or "").lower()
    if "explicit" in reason:
        return "explicit"
    if "youtube url detected" in reason:
        return "heuristic"
    if "active kb question" in reason:
        return "kb_probe"
    if "selected top candidate" in reason:
        return "retriever"
    if "ambiguous" in reason or "below threshold" in reason or "no eligible" in reason:
        return "fallback"
    if getattr(decision, "action", None) == "chat":
        return "fallback"
    return "policy"


class RouteSelectionService:
    """
    Boundary esplicito per la route selection.

    Oggi usa deterministic_route(...) ma arricchisce il risultato con
    metadata di audit utili per runtime observability e sub-agent future.
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
            route_source=_route_source(decision),
            kb_probe_score=_best_kb_probe_score(decision),
            raw_decision=decision,
        )
