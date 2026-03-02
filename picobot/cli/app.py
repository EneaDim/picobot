from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import typer
from rich.console import Console

from picobot.agent.orchestrator import Orchestrator
from picobot.agent.prompts import detect_language
from picobot.channels.telegram import TelegramChannel
from picobot.config.init import init_project
from picobot.config.loader import load_config
from picobot.providers.ollama import OllamaProvider
from picobot.session.manager import SessionManager
from picobot.ui.commands import handle_command
from picobot.ui.console import ConsoleOptions, make_readline
from picobot.ui.status import Status
from picobot.utils.helpers import workspace_path

app = typer.Typer(add_completion=False)
console = Console()


def _strip_emojis(msg: str) -> str:
    return (
        msg.replace("🧭 ", "")
        .replace("🔎 ", "")
        .replace("💭 ", "")
        .replace("✅ ", "")
        .replace("🛠 ", "")
        .replace("🎙 ", "")
        .replace("🗣 ", "")
        .replace("📨 ", "")
    )


def _print_banner() -> None:
    console.print("🤖 picobot")
    console.print("  🔎 Retrieval (local KB)")
    console.print("  🛠 Tools (YouTube transcript/summary, PDF ingest)")
    console.print("  🎙 Podcast generator (trigger-based)")
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



def _find_recent_podcasts(cfg, limit: int = 10) -> list[Path]:
    pcfg = getattr(cfg, "podcast", None)
    out_dir = Path(getattr(pcfg, "output_dir", "outputs/podcasts") if pcfg else "outputs/podcasts").expanduser()
    if not out_dir.exists():
        return []
    cands: list[Path] = []
    # new layout: outputs/podcasts/<run>/podcast.*
    for p in out_dir.glob("*/podcast.*"):
        if p.is_file():
            cands.append(p)
    # fallback: old layout: outputs/podcasts/podcast.*
    for p in out_dir.glob("podcast.*"):
        if p.is_file():
            cands.append(p)
    cands = sorted(set(cands), key=lambda x: x.stat().st_mtime, reverse=True)
    return cands[: max(1, int(limit))]


def _play_audio(cfg, audio_path: Path) -> None:
    tools = getattr(cfg, "tools", None)
    ffmpeg_bin = str(getattr(tools, "ffmpeg_bin", "ffmpeg") or "ffmpeg").strip() or "ffmpeg"
    aplay_bin = str(getattr(tools, "aplay_bin", "aplay") or "aplay").strip() or "aplay"

    # Prefer ffplay if available (best for mp3/ogg)
    ffplay = shutil.which("ffplay")
    if ffplay:
        subprocess.run([ffplay, "-nodisp", "-autoexit", str(audio_path)], check=False)
        return

    # Otherwise: decode to wav on stdout -> aplay
    # aplay expects wav; ffmpeg handles mp3/ogg/wav
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
        # We should never be here because we don't call this from inside an async context,
        # but keep a safe error if it happens.
        raise RuntimeError("Event loop already running; cannot run coroutine from sync context.")
    return loop.run_until_complete(coro)


@app.command()
def chat(session: str = typer.Option("default", "--session", "-s")) -> None:
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

    async def status_cb(msg: str) -> None:
        if not cfg.ui.use_emojis:
            msg = _strip_emojis(msg)
        with st.show(msg):
            await asyncio.sleep(0)

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


        if user.startswith("/podcast"):
            parts = user.split()
            if len(parts) >= 2 and parts[1] == "list":
                items = _find_recent_podcasts(cfg, limit=10)
                if not items:
                    console.print("(no podcasts found)")
                    continue
                console.print("Recent podcasts:")
                for i, ap in enumerate(items, start=1):
                    console.print(f"  {i}. {ap}")
                continue

            if len(parts) >= 2 and parts[1] == "play":
                if len(parts) >= 3:
                    ap = Path(" ".join(parts[2:])).expanduser()
                    if not ap.exists():
                        console.print(f"❌ not found: {ap}")
                        continue
                    console.print(f"▶️  Playing: {ap}")
                    _play_audio(cfg, ap)
                    continue

                items = _find_recent_podcasts(cfg, limit=1)
                if not items:
                    console.print("(no podcasts found)")
                    continue
                ap = items[0]
                console.print(f"▶️  Playing latest: {ap}")
                _play_audio(cfg, ap)
                continue

            console.print("Usage: /podcast list | /podcast play [path]")
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

        cr = handle_command(user, session=current, session_manager=sm, cfg=cfg)
        if cr.handled:
            if cr.new_session_id:
                current = sm.get(cr.new_session_id)
            console.print(cr.reply)
            continue

        input_lang = detect_language(user, default=getattr(cfg, "default_language", "it"))

        async def _turn():
            return await orch.one_turn(current, user, status=status_cb, input_lang=input_lang)

        res = _run_coro(_turn())
        st.clear()

        if cfg.debug.enabled:
            route = {"action": res.action, "kb_mode": res.kb_mode, "reason": res.reason}
            console.print(f" route={json.dumps(route, ensure_ascii=False)}")

        console.print(f"🤖 {res.content}")
        ap = getattr(res, "audio_path", None)
        if ap:
            console.print(f"📁 {ap}")
@app.command()
def telegram() -> None:
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
