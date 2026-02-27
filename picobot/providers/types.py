from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ChatResponse:
    content: str
    tool_calls: list[ToolCall]

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)
