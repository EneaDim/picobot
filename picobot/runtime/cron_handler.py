from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from picobot.bus.events import BusMessage, InboundMessage
from picobot.runtime.event_publisher import RuntimeEventPublisher

CronJobHandler = Callable[[InboundMessage], Awaitable[dict[str, Any] | None]]


class CronHandler:
    """
    Handler dedicato per inbound.cron_tick.

    Oggi:
    - modella i cron job come first-class runtime handlers
    - emette runtime.cron.job_started / completed / failed
    - supporta job registry semplice

    In assenza di un handler specifico per il job, completa in modalità noop.
    """

    def __init__(self, *, events: RuntimeEventPublisher) -> None:
        self.events = events
        self._jobs: dict[str, CronJobHandler] = {}

    def register(self, job_name: str, handler: CronJobHandler) -> None:
        self._jobs[str(job_name).strip()] = handler

    async def handle(self, message: BusMessage) -> None:
        if not isinstance(message, InboundMessage):
            return

        job_name = str(message.payload.get("job_name") or "").strip()
        if not job_name:
            await self.events.publish_runtime_event(
                inbound=message,
                session_id=message.session_id,
                event_type="runtime.cron.job_failed",
                payload={
                    "job_name": "",
                    "error": "missing job_name",
                },
            )
            return

        await self.events.publish_runtime_event(
            inbound=message,
            session_id=message.session_id,
            event_type="runtime.cron.job_started",
            payload={
                "job_name": job_name,
            },
        )

        handler = self._jobs.get(job_name)
        if handler is None:
            await self.events.publish_runtime_event(
                inbound=message,
                session_id=message.session_id,
                event_type="runtime.cron.job_completed",
                payload={
                    "job_name": job_name,
                    "status": "noop",
                    "details": "no registered handler",
                },
            )
            return

        try:
            result = await handler(message)
        except Exception as exc:
            await self.events.publish_runtime_event(
                inbound=message,
                session_id=message.session_id,
                event_type="runtime.cron.job_failed",
                payload={
                    "job_name": job_name,
                    "error": str(exc),
                },
            )
            raise

        await self.events.publish_runtime_event(
            inbound=message,
            session_id=message.session_id,
            event_type="runtime.cron.job_completed",
            payload={
                "job_name": job_name,
                "status": "ok",
                "result": result or {},
            },
        )
