from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import TypeAlias

from picobot.bus.events import BusMessage

logger = logging.getLogger(__name__)

MessageHandler: TypeAlias = Callable[[BusMessage], Awaitable[None] | None]


class MessageBus:
    """
    In-memory async message bus.

    È volutamente semplice:
    - queue centrale
    - publish
    - subscribe per message_type
    - wildcard prefix support ("inbound.*", "outbound.*", "runtime.*")
    - dispatch concorrente controllato dal loop asyncio
    """

    def __init__(self, *, max_queue_size: int = 0) -> None:
        self._queue: asyncio.Queue[BusMessage] = asyncio.Queue(maxsize=max_queue_size)
        self._subscribers: dict[str, list[MessageHandler]] = defaultdict(list)
        self._dispatch_task: asyncio.Task[None] | None = None
        self._running = False

    def subscribe(self, message_type: str, handler: MessageHandler) -> Callable[[], None]:
        self._subscribers[message_type].append(handler)

        def unsubscribe() -> None:
            handlers = self._subscribers.get(message_type, [])
            try:
                handlers.remove(handler)
            except ValueError:
                return
            if not handlers:
                self._subscribers.pop(message_type, None)

        return unsubscribe

    async def publish(self, message: BusMessage) -> None:
        await self._queue.put(message)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._dispatch_task = asyncio.create_task(self._dispatch_loop(), name="picobot-message-bus")

    async def stop(self) -> None:
        self._running = False
        if self._dispatch_task is None:
            return
        self._dispatch_task.cancel()
        try:
            await self._dispatch_task
        except asyncio.CancelledError:
            pass
        finally:
            self._dispatch_task = None

    async def join(self) -> None:
        await self._queue.join()

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    async def _dispatch_loop(self) -> None:
        while True:
            message = await self._queue.get()
            try:
                await self._dispatch(message)
            except Exception:
                logger.exception("Unhandled exception during bus dispatch: %s", message.message_type)
            finally:
                self._queue.task_done()

    async def _dispatch(self, message: BusMessage) -> None:
        handlers = self._matched_handlers(message.message_type)
        if not handlers:
            logger.debug("No subscribers for message_type=%s", message.message_type)
            return

        for handler in handlers:
            try:
                result = handler(message)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "Message handler failed for type=%s handler=%r",
                    message.message_type,
                    handler,
                )

    def _matched_handlers(self, message_type: str) -> list[MessageHandler]:
        matched: list[MessageHandler] = []

        for pattern, handlers in self._subscribers.items():
            if self._matches(pattern, message_type):
                matched.extend(list(handlers))

        return matched

    @staticmethod
    def _matches(pattern: str, message_type: str) -> bool:
        if pattern == message_type:
            return True
        if pattern.endswith("*"):
            prefix = pattern[:-1]
            return message_type.startswith(prefix)
        return False
