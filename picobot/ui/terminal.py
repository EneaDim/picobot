from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Callable

from picobot.ui.render import (
    assistant_block,
    audio_block,
    banner_lines,
    error_block,
    info_block,
    outbound_kind_and_text,
    prompt_label,
    tool_block,
)
from picobot.ui.command_catalog import COMMAND_WORDS

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import WordCompleter
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.patch_stdout import patch_stdout

    HAVE_PROMPT_TOOLKIT = True
except Exception:
    PromptSession = None  # type: ignore[assignment]
    AutoSuggestFromHistory = None  # type: ignore[assignment]
    WordCompleter = None  # type: ignore[assignment]
    HTML = None  # type: ignore[assignment]
    FileHistory = None  # type: ignore[assignment]
    patch_stdout = None  # type: ignore[assignment]
    HAVE_PROMPT_TOOLKIT = False

DEBUG_RUNTIME = os.getenv("PICOBOT_DEBUG_CLI", "0").strip().lower() in {"1", "true", "yes", "on"}


def _short_status_from_runtime(msg) -> str | None:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})

    if mtype == "runtime.turn_started":
        return "📥 Turn started…"

    if mtype == "runtime.turn.route_selected":
        action = str(payload.get("route_action") or "").strip()
        name = str(payload.get("route_name") or "").strip()
        if action and name:
            if action == "tool":
                return f"🧭 Route → tool:{name}"
            if action == "workflow":
                return f"🧭 Route → workflow:{name}"
            return f"🧭 Route → {action}:{name}"
        return "🧭 Routing…"

    if mtype == "runtime.retrieval.started":
        return "🔎 Retrieving context…"

    if mtype == "runtime.retrieval.completed":
        return "🔎 Retrieval completed"

    if mtype == "runtime.turn.context_built":
        return "🧩 Context ready…"

    if mtype == "runtime.tool.started":
        tool_name = str(payload.get("tool_name") or "").strip()
        if tool_name == "tts":
            return "🔊 Generating audio…"
        if tool_name == "stt":
            return "🎙 Transcribing audio…"
        if tool_name == "yt_summary" or tool_name == "yt_transcript":
            return "📺 Processing YouTube content…"
        if tool_name == "python":
            return "🐍 Running Python…"
        if tool_name == "fetch":
            return "🌐 Fetching content…"
        if tool_name:
            return f"🛠 Running {tool_name}…"
        return "🛠 Running tool…"

    if mtype == "runtime.tool.completed":
        ok = payload.get("ok")
        return "✅ Tool completed" if ok is not False else "❌ Tool failed"

    if mtype == "runtime.tool.failed":
        return "❌ Tool failed"

    if mtype == "runtime.memory.updated":
        return "🧠 Updating memory…"

    if mtype == "runtime.turn_completed":
        return "🏁 Completed"

    if mtype == "runtime.turn_failed":
        return "❌ Failed"

    return None


def _format_runtime_event(msg) -> str | None:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})

    if mtype == "runtime.turn_started":
        return f"📥 turn     started    text_len={payload.get('text_len', '?')}"

    if mtype == "runtime.turn.route_selected":
        lines = [
            f"🧭 route    selected   {payload.get('route_action', '?')}:{payload.get('route_name', '?')}",
            f"   source={payload.get('route_source', '?')} score={payload.get('route_score', 0.0):.3f}",
        ]
        reason = payload.get("route_reason")
        if reason:
            lines.append(f"   reason={reason}")
        candidates = list(payload.get("route_candidates", []) or [])
        if candidates:
            lines.append("   candidates:")
            for item in candidates[:4]:
                lines.append(f"   - {item}")
        return "\n".join(lines)

    if mtype == "runtime.retrieval.started":
        return (
            f"🔎 retrieval started   kb={payload.get('kb_name', '?')} "
            f"top_k={payload.get('top_k', '?')}"
        )

    if mtype == "runtime.retrieval.completed":
        if payload.get("ok") is False:
            return f"❌ retrieval failed    error={payload.get('error', '?')}"
        return (
            f"🔎 retrieval done      hits={payload.get('hits', 0)} "
            f"context_chars={payload.get('context_chars', 0)}"
        )

    if mtype == "runtime.turn.context_built":
        return (
            f"🧩 context   built     workflow={payload.get('workflow_name', '?')} "
            f"history={payload.get('history_messages_count', 0)} "
            f"facts={payload.get('memory_facts_count', 0)} "
            f"summary={'yes' if payload.get('summary_present') else 'no'} "
            f"retrieval={'yes' if payload.get('retrieval_present') else 'no'}"
        )

    if mtype == "runtime.tool.started":
        return (
            f"🛠 tool      started   name={payload.get('tool_name', '?')} "
            f"workflow={payload.get('workflow_name', '?')}"
        )

    if mtype == "runtime.tool.completed":
        return (
            f"✅ tool      done      name={payload.get('tool_name', '?')} "
            f"ok={payload.get('ok', True)}"
        )

    if mtype == "runtime.tool.failed":
        return (
            f"❌ tool      failed    name={payload.get('tool_name', '?')} "
            f"error={payload.get('error', '?')}"
        )

    if mtype == "runtime.audio.generated":
        return f"🎧 audio     generated path={payload.get('audio_path', '?')}"

    if mtype == "runtime.memory.updated":
        facts = payload.get("facts_count", "?")
        return f"🧠 memory    updated   facts={facts}"

    if mtype == "runtime.turn_completed":
        return (
            f"🏁 turn      completed action={payload.get('action', '?')} "
            f"reason={payload.get('reason', '?')} "
            f"provider={payload.get('provider_name', '-') or '-'} "
            f"hits={payload.get('retrieval_hits', 0)} "
            f"audio={'yes' if payload.get('has_audio') else 'no'}"
        )

    if mtype == "runtime.turn_failed":
        return f"❌ turn      failed    error={payload.get('error', '?')}"

    return None


class TerminalUI:
    def __init__(self, *, cfg, workspace: Path) -> None:
        self.cfg = cfg
        self.workspace = Path(workspace).expanduser().resolve()

        self._status_visible = False
        self._status_text = ""
        self._status_since = 0.0
        self._status_min_visible_sec = 0.22
        self._runtime_debug_enabled = DEBUG_RUNTIME

        ui_cfg = getattr(cfg, "ui", None)
        use_pt = bool(getattr(ui_cfg, "use_prompt_toolkit", True))
        vi_mode = bool(getattr(ui_cfg, "vi_mode", False))

        self._session = None
        self._use_prompt_toolkit = bool(HAVE_PROMPT_TOOLKIT and use_pt)

        if self._use_prompt_toolkit:
            history_path = self.workspace / ".cli_history"
            history_path.parent.mkdir(parents=True, exist_ok=True)

            completer = WordCompleter(
                COMMAND_WORDS,
                ignore_case=True,
                sentence=True,
                match_middle=True,
            )

            self._session = PromptSession(
                history=FileHistory(str(history_path)),
                auto_suggest=AutoSuggestFromHistory(),
                completer=completer,
                complete_while_typing=True,
                vi_mode=vi_mode,
            )

    def print_banner(self, *, telegram_enabled: bool) -> None:
        for line in banner_lines():
            print(line)
        print(f"🐞 Debug: {'ON' if self._runtime_debug_enabled else 'OFF'}")
        print("🧠 Providers: Ollama, Gemini")
        if telegram_enabled:
            print("📨 Telegram channel enabled.")

        if not self._use_prompt_toolkit:
            print("ℹ️ prompt_toolkit not active, so TAB/history/advanced editing are not available.")

    def _wipe_status_line(self) -> None:
        if not self._status_visible:
            return
        print("\r\033[2K", end="", flush=True)
        self._status_visible = False
        self._status_text = ""
        self._status_since = 0.0

    def _redraw_status_line(self) -> None:
        if not self._status_text:
            return
        self._status_visible = True
        print(f"\r⏳ {self._status_text}", end="", flush=True)

    def show_status(self, text: str) -> None:
        clean = str(text or "").strip()
        if not clean:
            return

        if self._status_visible:
            print("\r\033[2K", end="", flush=True)

        self._status_text = clean
        self._status_visible = True
        self._status_since = time.monotonic()
        print(f"\r⏳ {clean}", end="", flush=True)

    def clear_status(self) -> None:
        if self._status_visible:
            elapsed = time.monotonic() - self._status_since
            remaining = self._status_min_visible_sec - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._wipe_status_line()

    def print_debug(self, text: str) -> None:
        if not self._runtime_debug_enabled:
            return

        body = str(text or "").rstrip()
        if not body:
            return

        saved_status = self._status_text if self._status_visible else ""

        if self._status_visible:
            print("\r\033[2K", end="", flush=True)
            self._status_visible = False

        for line in body.splitlines():
            print(f"🔹 {line}", flush=True)

        if saved_status:
            self._status_text = saved_status
            self._redraw_status_line()

    def print_info(self, text: str) -> None:
        self.clear_status()
        print(info_block(text), flush=True)

    def print_assistant(self, text: str) -> None:
        self.clear_status()
        print(assistant_block(text), flush=True)

    def print_error(self, text: str) -> None:
        self.clear_status()
        print(error_block(text), flush=True)

    def print_audio(self, text: str) -> None:
        self.clear_status()
        print(audio_block(text), flush=True)

    def print_tool(self, text: str) -> None:
        self.clear_status()
        print(tool_block(text), flush=True)

    async def prompt(self) -> str:
        self.clear_status()

        if self._session is not None:
            assert patch_stdout is not None
            assert HTML is not None
            with patch_stdout():
                value = await self._session.prompt_async(
                    HTML(f"<ansicyan>{prompt_label()}</ansicyan>")
                )
                return value.strip()

        return (await asyncio.to_thread(input, prompt_label())).strip()

    async def drain_messages(
        self,
        *,
        cli_channel,
        correlation_id: str,
        debug_cb: Callable[[str], None] | None = None,
        idle_after_terminal_ms: int = 350,
    ) -> None:
        saw_non_status = False

        while True:
            try:
                timeout_sec = max(idle_after_terminal_ms, 80) / 1000.0 if saw_non_status else None
                if timeout_sec is None:
                    msg = await cli_channel.outbound_queue.get()
                else:
                    msg = await asyncio.wait_for(cli_channel.outbound_queue.get(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                break

            if getattr(msg, "correlation_id", None) != correlation_id:
                continue

            mtype = str(getattr(msg, "message_type", "") or "")

            if mtype.startswith("runtime."):
                short = _short_status_from_runtime(msg)
                if short:
                    self.show_status(short)

                if self._runtime_debug_enabled:
                    formatted = _format_runtime_event(msg)
                    if formatted:
                        self.print_debug(formatted)
                continue

            kind, text = outbound_kind_and_text(msg)

            if kind == "status":
                if text:
                    self.show_status(text)
                continue

            if kind == "assistant" and text:
                self.print_assistant(text)
                saw_non_status = True
                continue

            if kind == "audio" and text:
                self.print_audio(text)
                saw_non_status = True
                continue

            if kind == "tool" and text:
                self.print_tool(text)
                saw_non_status = True
                continue

            if kind == "error" and text:
                self.print_error(text)
                saw_non_status = True
                break

        self.clear_status()
