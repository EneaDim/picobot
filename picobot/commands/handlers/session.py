from __future__ import annotations

from pathlib import Path

from picobot.session.manager import SessionManager, sanitize_session_id
from picobot.ui.command_models import CommandResult


def _list_sessions_text(*, workspace: Path, current_session_id: str) -> str:
    sm = SessionManager(Path(workspace))
    names = sm.list()
    lines = [
        "Sessioni disponibili",
        f"- corrente: {current_session_id}",
    ]
    if names:
        lines.append("- elenco:")
        for name in names:
            marker = " *" if name == current_session_id else ""
            lines.append(f"  - {name}{marker}")
    else:
        lines.append("- elenco: (nessuna)")
    return "\n".join(lines)


def dispatch_session_command(*, text: str, workspace: Path, current_session_id: str) -> CommandResult | None:
    raw = " ".join((text or "").strip().split())

    if raw in {"/session", "/session list"}:
        return CommandResult(
            handled=True,
            text=_list_sessions_text(
                workspace=Path(workspace),
                current_session_id=current_session_id,
            ),
        )

    for prefix in ("/session use ", "/session new "):
        if raw.startswith(prefix):
            requested = raw[len(prefix):].strip()
            if not requested:
                return CommandResult(handled=True, text="Uso: /session use <id>")

            session_id = sanitize_session_id(requested)
            sm = SessionManager(Path(workspace))
            sm.get(session_id)

            return CommandResult(
                handled=True,
                text=f"Sessione attiva impostata su: {session_id}",
                new_session_id=session_id,
            )

    return None
