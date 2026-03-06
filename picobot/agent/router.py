from __future__ import annotations

import json
from pathlib import Path

from picobot.agent.prompts import detect_language
from picobot.router.router_service import RouterService
from picobot.router.schemas import RouteDecision, SessionRouteContext


_router = RouterService()


def _session_ctx_from_state_file(state_file: Path, input_lang: str) -> SessionRouteContext:
    kb_name = ""
    kb_enabled = True

    try:
        if state_file.exists():
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                kb_name = str(data.get("kb_name") or "")
                if "kb_enabled" in data:
                    kb_enabled = bool(data.get("kb_enabled"))
    except Exception:
        pass

    return SessionRouteContext(
        kb_name=kb_name,
        kb_enabled=kb_enabled,
        has_kb=bool(kb_name),
        input_lang=input_lang or "it",
    )


def deterministic_route(user_text: str, state_file: Path, default_language: str = "it") -> RouteDecision:
    lang = detect_language((user_text or "").strip(), default=default_language)
    ctx = _session_ctx_from_state_file(state_file, lang)
    return _router.route(user_text, ctx)


def route_json_one_line(user_text: str, state_file: Path, default_language: str = "it") -> str:
    lang = detect_language((user_text or "").strip(), default=default_language)
    ctx = _session_ctx_from_state_file(state_file, lang)
    return _router.route_json_one_line(user_text, ctx)
