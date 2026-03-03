from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

from picobot.tools.base import ToolSpec


class ToolRegistry:

    def resolve_name(self, name: str) -> str:
        n = (name or "").strip()
        if not n:
            return ""
        if n in self.tools:
            return n
        # common normalizations
        n2 = n.replace("-", "_")
        if n2 in self.tools:
            return n2
        n3 = n.replace("_", "-")
        if n3 in self.tools:
            return n3
        # explicit aliases (keep minimal)
        aliases = {
            "py": "sandbox_python",
            "python": "sandbox_python",
            "sandbox:python": "sandbox_python",
            "file": "sandbox_file",
            "sandbox:file": "sandbox_file",
        }
        a = aliases.get(n)
        if a and a in self.tools:
            return a
        return n  # fallback (unknown)
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
