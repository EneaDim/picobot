from __future__ import annotations

import inspect
import json
import shutil
import subprocess
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Callable

from picobot.agent.router import deterministic_route
from picobot.config.schema import Config
from picobot.memory.stores import MemoryRepository
from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.store import copy_source_file, ensure_kb_dirs, list_kbs
from picobot.session.manager import Session, SessionManager, sanitize_session_id


class CommandResult:
    def __init__(
        self,
        *,
        handled: bool,
        reply: str = "",
        new_session_id: str | None = None,
        exit_requested: bool = False,
    ) -> None:
        self.handled = handled
        self.reply = reply
        self.new_session_id = new_session_id
        self.exit_requested = exit_requested


def _jsonable(value: Any) -> Any:
    if value is None:
        return None

    if is_dataclass(value):
        return {k: _jsonable(v) for k, v in asdict(value).items()}

    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]

    if isinstance(value, Path):
        return str(value)

    if hasattr(value, "model_dump") and callable(value.model_dump):
        try:
            return _jsonable(value.model_dump())
        except Exception:
            pass

    if hasattr(value, "__dict__"):
        try:
            return {str(k): _jsonable(v) for k, v in vars(value).items()}
        except Exception:
            pass

    return value


def _decision_to_jsonable(decision: Any) -> dict[str, Any]:
    base = _jsonable(decision)
    if not isinstance(base, dict):
        return {"value": base}

    candidates = []
    for item in base.get("candidates", []) or []:
        if not isinstance(item, dict):
            continue

        record = item.get("record") or {}
        if not isinstance(record, dict):
            record = {}

        candidates.append(
            {
                "route_id": record.get("id"),
                "name": record.get("name"),
                "kind": record.get("kind"),
                "title": record.get("title"),
                "final_score": item.get("final_score"),
                "vector_score": item.get("vector_score"),
                "lexical_score": item.get("lexical_score"),
                "rerank_score": item.get("rerank_score"),
                "reason": item.get("reason"),
            }
        )

    base["candidates"] = candidates
    return base


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
        "/podcasts\n"
        "  mostra i podcast disponibili\n"
        "\n"
        "/play last\n"
        "/play <numero>\n"
        "/play <path>\n"
        "  riproduce un audio locale\n"
        "\n"
        "/news <query>\n"
        "/podcast <topic>\n"
        "  workflow gestiti dal runtime\n"
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


def _run_ingest_kb(cfg: Config, workspace: Path, kb_name: str, source_path: Path):
    sig = inspect.signature(ingest_kb)
    params = list(sig.parameters.keys())

    if params[:4] == ["cfg", "workspace", "kb_name", "source_path"]:
        return ingest_kb(cfg, workspace, kb_name, source_path)

    if params[:3] == ["cfg", "kb_name", "source_path"]:
        return ingest_kb(cfg, kb_name, source_path)

    kwargs = {}
    if "cfg" in sig.parameters:
        kwargs["cfg"] = cfg
    if "workspace" in sig.parameters:
        kwargs["workspace"] = workspace
    if "kb_name" in sig.parameters:
        kwargs["kb_name"] = kb_name
    if "source_path" in sig.parameters:
        kwargs["source_path"] = source_path

    return ingest_kb(**kwargs)


def _podcast_dir(cfg: Config) -> Path:
    raw = str(getattr(cfg.podcast, "output_dir", "outputs/podcasts") or "outputs/podcasts").strip()
    return Path(raw).expanduser().resolve()


def list_podcasts(cfg: Config) -> list[Path]:
    pdir = _podcast_dir(cfg)
    if not pdir.exists():
        return []

    return sorted(
        [p for p in pdir.glob("*.wav") if p.is_file()],
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )


def play_audio(path: Path) -> tuple[bool, str]:
    path = path.expanduser().resolve()

    if not path.exists() or not path.is_file():
        return False, f"File audio non trovato: {path}"

    candidates = [
        ["aplay", str(path)],
        ["ffplay", "-nodisp", "-autoexit", str(path)],
        ["mpv", str(path)],
    ]

    errors: list[str] = []

    for cmd in candidates:
        exe = cmd[0]
        if shutil.which(exe) is None:
            errors.append(f"{exe}: non disponibile")
            continue

        try:
            subprocess.run(cmd, check=True)
            return True, exe
        except subprocess.CalledProcessError as e:
            errors.append(f"{exe}: exit code {e.returncode}")
        except Exception as e:
            errors.append(f"{exe}: {e}")

    return False, " ; ".join(errors) if errors else "nessun player disponibile"


def _generate_new_session_id(session_manager: SessionManager, requested: str | None) -> str:
    if requested and str(requested).strip():
        return sanitize_session_id(requested)

    existing = set(session_manager.list())
    idx = 1
    candidate = f"session-{idx}"
    while candidate in existing:
        idx += 1
        candidate = f"session-{idx}"
    return candidate


def _handle_help() -> CommandResult:
    return CommandResult(handled=True, reply=_help_text())


def _handle_exit() -> CommandResult:
    return CommandResult(handled=True, reply="A presto 👋", exit_requested=True)


def _handle_new(parts: list[str], session_manager: SessionManager) -> CommandResult:
    requested = parts[1] if len(parts) >= 2 else ""
    session_id = _generate_new_session_id(session_manager, requested)
    session_manager.get(session_id)
    return CommandResult(
        handled=True,
        reply=f"✅ Nuova sessione attiva: {session_id}",
        new_session_id=session_id,
    )


def _handle_session(parts: list[str], session: Session, session_manager: SessionManager) -> CommandResult:
    if len(parts) == 1:
        return CommandResult(handled=True, reply=_session_info(session))

    sub = parts[1].lower()

    if sub == "list":
        sessions = session_manager.list()
        if not sessions:
            return CommandResult(handled=True, reply="Nessuna sessione trovata.")
        return CommandResult(
            handled=True,
            reply="Sessioni disponibili:\n- " + "\n- ".join(sessions),
        )

    if sub == "set" and len(parts) >= 3:
        new_id = sanitize_session_id(parts[2])
        session_manager.get(new_id)
        return CommandResult(
            handled=True,
            reply=f"✅ Sessione attiva: {new_id}",
            new_session_id=new_id,
        )

    return CommandResult(
        handled=True,
        reply="Uso: /session | /session list | /session set <id>",
    )


def _handle_memory(parts: list[str], session: Session) -> CommandResult:
    sub = parts[1].lower() if len(parts) >= 2 else "show"

    if sub == "show":
        return CommandResult(handled=True, reply=_show_memory(session))

    if sub == "clear":
        return CommandResult(handled=True, reply=_clear_memory(session))

    return CommandResult(handled=True, reply="Uso: /mem show | /mem clear")


def _handle_kb(parts: list[str], session: Session, cfg: Config, workspace: Path) -> CommandResult:
    if len(parts) == 1:
        return CommandResult(handled=True, reply=_session_info(session))

    sub = parts[1].lower()

    if sub == "list":
        names = list_kbs(workspace)
        if not names:
            return CommandResult(handled=True, reply="Nessuna KB trovata.")
        return CommandResult(
            handled=True,
            reply="Knowledge base disponibili:\n- " + "\n- ".join(names),
        )

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
        result = _run_ingest_kb(cfg, workspace, kb_name, copied)

        return CommandResult(
            handled=True,
            reply=json.dumps(_jsonable(result), ensure_ascii=False, indent=2),
        )

    return CommandResult(
        handled=True,
        reply="Uso: /kb | /kb list | /kb use <name> | /kb ingest <pdf_path>",
    )


def _handle_route(text: str, session: Session, cfg: Config) -> CommandResult:
    probe = text[len("/route"):].strip()
    if not probe:
        return CommandResult(handled=True, reply="Uso: /route <testo>")

    decision = deterministic_route(
        user_text=probe,
        state_file=session.state_file,
        default_language=cfg.default_language,
    )
    return CommandResult(
        handled=True,
        reply=json.dumps(_decision_to_jsonable(decision), ensure_ascii=False, indent=2),
    )


def _handle_podcasts(cfg: Config) -> CommandResult:
    files = list_podcasts(cfg)
    if not files:
        return CommandResult(handled=True, reply="Nessun podcast disponibile.")

    lines = ["🎧 Podcast disponibili:", ""]
    for idx, path in enumerate(files, start=1):
        lines.append(f"{idx}. {path.stem}")
    lines.append("")
    lines.append("Usa: /play last  oppure  /play <numero>  oppure  /play <path>")

    return CommandResult(handled=True, reply="\n".join(lines))


def _resolve_play_target(cfg: Config, session: Session, raw_value: str) -> tuple[Path | None, str | None]:
    value = str(raw_value or "").strip()
    files = list_podcasts(cfg)

    if value == "last":
        last = str(session.get_state().get("last_audio_path") or "").strip()
        if last:
            path = Path(last).expanduser().resolve()
            if path.exists() and path.is_file():
                return path, None
        if files:
            return files[0], None
        return None, "Nessun podcast disponibile."

    if value.isdigit():
        idx = int(value) - 1
        if idx < 0 or idx >= len(files):
            return None, "Numero podcast non valido."
        return files[idx], None

    if value:
        direct = Path(value).expanduser().resolve()
        if direct.exists() and direct.is_file():
            return direct, None
        return None, f"File audio non trovato: {direct}"

    return None, "Uso: /play last  oppure  /play <numero>  oppure  /play <path>"


def _handle_play(text: str, cfg: Config, session: Session) -> CommandResult:
    raw_value = text[len("/play"):].strip()
    target, err = _resolve_play_target(cfg, session, raw_value)

    if target is None:
        return CommandResult(handled=True, reply=err or "Target audio non valido.")

    ok, detail = play_audio(target)

    if ok:
        session.set_state({"last_audio_path": str(target)})
        return CommandResult(
            handled=True,
            reply=f"▶️ Riproduco: {target.name}",
        )

    return CommandResult(
        handled=True,
        reply=(
            f"Riproduzione automatica non disponibile.\n"
            f"File audio: {target}\n"
            f"Dettaglio player: {detail}"
        ),
    )


def handle_command(
    raw: str,
    *,
    session: Session,
    session_manager: SessionManager,
    cfg: Config,
    workspace: Path,
) -> CommandResult:
    text = str(raw or "").strip()
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

    handlers: dict[str, Callable[[], CommandResult]] = {
        "/help": _handle_help,
        "/start": _handle_help,
        "/exit": _handle_exit,
        "/quit": _handle_exit,
        "/new": lambda: _handle_new(parts, session_manager),
        "/session": lambda: _handle_session(parts, session, session_manager),
        "/mem": lambda: _handle_memory(parts, session),
        "/memory": lambda: _handle_memory(parts, session),
        "/kb": lambda: _handle_kb(parts, session, cfg, workspace),
        "/route": lambda: _handle_route(text, session, cfg),
        "/podcasts": lambda: _handle_podcasts(cfg),
        "/play": lambda: _handle_play(text, cfg, session),
    }

    handler = handlers.get(cmd)
    if handler is None:
        return CommandResult(handled=False)

    return handler()
