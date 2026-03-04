from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from picobot.session.manager import SessionManager

# Optional CLI autocomplete
_pt_prompt = None
WordCompleter = None
FileHistory = None
try:
    from prompt_toolkit import prompt as _pt_prompt  # type: ignore
    from prompt_toolkit.completion import WordCompleter  # type: ignore
    from prompt_toolkit.history import FileHistory  # type: ignore
except Exception:  # pragma: no cover
    _pt_prompt = None
    WordCompleter = None
    FileHistory = None

# Optional rich console
try:
    from rich.console import Console
except Exception:  # pragma: no cover
    Console = None  # type: ignore

# =========================================================
# UI base
# =========================================================

class BaseUI:
    """Minimal UI interface used by CLI and Telegram."""

    def info(self, text: str) -> None:
        raise NotImplementedError

    def debug(self, text: str) -> None:
        raise NotImplementedError

    def error(self, text: str) -> None:
        """Terminal-only errors. Telegram implementation must NEVER expose stack traces."""
        raise NotImplementedError

    async def transient(self, key: str, text: str) -> None:
        """Transient status updates (e.g., 'Routing…', 'TTS…')."""
        return

    def send_text(self, text: str) -> None:
        raise NotImplementedError

    def send_file(self, path: str, caption: str | None = None) -> None:
        raise NotImplementedError

    def send_audio(self, path: str, caption: str | None = None) -> None:
        raise NotImplementedError


class ConsoleUI(BaseUI):
    def __init__(self, *, debug_enabled: bool = False) -> None:
        self.debug_enabled = debug_enabled
        self._console = Console() if Console else None

    def _print(self, text: str) -> None:
        if self._console:
            self._console.print(text)
        else:
            print(text)

    def info(self, text: str) -> None:
        self._print(text)

    def debug(self, text: str) -> None:
        if self.debug_enabled:
            self._print(text)

    def error(self, text: str) -> None:
        # terminal only
        if self._console:
            self._console.print(text)
        else:
            print(text)

    async def transient(self, key: str, text: str) -> None:
        # Simple: print transient status line. (No spinner; deterministic.)
        self.debug(f"{text}")
        await asyncio.sleep(0)

    def send_text(self, text: str) -> None:
        self._print(text)

    def send_file(self, path: str, caption: str | None = None) -> None:
        cap = f" {caption}" if caption else ""
        self._print(f"📎 {path}{cap}")

    def send_audio(self, path: str, caption: str | None = None) -> None:
        cap = f" {caption}" if caption else ""
        self._print(f"🎧 {path}{cap}")


class TelegramUI(BaseUI):
    """
    Thin adapter. Telegram channel should call these methods.
    IMPORTANT: error() is terminal-only (no Telegram leak).
    """
    def __init__(self, *, debug_enabled: bool = False) -> None:
        self.debug_enabled = debug_enabled

    def info(self, text: str) -> None:
        # TelegramChannel should send messages explicitly; keep as no-op
        return

    def debug(self, text: str) -> None:
        if self.debug_enabled:
            print(f"[telegram-ui] {text}", flush=True)

    def error(self, text: str) -> None:
        # NEVER send errors to Telegram; terminal only
        print(f"[telegram-ui][error] {text}", flush=True)

    def send_text(self, text: str) -> None:
        return

    def send_file(self, path: str, caption: str | None = None) -> None:
        return

    def send_audio(self, path: str, caption: str | None = None) -> None:
        return


# =========================================================
# Status helper (backward compatible)
# =========================================================

class Status:
    """Tiny helper used by CLI; kept for compatibility with older call sites."""
    def __init__(self, ui: BaseUI) -> None:
        self.ui = ui

    def clear(self) -> None:
        return

    def show(self, text: str):
        # context manager
        class _Ctx:
            def __enter__(_self):
                self.ui.debug(text)
                return _self

            def __exit__(_self, exc_type, exc, tb):
                return False

        return _Ctx()


# =========================================================
# CLI readline (prompt_toolkit optional)
# =========================================================

@dataclass(frozen=True)
class ConsoleOptions:
    use_prompt_toolkit: bool = True
    vi_mode: bool = False


def make_readline(workspace: Path, opts: ConsoleOptions) -> Callable[[str], str]:
    """
    Returns a callable(prompt)->str.
    Enables autocomplete if prompt_toolkit is available.
    """
    commands = [
        "/help", "/h",
        "/ping",
        "/wsearch",
        "/exit", "/quit",
        "/session", "/session list", "/session set",
        "/new",
        "/kb", "/kb list", "/kb status", "/kb set", "/kb ingest", "/kb rebuild",
        "/mem", "/mem show", "/mem clear",
        "/podcast", "/podcast it", "/podcast en", "/podcast list", "/podcast play",
        "/py",
        "/file", "/file preview",
    ]

    def _read_plain(prompt: str) -> str:
        p = (prompt + " ") if prompt and not prompt.endswith(" ") else prompt
        return input(p)

    if not opts.use_prompt_toolkit:
        return _read_plain
    if _pt_prompt is None or WordCompleter is None:
        return _read_plain

    completer = WordCompleter(commands, ignore_case=True, sentence=True)
    hist_path = (workspace / "channels" / "cli" / "history.txt").resolve()
    hist_path.parent.mkdir(parents=True, exist_ok=True)
    history = FileHistory(str(hist_path)) if FileHistory else None

    def _read(prompt: str) -> str:
        p = (prompt + " ") if prompt and not prompt.endswith(" ") else prompt
        try:
            return _pt_prompt(
                p,
                completer=completer,
                complete_while_typing=True,
                vi_mode=bool(opts.vi_mode),
                history=history,
            )
        except (EOFError, KeyboardInterrupt):
            return ""
        except Exception:
            return _read_plain(prompt)

    return _read


# =========================================================
# Commands (shared CLI + Telegram)
# =========================================================

@dataclass
class CommandResult:
    handled: bool
    reply: str = ""
    new_session_id: str | None = None
    rewrite_text: str | None = None
    exit_now: bool = False
    play_audio_path: str | None = None


def _strip_emojis(text: str) -> str:
    # used if cfg.ui.use_emojis is False
    return (
        text.replace("🧭 ", "")
        .replace("🔎 ", "")
        .replace("💭 ", "")
        .replace("✅ ", "")
        .replace("🛠 ", "")
        .replace("🎙 ", "")
        .replace("🗣 ", "")
        .replace("📨 ", "")
    )


def _find_recent_podcasts(cfg, limit: int = 10) -> list[Path]:
    pcfg = getattr(cfg, "podcast", None)
    out_dir = Path(getattr(pcfg, "output_dir", "outputs/podcasts") if pcfg else "outputs/podcasts").expanduser()
    if not out_dir.exists():
        return []
    cands: list[Path] = []
    for p in out_dir.glob("*/podcast.*"):
        if p.is_file():
            cands.append(p)
    for p in out_dir.glob("podcast.*"):
        if p.is_file():
            cands.append(p)
    cands = sorted(set(cands), key=lambda x: x.stat().st_mtime, reverse=True)
    return cands[: max(1, int(limit))]


def _help_text(use_emojis: bool) -> str:
    if use_emojis:
        return (
            "🤖 picobot commands\n"
            "  🧭 /help              Show this help\n"
            "  🧩 /session list      List sessions\n"
            "  🧩 /session set <id>  Switch session\n"
            "  📚 /kb set <name>     Switch knowledge base\n"
            "  📝 /mem show          Show global MEMORY + session SUMMARY + HISTORY tail\n"
            "  🧹 /mem clear         Clear global MEMORY + session history/summary\n"
            "  🎙 /podcast <topic>   Generate a podcast (trigger)\n"
            "  🎙 /podcast it|en <topic>\n"
            "  🎧 /podcast list      List recent podcasts (CLI)\n"
            "  ▶️  /podcast play [path] (CLI)\n"
            "  🚪 /exit              Quit (CLI)\n"
        )
    return (
        "picobot commands\n"
        "  /help\n"
        "  /session list\n"
        "  /session set <id>\n"
        "  /kb set <name>\n"
        "  /mem show\n"
        "  /mem clear\n"
        "  /podcast <topic>\n"
        "  /podcast it|en <topic>\n"
        "  /podcast list\n"
        "  /podcast play [path]\n"
        "  /exit\n"
    )


def handle_command(
    text: str,
    *,
    session: Any,
    session_manager: SessionManager,
    cfg: Any,
    workspace: Path,
) -> CommandResult:
    t = (text or "").strip()
    if not t.startswith("/"):
        return CommandResult(handled=False)

    parts = t.split(None, 2)
    cmd = parts[0].lower()
    arg1 = parts[1] if len(parts) >= 2 else ""
    argrest = t[len(parts[0]) :].strip() if len(parts) >= 2 else ""

    use_emojis = bool(getattr(getattr(cfg, "ui", None), "use_emojis", True))

    if cmd in ("/help", "/h"):
        return CommandResult(handled=True, reply=_help_text(use_emojis))

    if cmd == "/ping":
        return CommandResult(handled=True, reply="Pong!")

    if cmd in ("/exit", "/quit"):
        return CommandResult(handled=True, exit_now=True, reply="bye 👋")

    # session
    if cmd == "/session":
        if arg1 == "list":
            return CommandResult(handled=True, reply="Sessions: " + ", ".join(session_manager.list()))
        if arg1 == "set" and len(parts) >= 3:
            sid = parts[2].strip()
            if not sid:
                return CommandResult(handled=True, reply="Usage: /session set <id>")
            return CommandResult(handled=True, new_session_id=sid, reply=f"(session set to {sid})")
        return CommandResult(handled=True, reply="Usage: /session list | /session set <id>")

    # kb

    if cmd == "/kb":
        sub = (arg1 or "").strip().lower()
        if not sub:
            return CommandResult(handled=True, reply="Usage: /kb list | /kb status | /kb set <name> | /kb unset | /kb on | /kb off | /kb ingest | /kb rebuild")

        def _kb_enabled() -> bool:
            try:
                st = session.get_state() or {}
                if isinstance(st, dict) and "kb_enabled" in st:
                    return bool(st["kb_enabled"])
            except Exception:
                pass
            return True

        def _kb_name() -> str:
            try:
                st = session.get_state() or {}
                if isinstance(st, dict) and st.get("kb_name"):
                    return str(st["kb_name"])
            except Exception:
                pass
            return "default"

        def _kb_root(name: str) -> Path:
            return (workspace / "docs" / name).resolve()

        def _kb_ensure(name: str) -> Path:
            root = _kb_root(name)
            (root / "kb").mkdir(parents=True, exist_ok=True)
            (root / "source").mkdir(parents=True, exist_ok=True)
            return root

        if sub == "list":
            docs = (workspace / "docs")
            docs.mkdir(parents=True, exist_ok=True)
            items = sorted([p.name for p in docs.iterdir() if p.is_dir()])
            return CommandResult(handled=True, reply="KBs: " + (", ".join(items) if items else "(none)"))

        if sub == "status":
            name = _kb_name()
            root = _kb_ensure(name)
            src = root / "source"
            store = root / "kb"
            src_n = len([p for p in src.rglob("*") if p.is_file()])
            store_n = len([p for p in store.rglob("*") if p.is_file()])
            return CommandResult(handled=True, reply=f"KB={name}\n(enabled={_kb_enabled()})\nsource_files={src_n}\nstore_files={store_n}\nroot={root}")

        if sub == "off":
            try:
                session.set_state({"kb_enabled": False})
            except Exception:
                pass
            return CommandResult(handled=True, reply="(kb disabled)")

        if sub == "on":
            try:
                session.set_state({"kb_enabled": True, "kb_auto": True})
            except Exception:
                pass
            return CommandResult(handled=True, reply="(kb enabled)")

        if sub == "unset":
            try:
                st = session.get_state() or {}
                if isinstance(st, dict) and "kb_name" in st:
                    st.pop("kb_name", None)
                    session.set_state(st)
            except Exception:
                pass
            return CommandResult(handled=True, reply="(kb unset)")

        if sub == "set":
            if len(parts) < 3:
                return CommandResult(handled=True, reply="Usage: /kb set <name>")
            name = parts[2].strip()
            if not name:
                return CommandResult(handled=True, reply="Usage: /kb set <name>")
            _kb_ensure(name)
            try:
                session.set_state({"kb_name": name})
            except Exception:
                pass
            return CommandResult(handled=True, reply=f"(kb set to {name})")

        if sub in ("ingest", "rebuild"):
            name = _kb_name()
            root = _kb_ensure(name)
            source_dir = root / "source"
            store_dir = root / "kb"
            if sub == "rebuild":
                try:
                    for fp in store_dir.rglob("*"):
                        if fp.is_file():
                            fp.unlink(missing_ok=True)
                except Exception:
                    pass
            try:
                from picobot.retrieval.ingest import ingest_dir
                ingest_dir(source_dir=source_dir, store_dir=store_dir)
            except Exception as e:
                # detailed error should stay on terminal; CLI gets a short safe msg
                return CommandResult(handled=True, reply=f"KB {sub} error. Check terminal. ({e.__class__.__name__})")
            return CommandResult(handled=True, reply=f"(kb {sub} done) {name}")

        return CommandResult(handled=True, reply="Usage: /kb list | /kb status | /kb set <name> | /kb unset | /kb on | /kb off | /kb ingest | /kb rebuild")


    if cmd == "/mem":
        global_memory = workspace / "memory" / "MEMORY.md"
        global_memory.parent.mkdir(parents=True, exist_ok=True)
        if not global_memory.exists():
            global_memory.write_text("# Memory\n\n", encoding="utf-8")

        if arg1 == "show":
            try:
                g = global_memory.read_text(encoding="utf-8") or "(empty)"
            except Exception:
                g = "(unreadable)"
            try:
                summ = session.summary_file.read_text(encoding="utf-8") or "(empty)"
            except Exception:
                summ = "(unreadable)"
            try:
                hist_lines = (session.history_file.read_text(encoding="utf-8") or "").splitlines()
                tail = "\n".join(hist_lines[-120:]).strip() or "(empty)"
            except Exception:
                tail = "(unreadable)"
            return CommandResult(
                handled=True,
                reply=(
                    "----- GLOBAL MEMORY.md -----\n"
                    f"{g}\n\n"
                    "----- SESSION SUMMARY.md -----\n"
                    f"{summ}\n\n"
                    "----- SESSION HISTORY tail -----\n"
                    f"{tail}\n"
                ),
            )

        if arg1 == "clear":
            global_memory.write_text("# Memory\n\n", encoding="utf-8")
            try:
                session.history_file.write_text("# Session History\n\n", encoding="utf-8")
                session.summary_file.write_text("# Session Summary\n\n", encoding="utf-8")
            except Exception:
                pass
            return CommandResult(handled=True, reply="(memory cleared)")

        return CommandResult(handled=True, reply="Usage: /mem show | /mem clear")

    # podcast utility (CLI)
    if cmd == "/podcast":
        if arg1 == "list":
            items = _find_recent_podcasts(cfg, limit=10)
            if not items:
                return CommandResult(handled=True, reply="(no podcasts found)")
            lines = ["Recent podcasts:"]
            for i, ap in enumerate(items, start=1):
                lines.append(f"  {i}. {ap}")
            return CommandResult(handled=True, reply="\n".join(lines))

        if arg1 == "play":
            # CLI-only; Telegram should just print the path
            if len(parts) >= 3:
                ap = Path(parts[2]).expanduser()
                return CommandResult(handled=True, play_audio_path=str(ap), reply=f"▶️  Playing: {ap}")
            items = _find_recent_podcasts(cfg, limit=1)
            if not items:
                return CommandResult(handled=True, reply="(no podcasts found)")
            return CommandResult(handled=True, play_audio_path=str(items[0]), reply=f"▶️  Playing latest: {items[0]}")

        # /podcast it|en <topic>  => rewrite into natural trigger text (NO LLM)
        rest = argrest.strip()
        if not rest:
            return CommandResult(handled=True, reply="Usage: /podcast <topic> | /podcast it <topic> | /podcast en <topic>")
        sub = rest.split(None, 1)
        if len(sub) == 2 and sub[0].lower() in ("it", "en"):
            lng = sub[0].lower()
            topic = sub[1].strip()
            if lng == "it":
                return CommandResult(handled=False, rewrite_text=f"podcast su {topic}")
            return CommandResult(handled=False, rewrite_text=f"podcast about {topic}")
        return CommandResult(handled=False, rewrite_text=f"podcast {rest}")
    # -------------------------
    # KB utilities (CLI+Telegram)
    # -------------------------
    def _kb_name() -> str:
        # try session state first
        try:
            st = session.get_state() or {}
            if isinstance(st, dict) and st.get("kb_name"):
                return str(st["kb_name"])
        except Exception:
            pass
        return str(getattr(getattr(cfg, "retrieval", None), "default_kb", "default") or "default")

    def _kb_root(name: str) -> Path:
        return (workspace / "docs" / name).resolve()

    def _kb_ensure(name: str) -> Path:
        root = _kb_root(name)
        (root / "kb").mkdir(parents=True, exist_ok=True)
        (root / "source").mkdir(parents=True, exist_ok=True)
        return root

    if cmd == "/kb":
        sub = (arg1 or "").strip().lower()
        if not sub:
            return CommandResult(
                handled=True,
                reply="Usage: /kb list | /kb status | /kb set <name> | /kb unset | /kb on | /kb off | /kb ingest | /kb rebuild",
            )

        if sub == "list":
            docs = (workspace / "docs")
            docs.mkdir(parents=True, exist_ok=True)
            items = sorted([p.name for p in docs.iterdir() if p.is_dir()])
            return CommandResult(handled=True, reply="KBs: " + (", ".join(items) if items else "(none)"))

        if sub == "status":
            name = _kb_name()
            root = _kb_ensure(name)
            src = root / "source"
            store = root / "kb"
            src_n = len([p for p in src.rglob("*") if p.is_file()])
            store_n = len([p for p in store.rglob("*") if p.is_file()])
            return CommandResult(
                handled=True,
                reply=f"KB={name}\n  source_files={src_n}\n  store_files={store_n}\n  root={root}",
            )

        if sub == "set" and len(parts) >= 3:
            name = parts[2].strip()
            if not name:
                return CommandResult(handled=True, reply="Usage: /kb set <name>")
            _kb_ensure(name)
            try:
                session.set_state({"kb_name": name})
            except Exception:
                pass
            return CommandResult(handled=True, reply=f"(kb set to {name})")

        if sub in ("ingest", "rebuild"):
            name = _kb_name()
            root = _kb_ensure(name)
            source_dir = root / "source"
            store_dir = root / "kb"
            if sub == "rebuild":
                # hard rebuild: wipe store
                try:
                    for fp in store_dir.rglob("*"):
                        if fp.is_file():
                            fp.unlink(missing_ok=True)
                except Exception:
                    pass
            # run ingest (local deterministic)
            try:
                from picobot.retrieval.ingest import ingest_dir
                ingest_dir(source_dir=source_dir, store_dir=store_dir)
            except Exception as e:
                # errors should be terminal-only; CLI will show a short message
                return CommandResult(handled=True, reply=f"KB ingest error. Check terminal. ({e.__class__.__name__})")
            return CommandResult(handled=True, reply=f"(kb {sub} done) {name}")

        return CommandResult(handled=True, reply="Usage: /kb list | /kb status | /kb set <name> | /kb unset | /kb on | /kb off | /kb ingest | /kb rebuild")

    # -------------------------
    # Sandbox helpers (force tool routing via rewrite)
    # -------------------------
    if cmd == "/py":
        code = (argrest or "").strip()
        if not code:
            return CommandResult(handled=True, reply="Usage: /py <python code>")
        payload = {"cwd": str(workspace), "code": code}
        return CommandResult(handled=False, rewrite_text="tool sandbox_python " + json.dumps(payload, ensure_ascii=False))

    if cmd == "/file":
        rest = (argrest or "").strip()
        if not rest:
            return CommandResult(handled=True, reply="Usage: /file preview <path>")
        sub = rest.split(None, 1)
        if len(sub) != 2 or sub[0].lower() != "preview":
            return CommandResult(handled=True, reply="Usage: /file preview <path>")
        path = sub[1].strip()
        payload = {"root": str(workspace), "path": path}
        return CommandResult(handled=False, rewrite_text="tool sandbox_file " + json.dumps(payload, ensure_ascii=False))


    return CommandResult(handled=True, reply="Unknown command. Type /help")
