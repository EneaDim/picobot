from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from picobot.agent.router import deterministic_route
from picobot.config.schema import Config
from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.store import copy_source_file, ensure_kb_dirs, list_kbs
from picobot.session.manager import Session, SessionManager, sanitize_session_id


@dataclass(frozen=True)
class CommandResult:
    handled: bool
    reply: str = ""
    new_session_id: str | None = None
    exit_requested: bool = False


def _help_text() -> str:
    return (
        "Comandi disponibili:\n"
        "\n"
        "/help\n"
        "  mostra questo aiuto\n"
        "\n"
        "/new [session_id]\n"
        "  crea o seleziona una nuova sessione\n"
        "\n"
        "/session\n"
        "/session list\n"
        "/session set <id>\n"
        "  gestione sessioni\n"
        "\n"
        "/mem show\n"
        "/mem clear\n"
        "/memory show\n"
        "/memory clear\n"
        "  mostra o pulisce memoria e storia della sessione corrente\n"
        "\n"
        "/kb\n"
        "/kb list\n"
        "/kb use <kb_name>\n"
        "/kb ingest <pdf_path>\n"
        "  gestione knowledge base locale\n"
        "\n"
        "/route <testo>\n"
        "  mostra la decisione del router\n"
        "\n"
        "/news <query>\n"
        "  rassegna news via workflow\n"
        "\n"
        "/podcast <topic>\n"
        "  genera un podcast\n"
        "\n"
        "/exit\n"
        "  esce dalla CLI\n"
    ).strip()


def _session_info(session: Session) -> str:
    state = session.get_state()
    kb_name = str(state.get("kb_name") or "").strip() or "(nessuna)"
    kb_enabled = bool(state.get("kb_enabled", True))

    return (
        f"Sessione corrente: {session.session_id}\n"
        f"KB attiva: {kb_name}\n"
        f"KB enabled: {'yes' if kb_enabled else 'no'}"
    )


def _set_session_kb(session: Session, kb_name: str) -> str:
    safe = sanitize_session_id(kb_name)
    session.set_state({"kb_name": safe, "kb_enabled": True})
    return safe


def _read_text_file(path: Path, default_header: str) -> str:
    if not path.exists():
        return default_header
    try:
        return path.read_text(encoding="utf-8").strip() or default_header
    except Exception:
        return default_header


def _show_memory(session: Session) -> str:
    memory_text = _read_text_file(session.memory_file, "# Memory")
    summary_text = _read_text_file(session.summary_file, "# Session Summary")
    history_text = _read_text_file(session.history_file, "# Session History")

    return (
        "=== MEMORY ===\n"
        f"{memory_text}\n\n"
        "=== SUMMARY ===\n"
        f"{summary_text}\n\n"
        "=== HISTORY ===\n"
        f"{history_text}"
    ).strip()


def _clear_memory(session: Session) -> str:
    session.root.mkdir(parents=True, exist_ok=True)
    session.history_file.write_text("# Session History\n\n", encoding="utf-8")
    session.summary_file.write_text("# Session Summary\n\n", encoding="utf-8")
    session.memory_file.parent.mkdir(parents=True, exist_ok=True)
    session.memory_file.write_text("# Memory\n\n", encoding="utf-8")
    return "✅ Memoria e storia pulite."


def handle_command(
    raw: str,
    *,
    session: Session,
    session_manager: SessionManager,
    cfg: Config,
    workspace: Path,
) -> CommandResult:
    text = (raw or "").strip()
    if not text.startswith("/"):
        return CommandResult(handled=False)

    parts = text.split()
    cmd = parts[0].lower()

    # Slash commands che devono passare all'orchestrator/router
    passthrough_commands = {
        "/news",
        "/podcast",
        "/py",
        "/python",
        "/file",
        "/fetch",
    }
    if cmd in passthrough_commands:
        return CommandResult(handled=False)

    if cmd in {"/help", "/start"}:
        return CommandResult(handled=True, reply=_help_text())

    if cmd in {"/exit", "/quit"}:
        return CommandResult(handled=True, reply="A presto 👋", exit_requested=True)

    if cmd == "/new":
        requested = parts[1] if len(parts) >= 2 else ""
        session_id = sanitize_session_id(requested or "session")
        if not requested:
            existing = set(session_manager.list())
            base = "session"
            idx = 1
            candidate = f"{base}-{idx}"
            while candidate in existing:
                idx += 1
                candidate = f"{base}-{idx}"
            session_id = candidate

        _ = session_manager.get(session_id)
        return CommandResult(
            handled=True,
            reply=f"✅ Nuova sessione attiva: {session_id}",
            new_session_id=session_id,
        )

    if cmd == "/session":
        if len(parts) == 1:
            return CommandResult(handled=True, reply=_session_info(session))

        sub = parts[1].lower()

        if sub == "list":
            sessions = session_manager.list()
            if not sessions:
                return CommandResult(handled=True, reply="Nessuna sessione trovata.")
            lines = ["Sessioni disponibili:", *[f"- {sid}" for sid in sessions]]
            return CommandResult(handled=True, reply="\n".join(lines))

        if sub == "set" and len(parts) >= 3:
            new_id = sanitize_session_id(parts[2])
            _ = session_manager.get(new_id)
            return CommandResult(
                handled=True,
                reply=f"✅ Sessione attiva: {new_id}",
                new_session_id=new_id,
            )

        return CommandResult(
            handled=True,
            reply="Uso: /session | /session list | /session set <id>",
        )

    if cmd in {"/mem", "/memory"}:
        sub = parts[1].lower() if len(parts) >= 2 else "show"

        if sub == "show":
            return CommandResult(handled=True, reply=_show_memory(session))

        if sub == "clear":
            return CommandResult(handled=True, reply=_clear_memory(session))

        return CommandResult(handled=True, reply="Uso: /mem show | /mem clear")

    if cmd == "/kb":
        if len(parts) == 1:
            return CommandResult(handled=True, reply=_session_info(session))

        sub = parts[1].lower()

        if sub == "list":
            names = list_kbs(Path(workspace))
            if not names:
                return CommandResult(handled=True, reply="Nessuna KB trovata.")
            lines = ["Knowledge base disponibili:", *[f"- {name}" for name in names]]
            return CommandResult(handled=True, reply="\n".join(lines))

        if sub == "use" and len(parts) >= 3:
            kb_name = sanitize_session_id(parts[2])
            ensure_kb_dirs(Path(workspace), kb_name)
            used = _set_session_kb(session, kb_name)
            return CommandResult(handled=True, reply=f"✅ KB attiva impostata su: {used}")

        if sub == "ingest" and len(parts) >= 3:
            marker = "/kb ingest"
            tail = text[len(marker):].strip()
            pdf_path = Path(tail).expanduser().resolve()

            if not pdf_path.exists() or not pdf_path.is_file():
                return CommandResult(handled=True, reply=f"File non trovato: {pdf_path}")

            if pdf_path.suffix.lower() != ".pdf":
                return CommandResult(handled=True, reply="Puoi indicizzare solo file PDF.")

            state = session.get_state()
            kb_name = str(state.get("kb_name") or cfg.default_kb_name or "default").strip()
            ensure_kb_dirs(Path(workspace), kb_name)

            copied = copy_source_file(Path(workspace), kb_name, pdf_path)
            result = ingest_kb(Path(workspace), kb_name)

            return CommandResult(
                handled=True,
                reply=(
                    f"✅ PDF ingest completato.\n"
                    f"KB: {kb_name}\n"
                    f"Copiato in: {copied}\n"
                    f"Chunk: {result.chunk_files}\n"
                    f"Punti indicizzati: {result.indexed_points}"
                ),
            )

        return CommandResult(
            handled=True,
            reply="Uso: /kb | /kb list | /kb use <name> | /kb ingest <pdf_path>",
        )

    if cmd == "/route":
        query = text[len("/route"):].strip()
        if not query:
            return CommandResult(handled=True, reply="Uso: /route <testo>")

        decision = deterministic_route(
            user_text=query,
            state_file=session.state_file,
            default_language=cfg.default_language,
        )

        lines = [
            "Router decision:",
            f"- action: {decision.action}",
            f"- name: {decision.name}",
            f"- score: {decision.score:.4f}",
            f"- reason: {decision.reason}",
        ]

        if decision.candidates:
            lines.append("")
            lines.append("Top candidates:")
            for idx, cand in enumerate(decision.candidates[:5], start=1):
                lines.append(
                    f"{idx}. {cand.record.id} "
                    f"(name={cand.record.name}, "
                    f"final={cand.final_score:.4f}, "
                    f"vector={cand.vector_score:.4f}, "
                    f"lexical={cand.lexical_score:.4f})"
                )

        return CommandResult(handled=True, reply="\n".join(lines))

    return CommandResult(
        handled=True,
        reply="Comando non riconosciuto. Usa /help.",
    )
