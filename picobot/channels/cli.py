from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from picobot.bus.events import OutboundMessage, RuntimeEvent, inbound_text, outbound_status
from picobot.bus.queue import MessageBus
from picobot.channels.base import Channel


class CLIChannel(Channel):
    """
    Channel adapter per la CLI.

    Responsabilità:
    - pubblicare inbound.text sul bus
    - emettere uno status immediato locale-side prima dell'elaborazione runtime
    - ricevere outbound.* dal ChannelManager
    - ricevere runtime.* dal ChannelManager
    - rendere disponibili i messaggi in uscita al loop CLI
    """

    def __init__(self, *, bus: MessageBus, session_id: str = "default") -> None:
        super().__init__(name="cli", bus=bus)
        self.default_session_id = (session_id or "default").strip() or "default"
        self.outbound_queue: asyncio.Queue[object] = asyncio.Queue()

    async def start(self) -> None:
        return

    async def stop(self) -> None:
        return

    async def send_text(
        self,
        *,
        text: str,
        session_id: str | None = None,
        correlation_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        corr = correlation_id or uuid4().hex
        sid = (session_id or self.default_session_id)

        await self.bus.publish(
            outbound_status(
                channel=self.name,
                chat_id="cli",
                session_id=sid,
                text="📨 Messaggio inviato al bus…",
                correlation_id=corr,
                causation_id=None,
            )
        )

        message = inbound_text(
            channel=self.name,
            chat_id="cli",
            session_id=sid,
            text=text,
            correlation_id=corr,
            metadata=metadata or {},
        )
        await self.bus.publish(message)
        return corr

    async def handle_outbound(self, message: OutboundMessage) -> None:
        await self.outbound_queue.put(message)

    async def handle_runtime(self, message: RuntimeEvent) -> None:
        await self.outbound_queue.put(message)

    async def recv_for_correlation(
        self,
        correlation_id: str,
        *,
        stop_on_final_text: bool = True,
    ) -> list[object]:
        collected: list[object] = []

        while True:
            msg = await self.outbound_queue.get()
            if getattr(msg, "correlation_id", None) != correlation_id:
                continue

            collected.append(msg)

            if getattr(msg, "message_type", "") == "outbound.error":
                break

            if stop_on_final_text and getattr(msg, "message_type", "") == "outbound.text":
                break

        return collected
