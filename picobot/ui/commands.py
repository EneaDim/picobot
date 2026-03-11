from __future__ import annotations

from pathlib import Path

import picobot.ui.command_helpers as command_helpers
from picobot.routing.deterministic import route_json_one_line
from picobot.ui.command_catalog import HELP_TEXT

# Backward-compatible re-exports for older tests/monkeypatch paths.
from picobot.retrieval.ingest import ingest_kb  # noqa: F401
from picobot.retrieval.query import query_kb  # noqa: F401
from picobot.ui.command_handlers_kb import dispatch_kb_command
from picobot.ui.command_handlers_mem import dispatch_mem_command
from picobot.ui.command_helpers import active_kb_name, list_registered_tools, load_session
from picobot.ui.command_models import CommandResult


_LOCAL_ONLY_COMMANDS = {
    "/help",
    "/status",
    "/tools",
    "/mem",
    "/mem tail",
    "/mem summary",
    "/mem facts",
    "/mem clean",
    "/kb",
    "/kb list",
}

_LOCAL_PREFIXES = (
    "/kb use ",
    "/kb ingest ",
    "/kb query ",
    "/route ",
)

_PASSTHROUGH_PREFIXES = (
    "/news",
    "/yt",
    "/python",
    "/py",
    "/tts",
    "/fetch",
    "/file",
    "/stt",
    "/podcast",
)


def _is_local_command(text: str) -> bool:
    if text in _LOCAL_ONLY_COMMANDS:
        return True
    return any(text.startswith(prefix) for prefix in _LOCAL_PREFIXES)


def _is_passthrough_command(text: str) -> bool:
    return any(text == prefix or text.startswith(prefix + " ") for prefix in _PASSTHROUGH_PREFIXES)


def _handle_route_command(*, text: str, session, default_language: str) -> CommandResult:
    arg = text[len("/route "):].strip()
    if not arg:
        return CommandResult(handled=True, text="Uso: /route <testo>")

    payload = route_json_one_line(
        user_text=arg,
        state_file=session.state_file,
        default_language=default_language,
    )
    return CommandResult(handled=True, text=payload)


def handle_local_command(
    *,
    raw_text: str,
    cfg,
    workspace: Path,
    session_id: str,
    orchestrator=None,
) -> CommandResult:
    text = (raw_text or "").strip()
    if not text.startswith("/"):
        return CommandResult(handled=False)

    session = load_session(workspace=workspace, session_id=session_id)

    # Compat: i test monkeypatchano ancora picobot.ui.commands.ingest_kb/query_kb.
    # Riallineiamo i riferimenti usati dai helper KB al valore corrente di questo modulo.
    command_helpers.ingest_kb = ingest_kb
    command_helpers.query_kb = query_kb

    if text in {"/exit", "/quit"}:
        return CommandResult(handled=True, should_exit=True)

    if text == "/help":
        return CommandResult(handled=True, text=HELP_TEXT)

    if text == "/status":
        sandbox = getattr(getattr(cfg, "sandbox", None), "runtime", None)
        ollama = getattr(cfg, "ollama", None)
        kb_name = active_kb_name(cfg=cfg, session=session)
        lines = [
            "Stato runtime",
            f"- workspace: {workspace}",
            f"- session_id: {session_id}",
            f"- kb attiva: {kb_name}",
            f"- ollama base_url: {getattr(ollama, 'base_url', None)}",
            f"- ollama model: {getattr(ollama, 'model', None)}",
            f"- sandbox backend: {getattr(sandbox, 'backend', None)}",
        ]
        return CommandResult(handled=True, text="\n".join(lines))

    if text == "/tools":
        if orchestrator is None:
            return CommandResult(handled=True, text="Tool registry non disponibile.")
        return CommandResult(handled=True, text=list_registered_tools(orchestrator))

    if text.startswith("/route "):
        return _handle_route_command(
            text=text,
            session=session,
            default_language=getattr(cfg, "default_language", "it"),
        )

    if text == "/route":
        return CommandResult(handled=True, text="Uso: /route <testo>")

    result = dispatch_mem_command(
        text=text,
        cfg=cfg,
        workspace=Path(workspace),
        session=session,
    )
    if result is not None:
        return result

    result = dispatch_kb_command(
        text=text,
        cfg=cfg,
        workspace=Path(workspace),
        session=session,
    )
    if result is not None:
        return result

    if _is_passthrough_command(text):
        return CommandResult(handled=True, bus_text=text)

    if _is_local_command(text):
        return CommandResult(handled=True, text=f"Comando locale non supportato: {text}")

    # Forward di default per mantenere la CLI quasi paritetica con Telegram.
    return CommandResult(
        handled=True,
        bus_text=text,
        text=None,
    )


def handle_command(
    raw_text: str,
    *,
    cfg,
    workspace: Path,
    session_id: str = "default",
    orchestrator=None,
    **_: object,
) -> CommandResult:
    return handle_local_command(
        raw_text=raw_text,
        cfg=cfg,
        workspace=workspace,
        session_id=session_id,
        orchestrator=orchestrator,
    )
