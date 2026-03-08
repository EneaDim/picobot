from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from picobot.agent.router import deterministic_route
from picobot.config.schema import Config
from picobot.memory.stores import MemoryRepository
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
        "/play <wav_path>\n"
        "/play last\n"
        "  riproduce un file wav locale con aplay\n"
        "\n"
        "/exit\n"
        "  esce dalla CLI\n"
    ).strip()


def _repo(session: Session) -> MemoryRepository:
    return MemoryRepository(session.workspace, session)


def _session_info(session: Session) -> str:
    state = session.get_state()
    kb_name = str(state.get("kb_name") or "").strip() or "(nessuna)"
    kb_enabled = bool(state.get("kb_enabled", True))
    last_audio = str(state.get("last_audio_path") or "").strip() or "(nessuno)"

    return (
        f"Sessione corrente: {session.session_id}\n"
        f"KB attiva: {kb_name}\n"
        f"KB enabled: {'yes' if kb_enabled else 'no'}\n"
        f"Last audio: {last_audio}"
    )


def _set_session_kb(session: Session, kb_name: str) -> str:
    safe = sanitize_session_id(kb_name)
    session.set_state({"kb_name": safe, "kb_enabled": True})
    return safe


def _show_memory(session: Session) -> str:
    repo = _repo(session)
    repo.ensure_all()

    facts = repo.facts.read_items()
    summary = repo.summary.read()
    history = repo.history.read_entries()

    memory_block = "# Memory\n\n" + "\n".join(f"- {item}" for item in facts) if facts else "# Memory"

    summary_lines = ["# Session Summary", ""]
    summary_text = str(summary.get("summary_text") or "").strip()
    if summary_text:
        summary_lines.append(summary_text)
        summary_lines.append("")
    key_topics = [str(x).strip() for x in summary.get("key_topics") or [] if str(x).strip()]
    if key_topics:
        summary_lines.append("## Key Topics")
        summary_lines.append("")
        summary_lines.extend(f"- {item}" for item in key_topics)
        summary_lines.append("")
    open_loops = [str(x).strip() for x in summary.get("open_loops") or [] if str(x).strip()]
    if open_loops:
        summary_lines.append("## Open Loops")
        summary_lines.append("")
        summary_lines.extend(f"- {item}" for item in open_loops)
        summary_lines.append("")

    history_lines = ["# Session History", ""]
    for row in history:
        role = str(row.get("role") or "unknown").strip() or "unknown"
        ts = str(row.get("ts") or "").strip()
        content = str(row.get("content") or "").strip()
        history_lines.append(f"## {role}")
        history_lines.append("")
        history_lines.append(f"- [{ts}] {content}" if ts else f"- {content}")
        history_lines.append("")

    return (
        "=== MEMORY FACTS ===\n"
        f"{memory_block.strip()}\n\n"
        "=== SUMMARY ===\n"
        f"{chr(10).join(summary_lines).strip()}\n\n"
        "=== HISTORY ===\n"
        f"{chr(10).join(history_lines).strip()}"
    ).strip()


def _clear_memory(session: Session) -> str:
    repo = _repo(session)
    repo.ensure_all()
    repo.history.clear()
    repo.summary.clear()
    repo.facts.clear()
    return "✅ Memoria, summary e history pulite."


def _resolve_play_path(raw_value: str, session: Session) -> Path | None:
    value = (raw_value or "").strip()

    if value == "last":
        last = str(session.get_state().get("last_audio_path") or "").strip()
        if not last:
            return None
        return Path(last).expanduser().resolve()

    if not value:
        return None

    return Path(value).expanduser().resolve()


def _play_audio(cfg: Config, session: Session, raw_value: str) -> str:
    path = _resolve_play_path(raw_value, session)
    if path is None:
        return "Uso: /play <wav_path> oppure /play last"

    if not path.exists() or not path.is_file():
        return f"File audio non trovato: {path}"

    if path.suffix.lower() != ".wav":
        return (
            "Per ora /play usa aplay ed è pensato per file .wav.\n"
            f"File ricevuto: {path.name}"
        )

    aplay_bin = str(getattr(getattr(cfg, "tools", None), "aplay_bin", "aplay") or "aplay").strip()

    try:
        subprocess.run(
            [aplay_bin, str(path)],
            check=True,
        )
    except FileNotFoundError:
        return f"Comando aplay non trovato: {aplay_bin}"
    except subprocess.CalledProcessError as e:
        return f"Riproduzione fallita con exit code {e.returncode}: {path}"
    except Exception as e:
        return f"Errore durante la riproduzione audio: {e}"

    session.set_state({"last_audio_path": str(path)})
    return f"🔊 Riproduzione completata: {path}"


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
            names = list_kbs(workspace)
            if not names:
                return CommandResult(handled=True, reply="Nessuna KB trovata.")
            return CommandResult(handled=True, reply="Knowledge base disponibili:\n- " + "\n- ".join(names))

        if sub == "use" and len(parts) >= 3:
            kb_name = _set_session_kb(session, parts[2])
            ensure_kb_dirs(workspace, kb_name)
            return CommandResult(handled=True, reply=f"✅ KB attiva: {kb_name}")

        if sub == "ingest" and len(parts) >= 3:
            pdf_path = Path(" ".join(parts[2:])).expanduser().resolve()
            if not pdf_path.exists() or not pdf_path.is_file():
                return CommandResult(handled=True, reply=f"PDF non trovato: {pdf_path}")
            kb_name = str(session.get_state().get("kb_name") or cfg.default_kb_name or "default").strip()
            ensure_kb_dirs(workspace, kb_name)
            copied = copy_source_file(workspace, kb_name, pdf_path)
            result = ingest_kb(cfg, workspace, kb_name=kb_name, source_path=copied)
            return CommandResult(handled=True, reply=json.dumps(result, ensure_ascii=False, indent=2))

        return CommandResult(handled=True, reply="Uso: /kb | /kb list | /kb use <name> | /kb ingest <pdf_path>")

    if cmd == "/route":
        probe = text[len("/route"):].strip()
        if not probe:
            return CommandResult(handled=True, reply="Uso: /route <testo>")
        decision = deterministic_route(
            user_text=probe,
            state_file=session.state_file,
            default_language=cfg.default_language,
        )
        return CommandResult(handled=True, reply=json.dumps(decision.__dict__, ensure_ascii=False, indent=2))

    if cmd == "/play":
        raw_value = text[len("/play"):].strip()
        return CommandResult(handled=True, reply=_play_audio(cfg, session, raw_value))

    return CommandResult(handled=False)
