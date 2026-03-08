from __future__ import annotations

import logging
from typing import Dict

from picobot.bus.events import OutboundMessage
from picobot.bus.queue import MessageBus
from picobot.channels.base import Channel

logger = logging.getLogger(__name__)


class ChannelManager:
    """
    Gestisce tutti i canali.

    - registra channel adapter
    - dispatch outbound verso i canali
    """

    def __init__(self, *, bus: MessageBus) -> None:
        self.bus = bus
        self.channels: Dict[str, Channel] = {}

        self._unsubscribe = None

    def register(self, channel: Channel) -> None:
        logger.info("Registering channel: %s", channel.name)
        self.channels[channel.name] = channel

    async def start(self) -> None:
        self._unsubscribe = self.bus.subscribe(
            "outbound.*",
            self._dispatch_outbound,
        )

        for ch in self.channels.values():
            await ch.start()

    async def stop(self) -> None:
        if self._unsubscribe:
            self._unsubscribe()

        for ch in self.channels.values():
            try:
                await ch.stop()
            except Exception:
                logger.exception("Channel stop failed")

    async def _dispatch_outbound(self, message) -> None:
        if not isinstance(message, OutboundMessage):
            return

        channel_name = message.channel

        channel = self.channels.get(channel_name)

        if not channel:
            logger.warning("No channel registered for outbound: %s", channel_name)
            return

        try:
            await channel.publish(message)

        except Exception:
            logger.exception("Channel publish failed")
