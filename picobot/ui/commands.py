from __future__ import annotations

from pathlib import Path

import picobot.ui.command_helpers as command_helpers
from picobot.routing.deterministic import route_json_one_line
from picobot.ui.command_catalog import HELP_TEXT

from picobot.retrieval.ingest import ingest_kb  # noqa: F401
from picobot.retrieval.query import query_kb  # noqa: F401
from picobot.session.manager import SessionManager, sanitize_session_id
from picobot.ui.command_handlers_kb import dispatch_kb_command
from picobot.ui.command_handlers_media import dispatch_media_command
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
    "/play",
    "/session",
    "/session list",
}

_LOCAL_PREFIXES = (
    "/kb use ",
    "/kb ingest ",
    "/kb query ",
    "/route ",
    "/play ",
    "/session use ",
    "/session new ",
)

_PASSTHROUGH_PREFIXES = (
    "/kb ask",
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


def _handle_session_command(*, text: str, workspace: Path, current_session_id: str) -> CommandResult | None:
    raw = " ".join((text or "").strip().split())

    if raw in {"/session", "/session list"}:
        sm = SessionManager(workspace)
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
        return CommandResult(handled=True, text="\n".join(lines))

    for prefix in ("/session use ", "/session new "):
        if raw.startswith(prefix):
            requested = raw[len(prefix):].strip()
            if not requested:
                return CommandResult(handled=True, text="Uso: /session use <id>")
            session_id = sanitize_session_id(requested)
            sm = SessionManager(workspace)
            sm.get(session_id)
            return CommandResult(
                handled=True,
                text=f"Sessione attiva impostata su: {session_id}",
                new_session_id=session_id,
            )

    return None


def handle_local_command(
    *,
    raw_text: str,
    cfg,
    workspace: Path,
    session_id: str,
    orchestrator=None,
) -> CommandResult:
    text = " ".join((raw_text or "").strip().split())
    if not text.startswith("/"):
        return CommandResult(handled=False)

    session_cmd = _handle_session_command(
        text=text,
        workspace=workspace,
        current_session_id=session_id,
    )
    if session_cmd is not None:
        return session_cmd

    session = load_session(workspace=workspace, session_id=session_id)

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
        state = session.get_state()
        last_audio_path = str(state.get("last_audio_path") or "").strip() or "-"
        lines = [
            "Stato runtime",
            f"- workspace: {workspace}",
            f"- session_id: {session_id}",
            f"- kb attiva: {kb_name}",
            f"- ultimo audio: {last_audio_path}",
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

    result = dispatch_media_command(text=text, session=session)
    if result is not None:
        return result

    result = dispatch_mem_command(
        text=text,
        cfg=cfg,
        workspace=workspace,
        session=session,
    )
    if result is not None:
        return result

    result = dispatch_kb_command(
        text=text,
        cfg=cfg,
        workspace=workspace,
        session=session,
        ingest_fn=ingest_kb,
        query_fn=query_kb,
    )
    if result is not None:
        return result

    if _is_passthrough_command(text):
        return CommandResult(handled=True, bus_text=text)

    if _is_local_command(text):
        return CommandResult(handled=True, text=f"Comando locale non supportato: {text}")

    return CommandResult(handled=True, bus_text=text, text=None)


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
