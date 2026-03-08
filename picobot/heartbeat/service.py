from __future__ import annotations

import asyncio
import logging

from picobot.bus.events import inbound_heartbeat_tick
from picobot.bus.queue import MessageBus

logger = logging.getLogger(__name__)


class HeartbeatService:
    """
    Servizio heartbeat.

    Pubblica periodicamente un evento sul MessageBus
    che altri componenti possono usare per:

    - health check
    - metriche
    - manutenzione
    """

    def __init__(
        self,
        *,
        bus: MessageBus,
        interval_s: int = 30,
        tick_name: str = "runtime",
    ) -> None:
        self.bus = bus
        self.interval_s = max(1, int(interval_s))
        self.tick_name = tick_name

        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="picobot-heartbeat")

    async def stop(self) -> None:
        self._running = False

        if self._task:
            self._task.cancel()

            try:
                await self._task
            except asyncio.CancelledError:
                pass

            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self.interval_s)

                await self.bus.publish(
                    inbound_heartbeat_tick(
                        tick_name=self.tick_name
                    )
                )

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception("Heartbeat failure")
