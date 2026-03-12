from __future__ import annotations

import asyncio
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


class TerminalUI:
    def __init__(self, *, cfg, workspace: Path) -> None:
        self.cfg = cfg
        self.workspace = Path(workspace).expanduser().resolve()

        self._status_visible = False
        self._status_text = ""
        self._status_since = 0.0
        self._status_min_visible_sec = 0.35

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
        if telegram_enabled:
            print("Telegram channel abilitato.")

        if not self._use_prompt_toolkit:
            print("Nota: prompt_toolkit non attivo, quindi TAB/history/editing avanzato non sono disponibili.")

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
        print(f"\r{self._status_text}", end="", flush=True)

    def show_status(self, text: str) -> None:
        line = f"⏳ {str(text or '').strip()}"
        if not line.strip():
            return

        if self._status_visible:
            print("\r\033[2K", end="", flush=True)

        self._status_text = line
        self._status_visible = True
        self._status_since = time.monotonic()
        print(f"\r{line}", end="", flush=True)

    def clear_status(self) -> None:
        if self._status_visible:
            elapsed = time.monotonic() - self._status_since
            remaining = self._status_min_visible_sec - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self._wipe_status_line()

    def print_debug(self, text: str) -> None:
        body = str(text or "").rstrip()
        if not body:
            return

        had_status = self._status_visible
        saved_status = self._status_text

        if had_status:
            print("\r\033[2K", end="", flush=True)
            self._status_visible = False

        for line in body.splitlines():
            print(f"🐞 {line}", flush=True)

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

            if kind == "error" and text:
                self.print_error(text)
                saw_non_status = True
                break

        self.clear_status()
