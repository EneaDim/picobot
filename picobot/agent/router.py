from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RouteDecision:
    action: str  # "chat" | "kb_query" | "tool"
    kb_mode: str  # "keep" | "auto"
    reason: str



    @property
    def mode(self) -> str:
        # backward-compat: older code/tests expected .mode
        return self.action
_KB_SIGNALS = [
    "doc", "docs", "document", "documento", "pdf", "kb", "knowledge base",
    "manual", "spec", "datasheet", "verilator", "--kb", "--doc",
]

_FOLLOWUP_SIGNALS = [
    "more detail", "more details", "tell me more", "which formats", "what about",
    "continue", "go on", "elaborate",
    "più dettagli", "continua", "vai avanti", "approfondisci", "quali formati",
]


_YT_URL_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)
_PDF_INGEST_RX = re.compile(r"\b(ingest|import|add)\b.*\b(pdf)\b", re.IGNORECASE)


def _load_state(state_file: Path) -> dict:
    try:
        if state_file.exists():
            return json.loads(state_file.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _save_state(state_file: Path, state: dict) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def deterministic_route(user_text: str, state_file: Path) -> RouteDecision:
    text = (user_text or "").strip()
    low = text.lower()
    state = _load_state(state_file)
    last_action = state.get("last_action", "chat")

    # Very short heuristic (nice for debug + stability)
    if len(low.split()) <= 1 and len(low) <= 8:
        state["last_action"] = "chat"
        _save_state(state_file, state)
        return RouteDecision(action="chat", kb_mode="keep", reason="very short")

    # Tool signals
    if _YT_URL_RX.search(low):
        state["last_action"] = "tool"
        state["last_tool"] = "yt_summary"
        _save_state(state_file, state)
        return RouteDecision(action="tool", kb_mode="keep", reason="youtube url")

    if _PDF_INGEST_RX.search(low):
        state["last_action"] = "tool"
        state["last_tool"] = "kb_ingest_pdf"
        _save_state(state_file, state)
        return RouteDecision(action="tool", kb_mode="keep", reason="pdf ingest")

# Hard KB signals
    if any(sig in low for sig in _KB_SIGNALS):
        state["last_action"] = "kb_query"
        _save_state(state_file, state)
        return RouteDecision(action="kb_query", kb_mode="auto", reason="document question")

    # Follow-up stickiness
    if last_action == "kb_query" and any(sig in low for sig in _FOLLOWUP_SIGNALS):
        state["last_action"] = "kb_query"
        _save_state(state_file, state)
        return RouteDecision(action="kb_query", kb_mode="keep", reason="follow-up")

    state["last_action"] = "chat"
    _save_state(state_file, state)
    return RouteDecision(action="chat", kb_mode="keep", reason="default")
