from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from picobot.tools.base import ToolSpec


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, tool: ToolSpec) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolSpec:
        if name not in self._tools:
            raise KeyError(f"unknown tool: {name}")
        return self._tools[name]

    def list(self) -> list[str]:
        return sorted(self._tools.keys())

    def specs(self) -> list[ToolSpec]:
        return [self._tools[k] for k in self.list()]


@dataclass(frozen=True)
class ToolResult:
    name: str
    data: dict
