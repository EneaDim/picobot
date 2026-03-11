from __future__ import annotations

from pathlib import Path

from picobot.retrieval.store import sanitize_kb_name
from picobot.ui.command_helpers import active_kb_name, handle_kb_ingest, handle_kb_query, kb_list_text
from picobot.ui.command_models import CommandResult


def dispatch_kb_command(*, text: str, cfg, workspace: Path, session) -> CommandResult | None:
    if text == "/kb":
        kb_name = active_kb_name(cfg=cfg, session=session)
        return CommandResult(handled=True, text=f"KB attiva: {kb_name}")

    if text == "/kb list":
        return CommandResult(handled=True, text=kb_list_text(workspace))

    if text.startswith("/kb use "):
        name = text[len("/kb use "):].strip()
        if not name:
            return CommandResult(handled=True, text="Uso: /kb use <name>")
        safe_name = sanitize_kb_name(name)
        session.set_state({"kb_name": safe_name})
        return CommandResult(handled=True, text=f"KB attiva impostata a: {safe_name}")

    if text.startswith("/kb ingest "):
        arg = text[len("/kb ingest "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /kb ingest <path>")
        return handle_kb_ingest(arg=arg, cfg=cfg, workspace=Path(workspace), session=session)

    if text.startswith("/kb query "):
        arg = text[len("/kb query "):].strip()
        return handle_kb_query(arg=arg, cfg=cfg, workspace=Path(workspace), session=session)

    return None
