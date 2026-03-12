from __future__ import annotations

import asyncio
from typing import Any
from uuid import uuid4

from picobot.bus.events import OutboundMessage, inbound_text, outbound_status
from picobot.bus.queue import MessageBus
from picobot.channels.base import Channel


class CLIChannel(Channel):
    """
    Channel adapter per la CLI.

    Responsabilità:
    - pubblicare inbound.text sul bus
    - emettere uno status immediato locale-side prima dell'elaborazione runtime
    - ricevere outbound.* dal ChannelManager
    - rendere disponibili i messaggi in uscita al loop CLI
    """

    def __init__(self, *, bus: MessageBus, session_id: str = "default") -> None:
        super().__init__(name="cli", bus=bus)
        self.default_session_id = (session_id or "default").strip() or "default"
        self.outbound_queue: asyncio.Queue[OutboundMessage] = asyncio.Queue()

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

        # Status immediato lato CLI: compare prima ancora che il runtime inizi davvero.
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

    async def recv_for_correlation(
        self,
        correlation_id: str,
        *,
        stop_on_final_text: bool = True,
    ) -> list[OutboundMessage]:
        collected: list[OutboundMessage] = []

        while True:
            msg = await self.outbound_queue.get()
            if not isinstance(msg, OutboundMessage):
                continue
            if msg.correlation_id != correlation_id:
                continue

            collected.append(msg)

            if msg.message_type == "outbound.error":
                break

            if stop_on_final_text and msg.message_type == "outbound.text":
                break

        return collected
