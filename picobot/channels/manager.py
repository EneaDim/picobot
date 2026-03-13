from __future__ import annotations

import logging
import os
from typing import Dict

from picobot.bus.events import OutboundMessage, RuntimeEvent
from picobot.bus.queue import MessageBus
from picobot.channels.base import Channel

logger = logging.getLogger(__name__)
DEBUG_RUNTIME = os.getenv("PICOBOT_TRACE_INTERNAL", "0").strip().lower() in {"1", "true", "yes", "on"}


def _debug(msg: str) -> None:
    if DEBUG_RUNTIME:
        print(f"[trace][manager] {msg}")


class ChannelManager:
    """
    Gestisce tutti i canali.

    - registra channel adapter
    - dispatch outbound verso i canali
    - dispatch runtime verso i canali che li supportano
    """

    def __init__(self, *, bus: MessageBus) -> None:
        self.bus = bus
        self.channels: Dict[str, Channel] = {}
        self._unsubscribe_outbound = None
        self._unsubscribe_runtime = None

    def register(self, channel: Channel) -> None:
        logger.info("Registering channel: %s", channel.name)
        self.channels[channel.name] = channel
        _debug(f"registered channel={channel.name}")

    async def start(self) -> None:
        self._unsubscribe_outbound = self.bus.subscribe(
            "outbound.*",
            self._dispatch_outbound,
        )
        self._unsubscribe_runtime = self.bus.subscribe(
            "runtime.*",
            self._dispatch_runtime,
        )
        _debug("subscribed to outbound.* and runtime.*")

        for ch in self.channels.values():
            _debug(f"starting channel={ch.name}")
            await ch.start()

    async def stop(self) -> None:
        if self._unsubscribe_outbound:
            self._unsubscribe_outbound()
        if self._unsubscribe_runtime:
            self._unsubscribe_runtime()

        for ch in self.channels.values():
            try:
                await ch.stop()
            except Exception:
                logger.exception("Channel stop failed")

    async def _dispatch_outbound(self, message) -> None:
        if not isinstance(message, OutboundMessage):
            _debug(f"ignored non-OutboundMessage type={type(message).__name__}")
            return

        channel_name = message.channel
        _debug(
            f"dispatch outbound type={message.message_type} "
            f"channel={channel_name} corr={message.correlation_id}"
        )

        channel = self.channels.get(channel_name)
        if not channel:
            logger.warning("No channel registered for outbound: %s", channel_name)
            _debug(f"missing channel={channel_name}")
            return

        try:
            await channel.handle_outbound(message)
            _debug(f"delivered outbound to channel={channel_name}")
        except Exception:
            logger.exception("Channel outbound delivery failed")

    async def _dispatch_runtime(self, message) -> None:
        if not isinstance(message, RuntimeEvent):
            _debug(f"ignored non-RuntimeEvent type={type(message).__name__}")
            return

        channel_name = message.channel
        _debug(
            f"dispatch runtime type={message.message_type} "
            f"channel={channel_name} corr={message.correlation_id}"
        )

        channel = self.channels.get(channel_name)
        if not channel:
            _debug(f"missing channel for runtime={channel_name}")
            return

        handler = getattr(channel, "handle_runtime", None)
        if handler is None:
            _debug(f"channel={channel_name} has no handle_runtime")
            return

        try:
            await handler(message)
            _debug(f"delivered runtime to channel={channel_name}")
        except Exception:
            logger.exception("Channel runtime delivery failed")
