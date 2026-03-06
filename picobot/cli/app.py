from __future__ import annotations


import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import typer

from picobot.agent.orchestrator import Orchestrator
from picobot.agent.prompts import detect_language
from picobot.channels.telegram import TelegramChannel
from picobot.config.init import init_project
from picobot.config.loader import load_config
from picobot.providers.ollama import OllamaProvider
from picobot.session.manager import SessionManager
from picobot.ui import ConsoleUI, ConsoleOptions, Status, handle_command, make_readline
from picobot.utils.helpers import workspace_path

app = typer.Typer(add_completion=False)


def _rewrite_slash_commands(line: str) -> str:
    """
    Deterministic CLI slash commands that map to explicit tool lines.
    Keeps router simple and tool args valid.
    """
    t = (line or "").strip()
    if not t.startswith("/"):
        return line

    # /wsearch <query>  -> tool web_search {"query": "...", "count": 5}
    if t.startswith("/wsearch"):
        q = t[len("/wsearch"):].strip()
        if not q:
            return line
        payload = {"query": q, "count": 5}
        return "tool web_search " + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    return line
def _print_banner(ui: ConsoleUI) -> None:
    ui.send_text("🤖 picobot")
    ui.send_text("  🔎 Retrieval (local KB)")
    ui.send_text("  🛠 Tools (YouTube transcript/summary, PDF ingest)")
    ui.send_text("  🎙 Podcast generator (trigger-based)")
    ui.send_text("  📝 Memory (global MEMORY + session history/summary)")
    ui.send_text("  ⌨️  Tab completion + history (type /help)")
    ui.send_text("")


def _run_coro(coro):
    """
    Run an async coroutine from sync CLI code, without nesting asyncio.run().
    prompt_toolkit may already create an event loop internally.
    """
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    if loop.is_running():
        raise RuntimeError("Event loop already running; cannot run coroutine from sync context.")
    return loop.run_until_complete(coro)


def _play_audio(cfg, audio_path: Path) -> None:
    tools = getattr(cfg, "tools", None)
    ffmpeg_bin = str(getattr(tools, "ffmpeg_bin", "ffmpeg") or "ffmpeg").strip() or "ffmpeg"
    aplay_bin = str(getattr(tools, "aplay_bin", "aplay") or "aplay").strip() or "aplay"

    ffplay = shutil.which("ffplay")
    if ffplay:
        subprocess.run([ffplay, "-nodisp", "-autoexit", str(audio_path)], check=False)
        return

    p1 = subprocess.Popen(
        [ffmpeg_bin, "-hide_banner", "-loglevel", "error", "-i", str(audio_path), "-f", "wav", "-"],
        stdout=subprocess.PIPE,
    )
    try:
        subprocess.run([aplay_bin, "-"], stdin=p1.stdout, check=False)
    finally:
        try:
            p1.terminate()
        except Exception:
            pass


@app.command()
def chat(session: str = typer.Option("default", "--session", "-s")) -> None:
    cfg = load_config()
    ws = workspace_path(cfg)
    sm = SessionManager(ws)

    ui = ConsoleUI(debug_enabled=bool(getattr(getattr(cfg, "debug", None), "enabled", False)))
    st = Status(ui)

    provider = OllamaProvider(cfg.ollama.base_url, cfg.ollama.model, timeout_s=cfg.ollama.timeout_s)
    orch = Orchestrator(cfg, provider, ws)

    current = sm.get(session)

    _print_banner(ui)

    read_line = make_readline(
        ws,
        ConsoleOptions(
            use_prompt_toolkit=bool(getattr(getattr(cfg, "ui", None), "use_prompt_toolkit", True)),
            vi_mode=bool(getattr(getattr(cfg, "ui", None), "vi_mode", False)),
        ),
    )

    global_memory = ws / "memory" / "MEMORY.md"
    global_memory.parent.mkdir(parents=True, exist_ok=True)
    if not global_memory.exists():
        global_memory.write_text("# Memory\n\n", encoding="utf-8")

    async def status_cb(msg: str) -> None:
        # terminal-only transient, never errors
        with st.show(msg):
            await asyncio.sleep(0)

    while True:
        try:
            user = read_line("You:").strip()
            user = _rewrite_slash_commands(user)
        except (EOFError, KeyboardInterrupt):
            ui.send_text("\n/exit")
            ui.send_text("bye 👋")
            return

        if not user:
            continue

        
        # --- deterministic rewrite for news (workflow-friendly) ---

        u = (user or "").strip()

        low = u.lower()

        if low.startswith("/news"):

            q = u.split(None, 1)[1].strip() if " " in u else ""

            if not q:

                user = "/help"

            else:

                user = f"news: {q}"

        elif low.startswith("news:"):

            q = u.split(":", 1)[1].strip()

            if q:

                user = f"news: {q}"

        cr = handle_command(user, session=current, session_manager=sm, cfg=cfg, workspace=ws)

        if cr.handled:
            if cr.exit_now:
                ui.send_text("/exit")
                ui.send_text(cr.reply or "bye 👋")
                return

            if cr.new_session_id:
                current = sm.get(cr.new_session_id)

            ui.send_text(cr.reply)

            if cr.play_audio_path:
                ap = Path(cr.play_audio_path).expanduser()
                if not ap.exists():
                    ui.send_text(f"❌ not found: {ap}")
                else:
                    _play_audio(cfg, ap)
            continue

        if cr.rewrite_text:
            user = cr.rewrite_text.strip()
            if not user:
                continue

        input_lang = detect_language(user, default=getattr(cfg, "default_language", "it"))

        async def _turn():
            return await orch.one_turn(current, user, status=status_cb, input_lang=input_lang)

        res = _run_coro(_turn())

        if getattr(getattr(cfg, "debug", None), "enabled", False):
            route = {"action": res.action, "kb_mode": res.kb_mode, "reason": res.reason}
            ui.debug(f" route={json.dumps(route, ensure_ascii=False)}")

        ui.send_text(f"🤖 {res.content}")
        ap = getattr(res, "audio_path", None)
        if ap:
            ui.send_text(f"📁 {ap}")


@app.command()
def telegram() -> None:
    cfg = load_config()
    if not cfg.telegram.enabled:
        raise typer.Exit(code=2)

    ws = workspace_path(cfg)
    sm = SessionManager(ws)

    provider = OllamaProvider(cfg.ollama.base_url, cfg.ollama.model, timeout_s=cfg.ollama.timeout_s)
    orch = Orchestrator(cfg, provider, ws)

    chan = TelegramChannel(cfg, sm, orch)
    print("📨 Telegram bot running (polling)… Ctrl+C to stop")

    try:
        asyncio.run(chan.run())
    except KeyboardInterrupt:
        print("\nbye 👋")


@app.command()
def init(force: bool = typer.Option(False, "--force", help="Overwrite existing .picobot/config.json")) -> None:
    """Initialize project-local .picobot/ structure and config.json."""
    res = init_project(force=force)
    if res.get("status") == "exists":
        typer.echo(f"✅ .picobot already initialized: {res['config']}")
    else:
        typer.echo("✅ Initialized .picobot")
        typer.echo(f"  - config: {res.get('config')}")
        typer.echo(f"  - workspace: {res.get('workspace')}")
        typer.echo(f"  - memory: {res.get('memory')}")
