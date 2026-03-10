from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.query import query_kb
from picobot.retrieval.store import copy_source_file, list_kbs, sanitize_kb_name
from picobot.memory.manager import make_memory_manager
from picobot.session.manager import SessionManager


@dataclass(slots=True)
class CommandResult:
    handled: bool
    should_exit: bool = False
    text: str | None = None
    bus_text: str | None = None

    @property
    def reply(self) -> str | None:
        """Backward-compatible alias used by older tests/callers."""
        return self.text


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
  /mem clean

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


def _active_kb_name(*, cfg, session) -> str:
    state = session.get_state()
    default_name = getattr(getattr(cfg, "kb", None), "default_name", None)
    if not default_name:
        default_name = getattr(cfg, "default_kb_name", "default")
    return sanitize_kb_name(str(state.get("kb_name") or default_name or "default"))


def _format_kb_query_result(*, kb_name: str, query: str, result) -> str:
    lines = [
        f"KB query result [{kb_name}]",
        f"- query: {query}",
        f"- hits: {len(result.hits)}",
        f"- max_score: {result.max_score:.4f}",
    ]

    if result.hits:
        lines.append("- top results:")
        for idx, hit in enumerate(result.hits, start=1):
            snippet = " ".join((hit.text or "").split())
            if len(snippet) > 160:
                snippet = snippet[:157].rstrip() + "..."

            page = ""
            if hit.page_start is not None and hit.page_end is not None:
                page = (
                    f" p.{hit.page_start}"
                    if hit.page_start == hit.page_end
                    else f" p.{hit.page_start}-{hit.page_end}"
                )

            lines.append(
                f"  {idx}. {hit.source_file}{page} | score={hit.fused_score:.4f} | {snippet}"
            )
    else:
        lines.append("- top results: (nessuno)")

    context = (result.context or "").strip()
    if context:
        lines.append("")
        lines.append("Context:")
        lines.append(context)

    return "\n".join(lines)


def _handle_kb_ingest(*, arg: str, cfg, workspace: Path, session) -> CommandResult:
    src = Path(arg).expanduser()
    if not src.is_absolute():
        src = (Path.cwd() / src).resolve()
    else:
        src = src.resolve()

    if not src.exists() or not src.is_file():
        return CommandResult(handled=True, text=f"File non trovato: {src}")

    if src.suffix.lower() != ".pdf":
        return CommandResult(handled=True, text="/kb ingest supporta solo file PDF")

    kb_name = _active_kb_name(cfg=cfg, session=session)

    try:
        copied = copy_source_file(workspace, kb_name, src)
        result = ingest_kb(workspace=workspace, kb_name=kb_name)
    except Exception as exc:
        return CommandResult(handled=True, text=f"Errore /kb ingest: {exc}")

    lines = [
        f"KB ingest completato [{result.kb_name}]",
        f"- source file copiato: {copied}",
        f"- source_files: {result.source_files}",
        f"- chunk_files: {result.chunk_files}",
        f"- indexed_points: {result.indexed_points}",
        f"- manifest: {result.manifest_path}",
    ]
    return CommandResult(handled=True, text="\n".join(lines))


def _handle_mem_clean(*, cfg, workspace: Path, session) -> CommandResult:
    try:
        mm = make_memory_manager(cfg, session, workspace)
        mm.clear_all()
    except Exception as exc:
        return CommandResult(handled=True, text=f"Errore /mem clean: {exc}")

    lines = [
        "Memoria della chat ripulita.",
        "- state.json: reset",
        "- HISTORY.md / history.jsonl: svuotati",
        "- SUMMARY.md / summary.json: reset",
        "- MEMORY.md / facts.jsonl: svuotati",
    ]
    return CommandResult(handled=True, text="\n".join(lines))


def _handle_kb_query(*, arg: str, cfg, workspace: Path, session) -> CommandResult:
    query = (arg or "").strip()
    if not query:
        return CommandResult(handled=True, text="Uso: /kb query <testo>")

    kb_name = _active_kb_name(cfg=cfg, session=session)

    try:
        result = query_kb(
            workspace=workspace,
            kb_name=kb_name,
            query=query,
            top_k=4,
        )
    except Exception as exc:
        return CommandResult(handled=True, text=f"Errore /kb query: {exc}")

    return CommandResult(
        handled=True,
        text=_format_kb_query_result(kb_name=kb_name, query=query, result=result),
    )


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
        kb_name = _active_kb_name(cfg=cfg, session=session)
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

    if text == "/mem clean":
        return _handle_mem_clean(cfg=cfg, workspace=Path(workspace), session=session)

    if text == "/kb":
        kb_name = _active_kb_name(cfg=cfg, session=session)
        return CommandResult(handled=True, text=f"KB attiva: {kb_name}")

    if text == "/kb list":
        names = list_kbs(Path(workspace))
        return CommandResult(handled=True, text="KB disponibili:\n- " + ("\n- ".join(names) if names else "(nessuna)"))

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
        return _handle_kb_ingest(arg=arg, cfg=cfg, workspace=Path(workspace), session=session)

    if text.startswith("/kb query "):
        arg = text[len("/kb query "):].strip()
        return _handle_kb_query(arg=arg, cfg=cfg, workspace=Path(workspace), session=session)

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


def handle_command(
    raw_text: str,
    *,
    cfg,
    workspace: Path,
    session_id: str = "default",
    orchestrator=None,
    **_: object,
) -> CommandResult:
    """Backward-compatible shim for older imports/tests."""
    return handle_local_command(
        raw_text=raw_text,
        cfg=cfg,
        workspace=workspace,
        session_id=session_id,
        orchestrator=orchestrator,
    )
