from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class _Frame:
    message: str
    shown_at: float


class Status:
    """
    Transient, single-line status messages for TTYs.
    - Minimum display time per message (default: 1s)
    - Only redraw when message changes
    - Stack behavior for nested statuses
    """
    def __init__(self, enabled: bool = True, stream=None, min_display_s: float = 1.0) -> None:
        self.stream = stream or sys.stderr
        self.enabled = bool(enabled) and hasattr(self.stream, "isatty") and self.stream.isatty()
        self.min_display_s = float(min_display_s)
        self._stack: List[_Frame] = []
        self._last_rendered: Optional[str] = None

    def _clear_line(self) -> None:
        self.stream.write("\r\x1b[2K")
        self.stream.flush()

    def _render(self, message: Optional[str]) -> None:
        if not self.enabled:
            return
        if not message:
            self._clear_line()
            self._last_rendered = None
            return
        if message == self._last_rendered:
            return
        self._clear_line()
        self.stream.write(message)
        self.stream.flush()
        self._last_rendered = message

    def clear(self) -> None:
        if not self.enabled:
            return
        self._stack.clear()
        self._render(None)

    def _ensure_min_display(self, frame: _Frame) -> None:
        if not self.enabled:
            return
        elapsed = time.monotonic() - frame.shown_at
        remain = self.min_display_s - elapsed
        if remain > 0:
            time.sleep(remain)

    @contextmanager
    def show(self, message: str):
        if not self.enabled:
            yield
            return
        prev = self._stack[-1] if self._stack else None
        frame = _Frame(message=message, shown_at=time.monotonic())
        self._stack.append(frame)
        self._render(frame.message)
        try:
            yield
        finally:
            cur = self._stack.pop() if self._stack else None
            if cur:
                self._ensure_min_display(cur)
            self._render(prev.message if prev else None)
