from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ChannelName = Literal["cli", "telegram"]


@dataclass(slots=True)
class InboundMessage:
    channel: ChannelName
    chat_id: str  # telegram chat_id or cli pseudo id
    session_id: str
    user_text: str
    message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OutboundMessage:
    channel: ChannelName
    chat_id: str
    session_id: str
    content: str
    reply_to_message_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
