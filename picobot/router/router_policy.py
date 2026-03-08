from __future__ import annotations

import json
import re

from picobot.router.schemas import RouteCandidate, RouteDecision, SessionRouteContext
from picobot.runtime_config import cfg_get

_EXPLICIT_TOOL_RX = re.compile(
    r"^\s*tool\s+([a-zA-Z0-9_:-]+)\s+(\{.*\})\s*$",
    re.DOTALL,
)

_NEWS_COMMAND_RX = re.compile(r"^\s*/news(?:\s+.*)?$", re.IGNORECASE)
_PY_COMMAND_RX = re.compile(r"^\s*/py(?:thon)?\b", re.IGNORECASE)
_FILE_COMMAND_RX = re.compile(r"^\s*/file\b", re.IGNORECASE)
_FETCH_COMMAND_RX = re.compile(r"^\s*/fetch\b", re.IGNORECASE)
_KB_INGEST_COMMAND_RX = re.compile(r"^\s*/kb\s+ingest\b", re.IGNORECASE)
_PODCAST_COMMAND_RX = re.compile(r"^\s*/podcast\b", re.IGNORECASE)

_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)


def _extract_explicit_tool(text: str) -> tuple[str, dict] | None:
    match = _EXPLICIT_TOOL_RX.match(text or "")
    if not match:
        return None

    tool_name = match.group(1).strip()
    raw_args = match.group(2).strip()

    try:
        data = json.loads(raw_args)
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}

    return tool_name, data


def _candidate_score(candidate: RouteCandidate) -> float:
    """
    RouteCandidate nel router reale usa final_score.
    Manteniamo fallback difensivo per evitare altri mismatch futuri.
    """
    for attr in ("final_score", "score", "combined_score"):
        value = getattr(candidate, attr, None)
        if value is not None:
            try:
                return float(value)
            except Exception:
                pass
    return 0.0


class RouterPolicy:
    def __init__(self) -> None:
        self.accept_threshold = float(cfg_get("router.accept_threshold", 0.52))
        self.margin = float(cfg_get("router.margin", 0.08))

    def _explicit_decision(self, text: str) -> RouteDecision | None:
        raw = text or ""
        stripped = raw.strip()

        explicit_tool = _extract_explicit_tool(stripped)
        if explicit_tool is not None:
            tool_name, args = explicit_tool
            return RouteDecision(
                action="tool",
                name=tool_name,
                reason="explicit tool call",
                args=args,
                score=1.0,
                candidates=[],
            )

        if _NEWS_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="news_digest",
                reason="explicit /news command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _PY_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="python",
                reason="explicit /py command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _FILE_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="file",
                reason="explicit /file command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _FETCH_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="web",
                reason="explicit /fetch command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _KB_INGEST_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="kb_ingest_pdf",
                reason="explicit /kb ingest command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _PODCAST_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="podcast",
                reason="explicit /podcast command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _YT_RX.search(stripped):
            return RouteDecision(
                action="workflow",
                name="youtube_summarizer",
                reason="youtube url detected",
                args={},
                score=1.0,
                candidates=[],
            )

        return None

    def _apply_constraints(
        self,
        candidates: list[RouteCandidate],
        ctx: SessionRouteContext,
    ) -> list[RouteCandidate]:
        out: list[RouteCandidate] = []

        for candidate in candidates:
            record = candidate.record

            if record.requires_kb and (not ctx.has_kb or not ctx.kb_enabled):
                continue

            out.append(candidate)

        return out

    def decide(
        self,
        *,
        user_text: str,
        candidates: list[RouteCandidate],
        ctx: SessionRouteContext,
    ) -> RouteDecision:
        explicit = self._explicit_decision(user_text)
        if explicit is not None:
            return explicit

        filtered = self._apply_constraints(candidates, ctx)

        if not filtered:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason="no eligible candidates",
                args={},
                score=0.0,
                candidates=[],
            )

        filtered = sorted(filtered, key=_candidate_score, reverse=True)
        top1 = filtered[0]
        top2 = filtered[1] if len(filtered) > 1 else None

        top1_score = _candidate_score(top1)
        top2_score = _candidate_score(top2) if top2 is not None else None

        if top1_score < self.accept_threshold:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason=f"top score below threshold ({top1_score:.3f} < {self.accept_threshold:.3f})",
                args={},
                score=top1_score,
                candidates=filtered,
            )

        if top2 is not None and top2_score is not None and (top1_score - top2_score) < self.margin:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason=f"ambiguous top candidates (margin {(top1_score - top2_score):.3f} < {self.margin:.3f})",
                args={},
                score=top1_score,
                candidates=filtered,
            )

        record = top1.record
        action = "tool" if record.kind == "tool" else "workflow"

        return RouteDecision(
            action=action,
            name=record.name,
            reason=f"selected top candidate: {record.id}",
            args={},
            score=top1_score,
            candidates=filtered,
        )
