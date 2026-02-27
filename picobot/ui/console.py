from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# prompt_toolkit optional
try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
    from prompt_toolkit.styles import Style
    _HAS_PT = True
except Exception:
    PromptSession = None  # type: ignore
    AutoSuggestFromHistory = None  # type: ignore
    Completer = None  # type: ignore
    Completion = None  # type: ignore
    FileHistory = None  # type: ignore
    KeyBindings = None  # type: ignore
    Style = None  # type: ignore
    _HAS_PT = False


@dataclass
class ConsoleOptions:
    use_prompt_toolkit: bool = True
    vi_mode: bool = False


if _HAS_PT:
    class _PicoCompleter(Completer):  # type: ignore[misc]
        def __init__(self, workspace: Path) -> None:
            self.workspace = workspace
            self.commands = [
                "/help",
                "/exit",
                "/mem show",
                "/mem clear",
                "/session list",
                "/session set ",
                "/kb set ",
            ]

        def _kb_names(self) -> list[str]:
            kb_root = self.workspace / "docs"
            if not kb_root.exists():
                return ["default"]
            out = [d.name for d in kb_root.iterdir() if d.is_dir()]
            return sorted(out) or ["default"]

        def _session_names(self) -> list[str]:
            sroot = self.workspace / "sessions"
            if not sroot.exists():
                return ["default"]
            out = [d.name for d in sroot.iterdir() if d.is_dir()]
            return sorted(out) or ["default"]

        def get_completions(self, document, complete_event):
            text = document.text_before_cursor

            if text.startswith("/"):
                for c in self.commands:
                    if c.startswith(text):
                        yield Completion(c, start_position=-len(text))

            if text.startswith("/kb set "):
                prefix = text[len("/kb set "):]
                for k in self._kb_names():
                    if k.startswith(prefix):
                        yield Completion(k, start_position=-len(prefix))
                return

            if text.startswith("/session set "):
                prefix = text[len("/session set "):]
                for s in self._session_names():
                    if s.startswith(prefix):
                        yield Completion(s, start_position=-len(prefix))
                return
else:
    _PicoCompleter = None  # type: ignore


def make_readline(workspace: Path, opts: ConsoleOptions) -> Callable[[str], str]:
    """
    Returns read_line(prompt: str) -> str
    Uses prompt_toolkit if available + TTY, otherwise falls back to input().
    """
    if (not opts.use_prompt_toolkit) or (not _HAS_PT) or (PromptSession is None) or (not sys.stdin.isatty()):
        def _fallback(prompt: str) -> str:
            return input(prompt + " " if prompt and not prompt.endswith(" ") else prompt)
        return _fallback

    hist_path = workspace / "memory" / ".cli_history"
    hist_path.parent.mkdir(parents=True, exist_ok=True)

    kb = KeyBindings()  # type: ignore[operator]

    @kb.add("c-l")
    def _(event):
        event.app.renderer.clear()

    style = Style.from_dict({  # type: ignore[operator]
        "you": "#ff8800 bold",
    })

    session = PromptSession(  # type: ignore[operator]
        history=FileHistory(str(hist_path)),  # type: ignore[operator]
        auto_suggest=AutoSuggestFromHistory(),  # type: ignore[operator]
        completer=_PicoCompleter(workspace),  # type: ignore[operator]
        complete_while_typing=True,
        key_bindings=kb,
        vi_mode=opts.vi_mode,
        style=style,
    )

    def _read(prompt: str) -> str:
        if prompt.strip().startswith("You:"):
            return session.prompt([("class:you", "You:"), ("", " ")])
        return session.prompt(prompt)

    return _read
