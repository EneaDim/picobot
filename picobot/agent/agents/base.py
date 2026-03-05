from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class AgentResult:
    name: str
    ok: bool
    text: str
    data: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    name: str

    async def run(self, *, input_text: str, lang: str, memory_ctx: str) -> AgentResult:
        ...
