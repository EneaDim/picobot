from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from picobot.agent.prompts import detect_language


@dataclass(frozen=True)
class RouteDecision:
    action: str  # "chat" | "kb_query" | "tool"
    kb_mode: str  # "keep" | "auto"
    reason: str

    @property
    def mode(self) -> str:
        # backward-compat: older code/tests expected .mode
        return self.action


# ---------------------------------------------------------
# Signals (deterministic)
# ---------------------------------------------------------

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

_QUESTION_RX = re.compile(r"^\s*(who|what|where|when|why|how|dove|cosa|cos\xe8|come|perch\xe9|quando|chi)\b", re.I)

# Explicit tool directive:
#   tool sandbox_python {"code":"print(2+2)"}
_EXPLICIT_TOOL_RX = re.compile(r"^\s*tool\s+([a-zA-Z0-9_\-]+)\s+(\{.*\})\s*$", re.S)

# Natural sandbox shortcuts (no LLM)
_RUN_PY_RX = re.compile(r"^\s*run\s+python\s*:\s*(.+)\s*$", re.I | re.S)
_OPEN_FILE_PREVIEW_RX = re.compile(
    r"^\s*open\s+file\s+sandbox\s+preview\s+(.+?)\s*$", re.I | re.S
)

# Podcast shortcuts (no LLM)
_PODCAST_RX = re.compile(
    r"^\s*(?:/podcast\s+)?podcast(?:\s+(?:about|su))?\s*[:\-]?\s*(.+)?\s*$",
    re.I | re.S,
)


# ---------------------------------------------------------
# State (tiny, deterministic)
# ---------------------------------------------------------

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


# ---------------------------------------------------------
# Deterministic routing
# ---------------------------------------------------------

def _parse_explicit_tool(user_text: str) -> tuple[str, dict[str, Any]] | None:
    m = _EXPLICIT_TOOL_RX.match(user_text or "")
    if not m:
        return None
    name = m.group(1).strip()
    raw = m.group(2).strip()
    try:
        args = json.loads(raw)
    except Exception:
        return None
    if not isinstance(args, dict):
        return None
    return name, args


def deterministic_route(user_text: str, state_file: Path) -> RouteDecision:
    """
    Router responsibility: choose action only.
    Tool name/args are computed in route_json_one_line() (still deterministic).
    """
    text = (user_text or "").strip()
    low = text.lower()
    state = _load_state(state_file)
    last_action = state.get("last_action", "chat")
    kb_enabled = bool(state.get("kb_enabled", True))
    kb_auto = bool(state.get("kb_auto", False))

    # 0) Explicit tool always wins (deterministic)
    if _parse_explicit_tool(text):
        name_args = _parse_explicit_tool(text)
        # store the real tool name so orchestrator can resolve it deterministically
        tool_name = name_args[0] if name_args else ""
        state["last_action"] = "tool"
        state["last_tool"] = tool_name or ""
        _save_state(state_file, state)
        return RouteDecision(action="tool", kb_mode="keep", reason="explicit tool")

    # 1) Natural sandbox shortcuts
    if _RUN_PY_RX.match(text):
        state["last_action"] = "tool"
        state["last_tool"] = "sandbox_python"
        _save_state(state_file, state)
        return RouteDecision(action="tool", kb_mode="keep", reason="run python shortcut")

    if _OPEN_FILE_PREVIEW_RX.match(text):
        state["last_action"] = "tool"
        state["last_tool"] = "sandbox_file"
        _save_state(state_file, state)
        return RouteDecision(action="tool", kb_mode="keep", reason="file preview shortcut")

    # 2) Podcast shortcuts
    if low.startswith("podcast") or low.startswith("/podcast"):
        state["last_action"] = "tool"
        state["last_tool"] = "podcast"
        _save_state(state_file, state)
        return RouteDecision(action="tool", kb_mode="keep", reason="podcast shortcut")

    # 3) Very short heuristic (stable)
    if len(low.split()) <= 1 and len(low) <= 8:
        state["last_action"] = "chat"
        _save_state(state_file, state)
        return RouteDecision(action="chat", kb_mode="keep", reason="very short")

    # 4) Tool signals
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

    # 5) Hard KB signals
    if kb_enabled and any(sig in low for sig in _KB_SIGNALS):
        state["last_action"] = "kb_query"
        _save_state(state_file, state)
        return RouteDecision(action="kb_query", kb_mode="auto", reason="document question")

    # 6) Follow-up stickiness
    if kb_enabled and last_action == "kb_query" and any(sig in low for sig in _FOLLOWUP_SIGNALS):
        state["last_action"] = "kb_query"
        _save_state(state_file, state)
        return RouteDecision(action="kb_query", kb_mode="keep", reason="follow-up")

        # If KB is enabled, treat plain questions as KB queries (auto) for better recall
    if kb_enabled and kb_auto and (low.endswith("?") or _QUESTION_RX.match(text)):
        state["last_action"] = "kb_query"
        _save_state(state_file, state)
        return RouteDecision(action="kb_query", kb_mode="auto", reason="question -> kb_query")

    state["last_action"] = "chat"
    _save_state(state_file, state)
    return RouteDecision(action="chat", kb_mode="keep", reason="default")


# ---------------------------------------------------------
# JSON one-line output (deterministic contract)
# ---------------------------------------------------------

def route_json_one_line(user_text: str, state_file: Path, default_language: str = "it") -> str:
    """
    Minimal deterministic router output.

    Output MUST be a single JSON line:
      {"route":"chat"}
      {"route":"tool","tool_name":"...","args":{...}}
    """
    text = (user_text or "").strip()
    lang = detect_language(text, default=default_language)

    # A) Explicit tool directive: tool NAME {json}
    explicit = _parse_explicit_tool(text)
    if explicit:
        tool_name, args = explicit
        # ensure language present unless already specified
        if isinstance(args, dict) and "lang" not in args and "language" not in args:
            args["lang"] = lang
        return json.dumps(
            {"route": "tool", "tool_name": tool_name, "args": args},
            separators=(",", ":"),
        )

    # B) Natural sandbox shortcuts
    m_py = _RUN_PY_RX.match(text)
    if m_py:
        code = (m_py.group(1) or "").strip()
        return json.dumps(
            {"route": "tool", "tool_name": "sandbox_python", "args": {"code": code}},
            separators=(",", ":"),
        )

    m_file = _OPEN_FILE_PREVIEW_RX.match(text)
    if m_file:
        path = (m_file.group(1) or "").strip()
        return json.dumps(
            {"route": "tool", "tool_name": "sandbox_file", "args": {"op": "preview", "path": path}},
            separators=(",", ":"),
        )

    # C) Deterministic route
    d = deterministic_route(text, state_file)

    if d.action == "tool":
        st = _load_state(state_file)
        last_tool = (st.get("last_tool") or "").strip()

        # Podcast
        if last_tool == "podcast":
            m = _PODCAST_RX.match(text)
            topic = ""
            if m:
                topic = (m.group(1) or "").strip()
            if not topic:
                topic = text
            return json.dumps(
                {"route": "tool", "tool_name": "podcast", "args": {"topic": topic, "lang": lang}},
                separators=(",", ":"),
            )

        # YouTube
        if last_tool in {"yt_summary", "yt_transcript"}:
            return json.dumps(
                {"route": "tool", "tool_name": "yt_summary", "args": {"url": text, "lang": lang}},
                separators=(",", ":"),
            )

        # PDF ingest (if used)
        if last_tool == "kb_ingest_pdf":
            return json.dumps(
                {"route": "tool", "tool_name": "kb_ingest_pdf", "args": {"text": text, "lang": lang}},
                separators=(",", ":"),
            )

        # Fallback: unknown tool => chat (safe)
        return json.dumps({"route": "chat"}, separators=(",", ":"))

    if d.action == "kb_query":
        return json.dumps(
            {"route": "tool", "tool_name": "kb_query", "args": {"query": text, "lang": lang}},
            separators=(",", ":"),
        )

    return json.dumps({"route": "chat"}, separators=(",", ":"))
