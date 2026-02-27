from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class CommandResult:
    handled: bool
    reply: str = ""
    new_session_id: Optional[str] = None


def _get_session_id(session: Any) -> str:
    for attr in ("id", "session_id", "sid", "name"):
        v = getattr(session, attr, None)
        if isinstance(v, str) and v:
            return v
    return "<unknown>"


def _list_session_ids(sm: Any) -> list[str]:
    # Best-effort introspection across possible SessionManager APIs
    if sm is None:
        return []
    for meth in ("list_ids", "list", "sessions", "keys"):
        fn = getattr(sm, meth, None)
        if callable(fn):
            try:
                out = fn()
                if isinstance(out, dict):
                    return [str(k) for k in out.keys()]
                if isinstance(out, (list, tuple, set)):
                    return [str(x) for x in out]
            except Exception:
                pass
    # maybe stored internally
    for attr in ("_sessions", "sessions"):
        d = getattr(sm, attr, None)
        if isinstance(d, dict):
            return [str(k) for k in d.keys()]
    return []


def _get_or_create_session(sm: Any, session_id: str):
    if sm is None:
        return None
    for meth in ("get", "get_or_create", "open"):
        fn = getattr(sm, meth, None)
        if callable(fn):
            try:
                return fn(session_id)
            except Exception:
                pass
    return None


def handle_command(
    text: str,
    *,
    session: Any = None,
    session_manager: Any = None,
) -> CommandResult:
    """
    Shared command handler for CLI and Telegram.
    If handled=True, caller should send/print reply and (optionally) switch session to new_session_id.
    """
    t = (text or "").strip()
    if not t.startswith("/"):
        return CommandResult(handled=False)

    parts = t.split()
    cmd = parts[0].lower()
    args = parts[1:]

    if cmd in ("/help", "/h"):
        reply = (
            "Commands:\n"
            "/help - show this help\n"
            "/ping - pong\n"
            "/session - show current session id\n"
            "/sessions - list session ids\n"
            "/use <id> - switch session\n"
        )
        return CommandResult(handled=True, reply=reply)

    if cmd == "/ping":
        return CommandResult(handled=True, reply="Pong!")
    if cmd == "/session":
        # /session [list|set <id>]
        if not args:
            sid = _get_session_id(session)
            return CommandResult(handled=True, reply=sid)
        if args[0] == "list":
            ids = _list_session_ids(session_manager)
            if not ids:
                return CommandResult(handled=True, reply="No sessions found (or SessionManager does not expose listing).")
            return CommandResult(handled=True, reply="".join(ids))
        if args[0] == "set" and len(args) >= 2:
            sid = args[1]
            s = _get_or_create_session(session_manager, sid)
            if s is None:
                return CommandResult(handled=True, reply=f"Could not switch to session '{sid}' (SessionManager API mismatch).")
            return CommandResult(handled=True, reply=f"ok (session={sid})", new_session_id=sid)
        return CommandResult(handled=True, reply="Usage: /session [list|set <id>]")

    if cmd == "/sessions":
        ids = _list_session_ids(session_manager)
        if not ids:
            return CommandResult(handled=True, reply="No sessions found (or SessionManager does not expose listing).")
        return CommandResult(handled=True, reply="\n".join(ids))

    if cmd == "/use":
        if not args:
            return CommandResult(handled=True, reply="Usage: /use <session_id>")
        sid = args[0]
        s = _get_or_create_session(session_manager, sid)
        if s is None:
            return CommandResult(handled=True, reply=f"Could not switch to session '{sid}' (SessionManager API mismatch).")
        return CommandResult(handled=True, reply=f"ok (session={sid})", new_session_id=sid)

    return CommandResult(handled=True, reply=f"Unknown command: {cmd}. Try /help")
