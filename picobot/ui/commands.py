from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from picobot.session.manager import SessionManager


@dataclass(slots=True)
class CommandResult:
    handled: bool
    should_exit: bool = False
    text: str | None = None
    bus_text: str | None = None


HELP_TEXT = """Comandi disponibili

Sistema
  /help
  /exit
  /status
  /tools

Memoria
  /mem
  /mem tail
  /mem summary
  /mem facts

KB
  /kb
  /kb list
  /kb use <name>
  /kb ingest <path>
  /kb query <testo>

Shortcut
  /news <query>
  /yt <url>
  /python <code>
  /tts <testo>
"""


def _read_text(path: Path) -> str:
    if not path.exists():
        return "(vuoto)"
    data = path.read_text(encoding="utf-8").strip()
    return data or "(vuoto)"


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

    sessions = SessionManager(workspace)
    session = sessions.get(session_id)

    if text in {"/exit", "/quit"}:
        return CommandResult(handled=True, should_exit=True)

    if text == "/help":
        return CommandResult(handled=True, text=HELP_TEXT)

    if text == "/status":
        sandbox = getattr(getattr(cfg, "sandbox", None), "runtime", None)
        ollama = getattr(cfg, "ollama", None)
        kb_name = str(session.get_state().get("kb_name") or getattr(cfg, "default_kb_name", "default"))
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
        names = sorted(orchestrator.tools.list())
        return CommandResult(handled=True, text="Tools registrati:\n- " + "\n- ".join(names))

    if text == "/mem":
        state = session.get_state()
        return CommandResult(
            handled=True,
            text="Session state:\n" + json.dumps(state, indent=2, ensure_ascii=False),
        )

    if text == "/mem tail":
        try:
            return CommandResult(handled=True, text=_read_text(session.history_file))
        except Exception as exc:
            return CommandResult(handled=True, text=f"Errore /mem tail: {exc}")

    if text == "/mem summary":
        try:
            return CommandResult(handled=True, text=_read_text(session.summary_file))
        except Exception as exc:
            return CommandResult(handled=True, text=f"Errore /mem summary: {exc}")

    if text == "/mem facts":
        try:
            return CommandResult(handled=True, text=_read_text(session.facts_file))
        except Exception as exc:
            return CommandResult(handled=True, text=f"Errore /mem facts: {exc}")

    if text == "/kb":
        state = session.get_state()
        kb_name = str(state.get("kb_name") or getattr(cfg, "default_kb_name", "default"))
        return CommandResult(handled=True, text=f"KB attiva: {kb_name}")

    if text == "/kb list":
        docs_root = Path(workspace) / "docs"
        names = []
        if docs_root.exists():
            names = sorted([p.name for p in docs_root.iterdir() if p.is_dir()])
        return CommandResult(handled=True, text="KB disponibili:\n- " + ("\n- ".join(names) if names else "(nessuna)"))

    if text.startswith("/kb use "):
        name = text[len("/kb use "):].strip()
        if not name:
            return CommandResult(handled=True, text="Uso: /kb use <name>")
        session.set_state({"kb_name": name})
        return CommandResult(handled=True, text=f"KB attiva impostata a: {name}")

    if text.startswith("/kb ingest "):
        arg = text[len("/kb ingest "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /kb ingest <path>")
        return CommandResult(handled=True, bus_text=f"/kb ingest {arg}")

    if text.startswith("/kb query "):
        arg = text[len("/kb query "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /kb query <testo>")
        return CommandResult(handled=True, bus_text=arg)

    if text.startswith("/news "):
        arg = text[len("/news "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /news <query>")
        return CommandResult(handled=True, bus_text=f"/news {arg}")

    if text.startswith("/yt "):
        arg = text[len("/yt "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /yt <youtube-url>")
        return CommandResult(handled=True, bus_text=f"riassumi questo video {arg}")

    if text.startswith("/python "):
        arg = text[len("/python "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /python <code>")
        return CommandResult(handled=True, bus_text=f"python: {arg}")

    if text.startswith("/tts "):
        arg = text[len("/tts "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /tts <testo>")
        return CommandResult(handled=True, bus_text=f'tts "{arg}"')

    return CommandResult(handled=True, text=f"Comando sconosciuto: {text}\nUsa /help")
