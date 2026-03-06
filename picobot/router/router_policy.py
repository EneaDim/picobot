from __future__ import annotations

import json
import re
from typing import Callable

from picobot.router.schemas import RouteCandidate, RouteDecision, SessionRouteContext
from picobot.runtime_config import cfg_get


_EXPLICIT_TOOL_RX = re.compile(r"^\s*tool\s+([a-zA-Z0-9_\-]+)\s+(\{.*\})\s*$", re.S)
_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)
_NEWS_RX = re.compile(r"^\s*(?:/news|news:)\b", re.IGNORECASE)
_REMEMBER_RX = re.compile(r"^\s*remember\b", re.IGNORECASE)
_MEM_RECALL_RX = re.compile(
    r"\b(my favorite|mia spezia preferita|what is my|qual è la mia|do you remember|ti ricordi)\b",
    re.IGNORECASE,
)
_KB_COMMAND_RX = re.compile(r"^\s*/kb\b", re.IGNORECASE)
_MEM_COMMAND_RX = re.compile(r"^\s*/mem\b", re.IGNORECASE)
_FILE_COMMAND_RX = re.compile(r"^\s*/file\b", re.IGNORECASE)
_PY_COMMAND_RX = re.compile(r"^\s*/py\b", re.IGNORECASE)
_PODCAST_COMMAND_RX = re.compile(r"^\s*/podcast\b", re.IGNORECASE)


def _parse_explicit_tool(user_text: str) -> tuple[str, dict] | None:
    m = _EXPLICIT_TOOL_RX.match(user_text or "")
    if not m:
        return None
    try:
        args = json.loads(m.group(2))
    except Exception:
        return None
    if not isinstance(args, dict):
        return None
    return m.group(1).strip(), args


def _looks_like_python_snippet(text: str) -> bool:
    t = (text or "").strip()
    return any(x in t for x in ["print(", "for ", "while ", "def ", "import ", " = ", "lambda "])


def _is_natural_language(text: str) -> bool:
    t = (text or "").strip()
    low = t.lower()
    if not t:
        return False
    if low.startswith("/"):
        return False
    if low.startswith("tool "):
        return False
    return True


class RouterPolicy:
    def __init__(self) -> None:
        self.accept_threshold = float(cfg_get("router.accept_threshold", 0.72))
        self.margin = float(cfg_get("router.margin", 0.05))

    def decide(
        self,
        *,
        user_text: str,
        candidates: list[RouteCandidate],
        ctx: SessionRouteContext,
        kb_probe: Callable[[str, SessionRouteContext], bool] | None = None,
    ) -> RouteDecision:
        text = (user_text or "").strip()

        if _NEWS_RX.search(text):
            return RouteDecision(action="workflow", name="news_digest", reason="news command", score=1.0, candidates=candidates)

        if _KB_COMMAND_RX.search(text):
            return RouteDecision(action="workflow", name="kb_command", reason="kb command", score=1.0, candidates=candidates)

        if _MEM_COMMAND_RX.search(text):
            return RouteDecision(action="workflow", name="memory_command", reason="memory command", score=1.0, candidates=candidates)

        if _FILE_COMMAND_RX.search(text):
            return RouteDecision(action="workflow", name="file_command", reason="file command", score=1.0, candidates=candidates)

        if _PY_COMMAND_RX.search(text):
            return RouteDecision(action="workflow", name="python_command", reason="python command", score=1.0, candidates=candidates)

        if _PODCAST_COMMAND_RX.search(text):
            return RouteDecision(action="workflow", name="podcast", reason="podcast command", score=1.0, candidates=candidates)

        exp = _parse_explicit_tool(text)
        if exp:
            tool_name, args = exp
            return RouteDecision(action="tool", name=tool_name, reason="explicit tool", args=args, score=1.0, candidates=candidates)

        if _YT_RX.search(text):
            return RouteDecision(action="workflow", name="youtube_summarizer", reason="youtube url", score=1.0, candidates=candidates)

        if _REMEMBER_RX.search(text) or _MEM_RECALL_RX.search(text):
            return RouteDecision(action="workflow", name="chat", reason="memory-like natural language", score=0.95, candidates=candidates)

        if ctx.has_kb and ctx.kb_enabled and _is_natural_language(text) and not _looks_like_python_snippet(text):
            if kb_probe and kb_probe(text, ctx):
                return RouteDecision(action="workflow", name="kb_query", reason="kb probe hit", score=0.95, candidates=candidates)

        if not candidates:
            return RouteDecision(action="workflow", name="chat", reason="no candidates", score=0.0, candidates=[])

        top = candidates[0]
        second = candidates[1] if len(candidates) > 1 else None

        if top.record.requires_kb and not ctx.has_kb:
            return RouteDecision(action="workflow", name="chat", reason="top requires kb", score=top.final_score, candidates=candidates)

        if second and abs(top.final_score - second.final_score) < self.margin:
            return RouteDecision(action="workflow", name="chat", reason="ambiguous top candidates", score=top.final_score, candidates=candidates)

        if top.final_score < self.accept_threshold:
            return RouteDecision(action="workflow", name="chat", reason="low confidence", score=top.final_score, candidates=candidates)

        if top.record.kind == "tool":
            return RouteDecision(action="tool", name=top.record.name, reason=f"semantic route: {top.record.name}", args={}, score=top.final_score, candidates=candidates)

        return RouteDecision(action="workflow", name=top.record.name, reason=f"semantic route: {top.record.name}", score=top.final_score, candidates=candidates)
