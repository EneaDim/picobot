from __future__ import annotations

from typing import Protocol

from picobot.providers.types import ChatResponse


class ChatProvider(Protocol):
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict] | None = None,
        max_tokens: int | None = None,
        temperature: float = 0.1,
    ) -> ChatResponse:
        ...
