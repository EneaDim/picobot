from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
import uuid
from pathlib import Path


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


def _safe_new_session_id(prefix: str = "s") -> str:
    # Telegram/CLI safe: letters/digits/dash only
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


def _clear_session_memory(session: Any) -> bool:
    """Clear *session-scoped* state/history/summary for the current Session.

    Compatible with picobot.session.manager.Session:
      - HISTORY.md (per-session)
      - SUMMARY.md (per-session)
      - state.json  (per-session)

    NOTE: global memory (workspace/memory/MEMORY.md) is intentionally NOT cleared here.
    """
    if session is None:
        return False

    # Primary: picobot.session.manager.Session has these Path properties
    try:
        history_file = getattr(session, "history_file", None)
        summary_file = getattr(session, "summary_file", None)
        state_file = getattr(session, "state_file", None)

        ok = False
        if history_file is not None:
            Path(history_file).write_text("# Session History\n\n", encoding="utf-8")
            ok = True
        if summary_file is not None:
            Path(summary_file).write_text("# Session Summary\n\n", encoding="utf-8")
            ok = True
        if state_file is not None:
            Path(state_file).write_text("{}", encoding="utf-8")
            ok = True

        # Also clear selected keys if get_state/set_state exist (safe)
        gs = getattr(session, "get_state", None)
        ss = getattr(session, "set_state", None)
        if callable(gs) and callable(ss):
            st = gs() or {}
            # clear common runtime keys without breaking other state
            for k in ("kb_name", "last_tool", "last_route", "session_summary"):
                st.pop(k, None)
            ss(st)

        if ok:
            return True
    except Exception:
        pass

    # Fallback: other possible session implementations (best-effort)
    for meth in ("clear_memory", "reset_memory", "forget_all", "memory_clear"):
        fn = getattr(session, meth, None)
        if callable(fn):
            try:
                fn()
                return True
            except Exception:
                pass

    return False


def handle_command(
    text: str,
    *,
    session: Any = None,
    session_manager: Any = None,
) -> CommandResult:
    """
    Shared command handler for CLI and Telegram.

    If handled=True:
      - caller should send/print `reply`
      - if new_session_id is set, caller should switch session and (Telegram) persist mapping.
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
            "/help\n"
            "/ping\n"
            "/session                 (show current)\n"
            "/session list            (list sessions)\n"
            "/session set <id>        (switch session)\n"
            "/sessions                (list sessions)\n"
            "/use <id>                (switch session)\n"
            "/new                     (create & switch to a fresh session)\n"
            "/memory                  (show memory help)\n"
            "/memory clear            (clear session memory)\n"
        )
        return CommandResult(handled=True, reply=reply)

    if cmd == "/ping":
        return CommandResult(handled=True, reply="Pong!")

    # Session commands
    if cmd == "/session":
        # /session [list|set <id>]
        if not args:
            sid = _get_session_id(session)
            return CommandResult(handled=True, reply=sid)

        if args[0] == "list":
            ids = _list_session_ids(session_manager)
            if not ids:
                return CommandResult(handled=True, reply="No sessions found (or SessionManager does not expose listing).")
            return CommandResult(handled=True, reply="\n".join(ids))

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

    if cmd == "/new":
        # Create a fresh session id and switch
        cur = _get_session_id(session)
        prefix = cur if cur and cur != "<unknown>" else "s"
        sid = _safe_new_session_id(prefix=prefix)
        _ = _get_or_create_session(session_manager, sid)  # best-effort
        return CommandResult(handled=True, reply=f"ok (new session={sid})", new_session_id=sid)

    # Memory commands (session-scoped)
    if cmd == "/memory":
        if not args:
            return CommandResult(
                handled=True,
                reply=(
                    "Memory commands:\n"
                    "/memory clear    (clear session memory)\n"
                    "Tip: you can also use natural language like 'remember keyword paprika'."
                ),
            )

        if args[0] == "clear":
            ok = _clear_session_memory(session)
            if ok:
                return CommandResult(handled=True, reply="ok (session memory cleared)")
            return CommandResult(
                handled=True,
                reply="Could not clear session memory (Session API mismatch).",
            )

        return CommandResult(handled=True, reply="Usage: /memory clear")

    return CommandResult(handled=True, reply=f"Unknown command: {cmd}. Try /help")
