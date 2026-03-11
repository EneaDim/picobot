from __future__ import annotations

from pathlib import Path

from picobot.ui.command_helpers import handle_mem_clean, read_text
from picobot.ui.command_models import CommandResult


def dispatch_mem_command(*, text: str, cfg, workspace: Path, session) -> CommandResult | None:
    if text == "/mem":
        from picobot.ui.command_helpers import dump_session_state
        return CommandResult(handled=True, text=dump_session_state(session))

    if text == "/mem tail":
        try:
            return CommandResult(handled=True, text=read_text(session.history_file))
        except Exception as exc:
            return CommandResult(handled=True, text=f"Errore /mem tail: {exc}")

    if text == "/mem summary":
        try:
            return CommandResult(handled=True, text=read_text(session.summary_file))
        except Exception as exc:
            return CommandResult(handled=True, text=f"Errore /mem summary: {exc}")

    if text == "/mem facts":
        try:
            return CommandResult(handled=True, text=read_text(session.facts_file))
        except Exception as exc:
            return CommandResult(handled=True, text=f"Errore /mem facts: {exc}")

    if text == "/mem clean":
        return handle_mem_clean(cfg=cfg, workspace=workspace, session=session)

    return None
