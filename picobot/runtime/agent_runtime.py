from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from picobot.agent.application import Orchestrator
from picobot.bus.events import BusMessage, InboundMessage
from picobot.bus.queue import MessageBus
from picobot.config.schema import Config
from picobot.providers.ollama import OllamaProvider
from picobot.runtime.cron_handler import CronHandler
from picobot.runtime.event_publisher import RuntimeEventPublisher
from picobot.runtime.heartbeat_handler import HeartbeatHandler
from picobot.runtime.telegram_inbound_handler import TelegramInboundHandler
from picobot.session.manager import SessionManager

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    Runtime event-driven del progetto.

    Ruolo:
    - consuma inbound.text
    - delega inbound.cron_tick e inbound.heartbeat_tick a handler dedicati
    - delega inbound Telegram non testuali a handler dedicato
    - invoca il turn pipeline dell'agente
    - pubblica outbound e runtime events tramite RuntimeEventPublisher
    """

    def __init__(
        self,
        *,
        bus: MessageBus,
        cfg: Config,
        provider: OllamaProvider,
        workspace: Path,
        session_manager: SessionManager | None = None,
        orchestrator: Orchestrator | None = None,
    ) -> None:
        self.bus = bus
        self.cfg = cfg
        self.provider = provider
        self.workspace = Path(workspace).expanduser().resolve()
        self.sessions = session_manager or SessionManager(self.workspace)
        self.orchestrator = orchestrator or Orchestrator(cfg, provider, self.workspace)
        self.events = RuntimeEventPublisher(bus=bus)

        self.heartbeat_handler = HeartbeatHandler(
            events=self.events,
            workspace=self.workspace,
            session_manager=self.sessions,
            orchestrator_name=self.orchestrator.__class__.__name__,
        )
        self.cron_handler = CronHandler(events=self.events)
        self.telegram_inbound_handler = TelegramInboundHandler(
            bus=self.bus,
            events=self.events,
            orchestrator=self.orchestrator,
            session_manager=self.sessions,
        )

        self._unsubscribe_callbacks: list[Callable[[], None]] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.text", self._on_inbound_text)
        )
        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.cron_tick", self.cron_handler.handle)
        )
        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.heartbeat_tick", self.heartbeat_handler.handle)
        )
        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.telegram.voice_note", self.telegram_inbound_handler.handle_voice_note)
        )
        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.telegram.document", self.telegram_inbound_handler.handle_document)
        )

        self._started = True
        self.heartbeat_handler.bind_runtime_state(runtime_started=True)

    async def stop(self) -> None:
        self.heartbeat_handler.bind_runtime_state(runtime_started=False)

        for unsubscribe in self._unsubscribe_callbacks:
            try:
                unsubscribe()
            except Exception:
                logger.exception("Failed to unsubscribe runtime handler")
        self._unsubscribe_callbacks.clear()
        self._started = False

    async def _on_inbound_text(self, message: BusMessage) -> None:
        if not isinstance(message, InboundMessage):
            return

        session_id = (message.session_id or "default").strip() or "default"
        session = self.sessions.get(session_id)
        user_text = str(message.payload.get("text") or "").strip()

        if not user_text:
            await self.events.publish_empty_input_error(
                inbound=message,
                session=session,
            )
            return

        await self.events.publish_turn_started(
            inbound=message,
            session=session,
            user_text=user_text,
        )

        async def status_cb(text: str) -> None:
            await self.events.publish_status(
                inbound=message,
                session=session,
                text=text,
            )

        hooks = self.events.make_turn_hooks(
            inbound=message,
            session_id=session.session_id,
        )

        try:
            result = await self.orchestrator.one_turn(
                session=session,
                user_text=user_text,
                status=status_cb,
                hooks=hooks,
            )
        except Exception as exc:
            logger.exception("Runtime turn failed for session=%s", session.session_id)

            await self.events.publish_turn_failed(
                inbound=message,
                session=session,
                error=exc,
            )

            await self.events.publish_error(
                inbound=message,
                session=session,
                text=f"Errore runtime: {exc}",
            )
            return

        await self.events.publish_turn_completed(
            inbound=message,
            session=session,
            result=result,
        )

        await self.events.publish_turn_outputs(
            inbound=message,
            session=session,
            result=result,
        )
