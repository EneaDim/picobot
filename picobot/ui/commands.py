from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
import uuid


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

        gs = getattr(session, "get_state", None)
        ss = getattr(session, "set_state", None)
        if callable(gs) and callable(ss):
            st = gs() or {}
            for k in ("kb_name", "last_tool", "last_route", "session_summary"):
                st.pop(k, None)
            ss(st)

        return ok
    except Exception:
        pass

    for meth in ("clear_memory", "reset_memory", "forget_all", "memory_clear"):
        fn = getattr(session, meth, None)
        if callable(fn):
            try:
                fn()
                return True
            except Exception:
                pass

    return False


def _find_recent_podcasts(cfg, limit: int = 10) -> list[Path]:
    pcfg = getattr(cfg, "podcast", None)
    out_dir = Path(getattr(pcfg, "output_dir", "outputs/podcasts") if pcfg else "outputs/podcasts").expanduser()
    if not out_dir.exists():
        return []
    cands: list[Path] = []
    for p in out_dir.glob("*/podcast.*"):
        if p.is_file():
            cands.append(p)
    for p in out_dir.glob("podcast.*"):
        if p.is_file():
            cands.append(p)
    cands = sorted(set(cands), key=lambda x: x.stat().st_mtime, reverse=True)
    return cands[: max(1, int(limit))]


def handle_command(
    text: str,
    *,
    session: Any = None,
    session_manager: Any = None,
    cfg: Any = None,
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
            "/podcast list            (list recent podcasts)\n"
            "/podcast play [path]     (show latest podcast path or given path)\n"
        )
        return CommandResult(handled=True, reply=reply)

    if cmd == "/ping":
        return CommandResult(handled=True, reply="Pong!")

    if cmd == "/podcast":
        if not args:
            return CommandResult(handled=True, reply="Usage: /podcast list | /podcast play [path]")
        if args[0] == "list":
            if cfg is None:
                return CommandResult(handled=True, reply="Config not available for listing podcasts.")
            items = _find_recent_podcasts(cfg, limit=10)
            if not items:
                return CommandResult(handled=True, reply="(no podcasts found)")
            return CommandResult(handled=True, reply="Recent podcasts:\n" + "\n".join(f"- {p}" for p in items))
        if args[0] == "play":
            # In shared handler we only return the path; CLI will actually play audio.
            if len(args) >= 2:
                ap = Path(" ".join(args[1:])).expanduser()
                if not ap.exists():
                    return CommandResult(handled=True, reply=f"❌ not found: {ap}")
                return CommandResult(handled=True, reply=f"▶️ {ap}")
            if cfg is None:
                return CommandResult(handled=True, reply="Config not available for finding latest podcast.")
            items = _find_recent_podcasts(cfg, limit=1)
            if not items:
                return CommandResult(handled=True, reply="(no podcasts found)")
            return CommandResult(handled=True, reply=f"▶️ {items[0]}")
        return CommandResult(handled=True, reply="Usage: /podcast list | /podcast play [path]")

    # Session commands
    if cmd == "/session":
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
            return CommandResult(handled=True, reply="Could not clear session memory (Session API mismatch).")

        return CommandResult(handled=True, reply="Usage: /memory clear")

    return CommandResult(handled=True, reply=f"Unknown command: {cmd}. Try /help")
