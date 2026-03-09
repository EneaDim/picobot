from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from picobot.bus.events import OutboundMessage, inbound_text
from picobot.bus.queue import MessageBus
from picobot.config.init import init_project
from picobot.config.loader import load_config
from picobot.providers.ollama import OllamaProvider
from picobot.runtime import AgentRuntime
from picobot.session.manager import Session, SessionManager
from picobot.tools.init_tools import bootstrap_all, resolve_config_path, tool_snapshot
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
FG_BLUE = "\033[94m"


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
        self.enabled = True
        self.base_text = ""
        self._spinner_task: asyncio.Task | None = None
        self._running = False
        self._frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self._started_at = 0.0

    def update(self, text: str) -> None:
        self.base_text = (text or "").strip()

    async def start(self, text: str = "processing...") -> None:
        if not self.enabled:
            return
        self.base_text = (text or "").strip() or "processing..."
        if self._running:
            return
        import time
        self._started_at = time.time()
        self._running = True
        self._spinner_task = asyncio.create_task(self._spin_loop(), name="picobot-cli-spinner")

    async def stop(self) -> None:
        import time
        elapsed = time.time() - float(self._started_at or 0.0)
        if elapsed < 0.25:
            await asyncio.sleep(0.25 - elapsed)

        self._running = False
        if self._spinner_task is not None:
            try:
                await self._spinner_task
            except asyncio.CancelledError:
                pass
            self._spinner_task = None
        self.clear()

    def clear(self) -> None:
        if not self.enabled:
            return
        sys.stdout.write(_clear_line())
        sys.stdout.flush()

    async def _spin_loop(self) -> None:
        idx = 0
        try:
            while self._running:
                text = self.base_text or "processing..."
                frame = self._frames[idx % len(self._frames)]
                idx += 1
                sys.stdout.write(_clear_line())
                sys.stdout.write(_s(f"{frame} {text}", DIM, FG_YELLOW))
                sys.stdout.flush()
                await asyncio.sleep(0.12)
        finally:
            sys.stdout.write(_clear_line())
            sys.stdout.flush()


def _render_banner(session: Session, workspace: Path) -> str:
    line1 = f"{_s('🤖 Picobot', BOLD, FG_CYAN)}  {_s('local-first modular assistant', DIM, FG_WHITE)}"
    line2 = f"{_s('🧠 Session', BOLD, FG_MAGENTA)}  {session.session_id}"
    line3 = f"{_s('📁 Workspace', BOLD, FG_MAGENTA)}  {workspace}"
    line4 = f"{_s('💡 Hint', BOLD, FG_MAGENTA)}  /help per i comandi"
    return "\n".join([line1, line2, line3, line4])


def _render_user_prompt() -> str:
    return "You: "


def _render_assistant(reply: str) -> str:
    return f"{_s('🤖:', BOLD, FG_GREEN)} {reply.strip()}"


def _render_error(reply: str) -> str:
    return f"{_s('⚠️:', BOLD, FG_RED)} {reply.strip()}"


def _render_debug(reply: str) -> str:
    return f"{_s('DEBUG:', BOLD, FG_BLUE)} {reply.strip()}"


def _run_init_command() -> int:
    result = init_project(force=False)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_init_tools_command(config_path: str | None, overwrite: bool) -> int:
    cfg_path = resolve_config_path(config_path)
    result = bootstrap_all(cfg_path, overwrite=overwrite)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _run_tools_status_command(config_path: str | None) -> int:
    cfg_path = resolve_config_path(config_path)
    result = tool_snapshot(cfg_path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _map_status_text(text: str) -> str:
    raw = (text or "").strip().lower()

    if "route scelta" in raw:
        return text
    if "decido" in raw or "route" in raw or "percorso" in raw:
        return "routing..."
    if "thinking" in raw or "pensando" in raw:
        return "thinking..."
    if "knowledge base" in raw or "kb" in raw or "retrieval" in raw:
        return "retrieving..."
    if "youtube" in raw or "transcript" in raw:
        return "processing youtube..."
    if "podcast" in raw or "audio" in raw:
        return "generating audio..."
    if "news" in raw or "fonti" in raw:
        return "collecting sources..."
    return text or "processing..."


async def _prompt_once(cli_input: CLIInput) -> str:
    if cli_input.use_ptk and patch_stdout is not None:
        with patch_stdout():
            return await cli_input.prompt(_render_user_prompt())
    return await cli_input.prompt(_render_user_prompt())


def _debug_enabled(cfg) -> bool:
    dbg = getattr(cfg, "debug", None)
    return bool(getattr(dbg, "enabled", False))


def _render_router_debug(metadata: dict) -> str | None:
    route_action = str(metadata.get("route_action") or "").strip()
    route_name = str(metadata.get("route_name") or "").strip()
    route_reason = str(metadata.get("route_reason") or "").strip()
    route_score = float(metadata.get("route_score") or 0.0)

    if not route_name and not route_action:
        return None

    parts = [f"{route_action}:{route_name}", f"score={route_score:.3f}"]

    if route_reason:
        short_reason = route_reason.replace("\n", " ").strip()
        if len(short_reason) > 120:
            short_reason = short_reason[:117] + "..."
        parts.append(f"reason={short_reason}")

    candidates = list(metadata.get("route_candidates") or [])
    if candidates:
        short_candidates = " | ".join(str(x).strip() for x in candidates[:3] if str(x).strip())
        if short_candidates:
            parts.append(f"top={short_candidates}")

    return "router -> " + " ; ".join(parts)


async def _run_chat_cli(session_id: str) -> int:
    cfg = load_config()
    workspace = Path(cfg.workspace).expanduser().resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    sm = SessionManager(workspace)
    session = sm.get(session_id)

    provider = OllamaProvider(
        base_url=cfg.ollama.base_url,
        model=cfg.ollama.model,
        timeout_s=cfg.ollama.timeout_s,
    )

    bus = MessageBus()
    runtime = AgentRuntime(
        bus=bus,
        cfg=cfg,
        provider=provider,
        workspace=workspace,
        session_manager=sm,
    )

    await bus.start()
    await runtime.start()

    cli_ctx = CLIContext(session=session)
    cli_input = CLIInput(
        use_prompt_toolkit=bool(getattr(cfg.ui, "use_prompt_toolkit", True)),
        vi_mode=bool(getattr(cfg.ui, "vi_mode", False)),
    )
    status = TransientStatus()
    outbound_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()

    async def on_outbound(message) -> None:
        if not isinstance(message, OutboundMessage):
            return
        if message.channel != "cli":
            return
        await outbound_queue.put(message)

    unsubscribe = bus.subscribe("outbound.*", on_outbound)

    print(_render_banner(cli_ctx.session, workspace))
    print()

    try:
        while True:
            try:
                raw = await _prompt_once(cli_input)
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
                await status.stop()

                if cmd.new_session_id:
                    cli_ctx.session = sm.get(cmd.new_session_id)

                if cmd.reply.strip():
                    print(_render_assistant(cmd.reply))
                    print()

                if cmd.exit_requested:
                    return 0

                continue

            correlation_id = uuid4().hex

            try:
                await status.start("processing...")

                await bus.publish(
                    inbound_text(
                        channel="cli",
                        chat_id=cli_ctx.session.session_id,
                        session_id=cli_ctx.session.session_id,
                        text=user_text,
                        source="cli",
                        correlation_id=correlation_id,
                        metadata={"transport": "cli"},
                    )
                )

                while True:
                    outbound = await outbound_queue.get()

                    if outbound.correlation_id != correlation_id:
                        continue

                    if outbound.message_type == "outbound.status":
                        status.update(_map_status_text(str(outbound.payload.get("text") or "")))
                        continue

                    if outbound.message_type == "outbound.audio":
                        await status.stop()
                        audio_path = str(outbound.payload.get("audio_path") or "").strip()
                        if audio_path:
                            print(_s(f"🎧 Audio generato: {audio_path}", DIM, FG_WHITE))
                        continue

                    if outbound.message_type == "outbound.error":
                        await status.stop()
                        if _debug_enabled(cfg):
                            dbg = _render_router_debug(dict(outbound.metadata or {}))
                            if dbg:
                                print(_render_debug(dbg))
                        print(_render_error(str(outbound.payload.get("text") or "Errore runtime")))
                        print()
                        break

                    if outbound.message_type == "outbound.text":
                        await status.stop()
                        if _debug_enabled(cfg):
                            dbg = _render_router_debug(dict(outbound.metadata or {}))
                            if dbg:
                                print(_render_debug(dbg))
                        print(_render_assistant(str(outbound.payload.get("text") or "")))
                        print()
                        break

            except KeyboardInterrupt:
                await status.stop()
                print()
                print(_s("Interrotto.", FG_YELLOW))
                print()
                continue
            except Exception as e:
                await status.stop()
                print(_render_error(f"Errore non gestito: {e}"))
                print()
                continue
    finally:
        unsubscribe()
        await runtime.stop()
        await bus.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Picobot")
    parser.add_argument("command", nargs="?", default="chat", choices=["chat", "init", "init-tools", "tools-status"])
    parser.add_argument("--session", default="default", help="Session ID per la chat CLI")
    parser.add_argument("--config", default=None, help="Path config per init-tools/tools-status")
    parser.add_argument("--overwrite", action="store_true", help="Sovrascrivi tool già scaricati")
    args = parser.parse_args()

    if args.command == "init":
        sys.exit(_run_init_command())

    if args.command == "init-tools":
        sys.exit(_run_init_tools_command(args.config, args.overwrite))

    if args.command == "tools-status":
        sys.exit(_run_tools_status_command(args.config))

    try:
        code = asyncio.run(_run_chat_cli(args.session))
    except KeyboardInterrupt:
        code = 130
    sys.exit(code)


if __name__ == "__main__":
    main()
