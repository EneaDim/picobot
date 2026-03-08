from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from picobot.bus.events import inbound_cron_tick
from picobot.bus.queue import MessageBus

logger = logging.getLogger(__name__)


@dataclass
class CronJob:
    name: str
    interval_s: int


class CronService:
    """
    Scheduler semplice.

    Non usa dipendenze esterne.
    Pubblica inbound.cron_tick sul bus.
    """

    def __init__(self, *, bus: MessageBus) -> None:
        self.bus = bus
        self.jobs: list[CronJob] = []

        self._task: asyncio.Task | None = None
        self._running = False
        self._last_run: dict[str, float] = {}

    def register_job(self, name: str, interval_s: int) -> None:
        self.jobs.append(CronJob(name=name, interval_s=max(1, int(interval_s))))

    async def start(self) -> None:
        if self._running:
            return

        self._running = True
        self._task = asyncio.create_task(self._loop(), name="picobot-cron")

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
                now = time.time()

                for job in self.jobs:
                    last = self._last_run.get(job.name, 0)

                    if now - last >= job.interval_s:
                        self._last_run[job.name] = now

                        await self.bus.publish(
                            inbound_cron_tick(
                                job_name=job.name
                            )
                        )

                await asyncio.sleep(1)

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception("Cron loop error")
