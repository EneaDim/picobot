from __future__ import annotations

import atexit
import json
from pathlib import Path

from picobot.prompts import detect_language
from picobot.routing.router_service import RouterService
from picobot.routing.schemas import RouteDecision, SessionRouteContext

_router: RouterService | None = None


def _get_router() -> RouterService:
    """
    Inizializzazione lazy del router di processo.
    Evita side effects pesanti a import-time e permette close ordinato.
    """
    global _router

    if _router is None:
        _router = RouterService()

    return _router


def _close_router() -> None:
    """
    Cleanup esplicito a fine processo.
    """
    global _router

    if _router is not None:
        try:
            _router.close()
        except Exception:
            pass
        _router = None


atexit.register(_close_router)


def _session_ctx_from_state_file(state_file: Path, input_lang: str) -> SessionRouteContext:
    kb_name = ""
    kb_enabled = True

    try:
        if Path(state_file).exists():
            data = json.loads(Path(state_file).read_text(encoding="utf-8"))
            if isinstance(data, dict):
                kb_name = str(data.get("kb_name") or "").strip()
                if "kb_enabled" in data:
                    kb_enabled = bool(data.get("kb_enabled"))
    except Exception:
        kb_name = ""
        kb_enabled = True

    return SessionRouteContext(
        kb_name=kb_name,
        kb_enabled=kb_enabled,
        has_kb=bool(kb_name),
        input_lang=input_lang or "it",
    )


def deterministic_route(
    user_text: str,
    state_file: Path,
    default_language: str = "it",
) -> RouteDecision:
    lang = detect_language((user_text or "").strip(), default=default_language)
    ctx = _session_ctx_from_state_file(state_file, lang)
    router = _get_router()
    return router.route(user_text, ctx)


def route_json_one_line(
    user_text: str,
    state_file: Path,
    default_language: str = "it",
) -> str:
    lang = detect_language((user_text or "").strip(), default=default_language)
    ctx = _session_ctx_from_state_file(state_file, lang)
    router = _get_router()
    return router.route_json_one_line(user_text, ctx)
