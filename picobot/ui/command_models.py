from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class CommandResult:
    handled: bool
    should_exit: bool = False
    text: str | None = None
    bus_text: str | None = None

    @property
    def reply(self) -> str | None:
        return self.text
