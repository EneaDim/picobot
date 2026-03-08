from __future__ import annotations

from abc import ABC, abstractmethod

from picobot.bus.events import BusMessage, OutboundMessage
from picobot.bus.queue import MessageBus


class Channel(ABC):
    def __init__(self, *, name: str, bus: MessageBus) -> None:
        self.name = name
        self.bus = bus

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def publish(self, message: BusMessage) -> None:
        await self.bus.publish(message)

    @abstractmethod
    async def handle_outbound(self, message: OutboundMessage) -> None:
        raise NotImplementedError
