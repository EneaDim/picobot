from __future__ import annotations

from picobot.ui.commands import handle_command
import asyncio
import json

import typer
from picobot.config.init import init_project
from rich.console import Console

from picobot.config.loader import load_config
from picobot.providers.ollama import OllamaProvider
from picobot.session.manager import SessionManager
from picobot.utils.helpers import workspace_path
from picobot.agent.orchestrator import Orchestrator
from picobot.channels.telegram import TelegramChannel
from picobot.ui.status import Status
from picobot.ui.console import make_readline, ConsoleOptions

app = typer.Typer(add_completion=False)
console = Console()


def _strip_emojis(msg: str) -> str:
    return msg.replace("🧭 ", "").replace("🔎 ", "").replace("💭 ", "").replace("✅ ", "").replace("🛠 ", "")


def _print_banner() -> None:
    console.print("🤖 picobot")
    console.print("  🔎 Retrieval (local KB)")
    console.print("  🛠 Tools (YouTube transcript/summary, PDF ingest)")
    console.print("  📝 Memory (global MEMORY + session history/summary)")
    console.print("  ⌨️  Tab completion + history (type /help)")
    console.print("")


def _help_text(use_emojis: bool) -> str:
    if use_emojis:
        return (
            "🤖 picobot commands\n"
            "  🧭 /help              Show this help\n"
            "  📚 /kb set <name>     Switch knowledge base\n"
            "  📝 /mem show          Show global MEMORY + session SUMMARY + HISTORY tail\n"
            "  🧹 /mem clear         Clear global MEMORY + session history/summary\n"
            "  🧩 /session list      List sessions\n"
            "  🧩 /session set <id>  Switch session\n"
            "  🚪 /exit              Quit\n"
        )
    return (
        "picobot commands\n"
        "  /help\n"
        "  /kb set <name>\n"
        "  /mem show\n"
        "  /mem clear\n"
        "  /session list\n"
        "  /session set <id>\n"
        "  /exit\n"
    )


@app.command()
def chat(session: str = typer.Option("default", "--session", "-s")):
    cfg = load_config()
    ws = workspace_path(cfg)
    sm = SessionManager(ws)

    provider = OllamaProvider(cfg.ollama.base_url, cfg.ollama.model, timeout_s=cfg.ollama.timeout_s)
    orch = Orchestrator(cfg, provider, ws)

    current = sm.get(session)

    _print_banner()

    st = Status(enabled=True, min_display_s=1.0)
    read_line = make_readline(ws, ConsoleOptions(use_prompt_toolkit=cfg.ui.use_prompt_toolkit, vi_mode=cfg.ui.vi_mode))

    global_memory = ws / "memory" / "MEMORY.md"
    global_memory.parent.mkdir(parents=True, exist_ok=True)
    if not global_memory.exists():
        global_memory.write_text("# Memory\n\n", encoding="utf-8")

    while True:
        try:
            user = read_line("You:").strip()
        except (EOFError, KeyboardInterrupt):
            console.print("\n/exit")
            console.print("bye 👋")
            return

        if not user:
            continue

        if user in {"/exit", "/quit", "exit", "quit"}:
            console.print("/exit")
            console.print("bye 👋")
            return

        if user.startswith("/help"):
            console.print(_help_text(cfg.ui.use_emojis))
            continue

        if user.startswith("/session"):
            parts = user.split()
            if len(parts) >= 2 and parts[1] == "list":
                console.print("Sessions: " + ", ".join(sm.list()))
                continue
            if len(parts) >= 3 and parts[1] == "set":
                current = sm.get(parts[2])
                console.print(f"(session set to {current.session_id})")
                continue
            console.print("Usage: /session list | /session set <id>")
            continue

        if user.startswith("/kb"):
            parts = user.split()
            if len(parts) >= 3 and parts[1] == "set":
                kb_name = parts[2].strip()
                if not kb_name:
                    console.print("Usage: /kb set <name>")
                    continue
                current.set_state({"kb_name": kb_name})
                (ws / "docs" / kb_name / "kb").mkdir(parents=True, exist_ok=True)
                (ws / "docs" / kb_name / "source").mkdir(parents=True, exist_ok=True)
                console.print(f"(kb set to {kb_name})")
                continue
            console.print("Usage: /kb set <name>")
            continue

        if user.startswith("/mem"):
            parts = user.split()
            if len(parts) >= 2 and parts[1] == "show":
                console.print("----- GLOBAL MEMORY.md -----")
                console.print(global_memory.read_text(encoding="utf-8") or "(empty)")
                console.print("\n----- SESSION SUMMARY.md -----")
                console.print(current.summary_file.read_text(encoding="utf-8") or "(empty)")
                console.print("\n----- SESSION HISTORY tail -----")
                h = (current.history_file.read_text(encoding="utf-8") or "").splitlines()
                tail = "\n".join(h[-120:]).strip()
                console.print(tail or "(empty)")
                continue
            if len(parts) >= 2 and parts[1] == "clear":
                global_memory.write_text("# Memory\n\n", encoding="utf-8")
                current.history_file.write_text("# Session History\n\n", encoding="utf-8")
                current.summary_file.write_text("# Session Summary\n\n", encoding="utf-8")
                console.print("(memory cleared)")
                continue
            console.print("Usage: /mem show | /mem clear")
            continue

        async def _run():
            async def status_cb(msg: str) -> None:
                if not cfg.ui.use_emojis:
                    msg = _strip_emojis(msg)
                with st.show(msg):
                    await asyncio.sleep(0)

            # Shared command handling (/help, /sessions, /use, ...)
            cr = handle_command(user, session=current, session_manager=sm if 'sm' in locals() else None)
            if cr.handled:
                # If command switches session, update local session variable
                if cr.new_session_id and 'sm' in locals():
                    current = sm.get(cr.new_session_id)
                print(cr.reply)
                return

            res = await orch.one_turn(current, user, status=status_cb)
            st.clear()

            if cfg.debug.enabled:
                route = {"action": res.action, "kb_mode": res.kb_mode, "reason": res.reason}
                console.print(f' route={json.dumps(route, ensure_ascii=False)}')

            console.print(f"🤖 {res.content}")

        asyncio.run(_run())


@app.command()
def telegram():
    cfg = load_config()
    if not cfg.telegram.enabled:
        console.print("Telegram is disabled in config. Set telegram.enabled=true.")
        raise typer.Exit(code=2)

    ws = workspace_path(cfg)
    sm = SessionManager(ws)

    provider = OllamaProvider(cfg.ollama.base_url, cfg.ollama.model, timeout_s=cfg.ollama.timeout_s)
    orch = Orchestrator(cfg, provider, ws)

    chan = TelegramChannel(cfg, sm, orch)
    console.print("📨 Telegram bot running (polling)… Ctrl+C to stop")

    try:
        asyncio.run(chan.run())
    except KeyboardInterrupt:
        console.print("\nbye 👋")


@app.command()
def init(force: bool = typer.Option(False, "--force", help="Overwrite existing .picobot/config.json")):
    """Initialize project-local .picobot/ structure and config.json."""
    res = init_project(force=force)
    if res.get("status") == "exists":
        typer.echo(f"✅ .picobot already initialized: {res['config']}")
    else:
        typer.echo("✅ Initialized .picobot")
        typer.echo(f"  - config: {res.get('config')}")
        typer.echo(f"  - workspace: {res.get('workspace')}")
        typer.echo(f"  - memory: {res.get('memory')}")
