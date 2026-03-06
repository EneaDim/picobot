from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

from picobot.agent.orchestrator import Orchestrator
from picobot.config.loader import load_config
from picobot.providers.ollama import OllamaProvider
from picobot.session.manager import Session, SessionManager
from picobot.ui import handle_command

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.document import Document
    from prompt_toolkit.history import InMemoryHistory
    from prompt_toolkit.patch_stdout import patch_stdout
except Exception:  # pragma: no cover
    PromptSession = None  # type: ignore
    AutoSuggestFromHistory = None  # type: ignore
    InMemoryHistory = None  # type: ignore
    Completer = object  # type: ignore
    Completion = None  # type: ignore
    Document = None  # type: ignore
    patch_stdout = None  # type: ignore


RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

FG_CYAN = "\033[96m"
FG_MAGENTA = "\033[95m"
FG_GREEN = "\033[92m"
FG_YELLOW = "\033[93m"
FG_WHITE = "\033[97m"
FG_RED = "\033[91m"


def _s(text: str, *codes: str) -> str:
    return "".join(codes) + text + RESET


def _clear_line() -> str:
    return "\r\033[2K"


@dataclass
class CLIContext:
    session: Session


class SlashCommandCompleter(Completer):
    ROOT_COMMANDS = [
        "/help",
        "/new",
        "/session",
        "/mem",
        "/memory",
        "/kb",
        "/route",
        "/news",
        "/podcast",
        "/exit",
    ]

    SESSION_SUBS = [
        "/session list",
        "/session set ",
    ]

    MEM_SUBS = [
        "/mem show",
        "/mem clear",
        "/memory show",
        "/memory clear",
    ]

    KB_SUBS = [
        "/kb list",
        "/kb use ",
        "/kb ingest ",
    ]

    def get_completions(self, document: Document, complete_event):
        text = document.text_before_cursor

        if not text.startswith("/"):
            return

        stripped = text.strip()
        candidates: list[str] = []

        if stripped in {"", "/"}:
            candidates = self.ROOT_COMMANDS
        elif stripped.startswith("/session"):
            candidates = self.SESSION_SUBS
        elif stripped.startswith("/mem") or stripped.startswith("/memory"):
            candidates = self.MEM_SUBS
        elif stripped.startswith("/kb"):
            candidates = self.KB_SUBS
        else:
            candidates = self.ROOT_COMMANDS

        for item in candidates:
            if item.startswith(text):
                yield Completion(item, start_position=-len(text))


class CLIInput:
    def __init__(self, *, use_prompt_toolkit: bool, vi_mode: bool) -> None:
        self.use_ptk = bool(use_prompt_toolkit and PromptSession is not None)

        self.session = None
        if self.use_ptk:
            self.session = PromptSession(
                history=InMemoryHistory() if InMemoryHistory is not None else None,
                auto_suggest=AutoSuggestFromHistory() if AutoSuggestFromHistory is not None else None,
                vi_mode=bool(vi_mode),
                completer=SlashCommandCompleter(),
                complete_while_typing=False,
            )

    async def prompt(self, prompt_text: str) -> str:
        if self.session is not None:
            return await self.session.prompt_async(prompt_text)
        return await asyncio.to_thread(input, prompt_text)


class TransientStatus:
    def __init__(self) -> None:
        self.current = ""
        self.enabled = True

    def show(self, text: str) -> None:
        if not self.enabled:
            return
        self.current = text or ""
        if not self.current:
            return
        sys.stdout.write(_clear_line())
        sys.stdout.write(_s(self.current, DIM, FG_YELLOW))
        sys.stdout.flush()

    def clear(self) -> None:
        if not self.enabled:
            return
        if not self.current:
            return
        sys.stdout.write(_clear_line())
        sys.stdout.flush()
        self.current = ""


def _render_banner(session: Session, workspace: Path) -> str:
    line1 = f"{_s('🤖 Picobot', BOLD, FG_CYAN)}  {_s('local-first modular assistant', DIM, FG_WHITE)}"
    line2 = f"{_s('🧠 Session', BOLD, FG_MAGENTA)}  {session.session_id}"
    line3 = f"{_s('📁 Workspace', BOLD, FG_MAGENTA)}  {workspace}"
    line4 = f"{_s('💡 Hint', BOLD, FG_MAGENTA)}  /help per i comandi"
    return "\n".join([line1, line2, line3, line4])


def _render_user_prompt() -> str:
    # Niente ANSI qui: prompt_toolkit altrimenti può mostrarli grezzi.
    return "You: "


def _render_assistant(reply: str) -> str:
    return f"{_s('🤖:', BOLD, FG_GREEN)} {reply.strip()}"


def _render_error(reply: str) -> str:
    return f"{_s('⚠️:', BOLD, FG_RED)} {reply.strip()}"


async def _run_cli() -> int:
    parser = argparse.ArgumentParser(description="Picobot CLI")
    parser.add_argument("--session", default="default", help="Session ID iniziale")
    args = parser.parse_args()

    cfg = load_config()
    workspace = Path(cfg.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    sm = SessionManager(workspace)
    session = sm.get(args.session)

    provider = OllamaProvider(
        base_url=cfg.ollama.base_url,
        model=cfg.ollama.model,
        timeout_s=cfg.ollama.timeout_s,
    )

    orch = Orchestrator(cfg, provider, workspace)

    cli_ctx = CLIContext(session=session)
    cli_input = CLIInput(
        use_prompt_toolkit=bool(getattr(cfg.ui, "use_prompt_toolkit", True)),
        vi_mode=bool(getattr(cfg.ui, "vi_mode", False)),
    )
    status = TransientStatus()

    print(_render_banner(cli_ctx.session, workspace))
    print()

    async def status_cb(text: str) -> None:
        raw = (text or "").strip().lower()

        if "decido" in raw or "route" in raw or "percorso" in raw:
            status.show("🧭 routing...")
            return
        if "thinking" in raw or "pensando" in raw:
            status.show("💭 thinking...")
            return
        if "knowledge base" in raw or "kb" in raw or "retrieval" in raw:
            status.show("🔎 retrieving...")
            return
        if "youtube" in raw or "transcript" in raw:
            status.show("🎬 processing youtube...")
            return
        if "podcast" in raw or "audio" in raw:
            status.show("🎙️ generating audio...")
            return
        if "news" in raw or "fonti" in raw:
            status.show("📰 collecting sources...")
            return

        status.show(f"✨ {text}")

    async def _prompt_once() -> str:
        if cli_input.use_ptk and patch_stdout is not None:
            with patch_stdout():
                return await cli_input.prompt(_render_user_prompt())
        return await cli_input.prompt(_render_user_prompt())

    while True:
        try:
            raw = await _prompt_once()
        except (EOFError, KeyboardInterrupt):
            print()
            print(_s("Bye 👋", FG_YELLOW))
            return 0

        user_text = (raw or "").strip()
        if not user_text:
            continue

        cmd = handle_command(
            user_text,
            session=cli_ctx.session,
            session_manager=sm,
            cfg=cfg,
            workspace=workspace,
        )

        if cmd.handled:
            status.clear()

            if cmd.new_session_id:
                cli_ctx.session = sm.get(cmd.new_session_id)

            if cmd.reply.strip():
                print(_render_assistant(cmd.reply))
                print()

            if cmd.exit_requested:
                return 0

            continue

        try:
            status.show("🧭 routing...")

            result = await orch.one_turn(
                session=cli_ctx.session,
                user_text=user_text,
                status=status_cb,
            )

            status.clear()

        except KeyboardInterrupt:
            status.clear()
            print()
            print(_s("Interrotto.", FG_YELLOW))
            print()
            continue
        except Exception as e:
            status.clear()
            print(_render_error(f"Errore non gestito: {e}"))
            print()
            continue

        print(_render_assistant(result.content))
        print()

    return 0


def main() -> None:
    try:
        code = asyncio.run(_run_cli())
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
