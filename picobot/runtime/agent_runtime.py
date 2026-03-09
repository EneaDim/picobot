from __future__ import annotations

import logging
from pathlib import Path

from picobot.agent.orchestrator import Orchestrator
from picobot.bus.events import (
    BusMessage,
    InboundMessage,
    outbound_audio,
    outbound_error,
    outbound_status,
    outbound_text,
    runtime_event,
)
from picobot.bus.queue import MessageBus
from picobot.config.schema import Config
from picobot.providers.ollama import OllamaProvider
from picobot.session.manager import SessionManager

logger = logging.getLogger(__name__)


class AgentRuntime:
    """
    Primo runtime event-driven del progetto.
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

        self._unsubscribe_callbacks: list[callable] = []
        self._started = False

    async def start(self) -> None:
        if self._started:
            return

        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.text", self._on_inbound_text)
        )
        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.cron_tick", self._on_inbound_not_implemented)
        )
        self._unsubscribe_callbacks.append(
            self.bus.subscribe("inbound.heartbeat_tick", self._on_inbound_not_implemented)
        )

        self._started = True

    async def stop(self) -> None:
        for unsubscribe in self._unsubscribe_callbacks:
            try:
                unsubscribe()
            except Exception:
                logger.exception("Failed to unsubscribe runtime handler")
        self._unsubscribe_callbacks.clear()
        self._started = False

    async def _on_inbound_not_implemented(self, message: BusMessage) -> None:
        if not isinstance(message, InboundMessage):
            return

        await self.bus.publish(
            runtime_event(
                event_type="runtime.inbound_ignored",
                channel=message.channel,
                chat_id=message.chat_id,
                session_id=message.session_id,
                correlation_id=message.correlation_id,
                causation_id=message.message_id,
                payload={
                    "reason": "not_implemented_yet",
                    "message_type": message.message_type,
                },
            )
        )

    async def _on_inbound_text(self, message: BusMessage) -> None:
        if not isinstance(message, InboundMessage):
            return

        session_id = (message.session_id or "default").strip() or "default"
        session = self.sessions.get(session_id)
        user_text = str(message.payload.get("text") or "").strip()

        if not user_text:
            await self.bus.publish(
                outbound_error(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    session_id=session.session_id,
                    text="Messaggio vuoto.",
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                )
            )
            return

        await self.bus.publish(
            runtime_event(
                event_type="runtime.turn_started",
                channel=message.channel,
                chat_id=message.chat_id,
                session_id=session.session_id,
                correlation_id=message.correlation_id,
                causation_id=message.message_id,
                payload={
                    "input_type": message.message_type,
                    "text_len": len(user_text),
                },
            )
        )

        async def status_cb(text: str) -> None:
            await self.bus.publish(
                outbound_status(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    session_id=session.session_id,
                    text=text,
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                )
            )

        try:
            result = await self.orchestrator.one_turn(
                session=session,
                user_text=user_text,
                status=status_cb,
            )
        except Exception as exc:
            logger.exception("Runtime turn failed for session=%s", session.session_id)

            await self.bus.publish(
                runtime_event(
                    event_type="runtime.turn_failed",
                    channel=message.channel,
                    chat_id=message.chat_id,
                    session_id=session.session_id,
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                    payload={"error": str(exc)},
                )
            )

            await self.bus.publish(
                outbound_error(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    session_id=session.session_id,
                    text=f"Errore runtime: {exc}",
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                )
            )
            return

        await self.bus.publish(
            runtime_event(
                event_type="runtime.turn_completed",
                channel=message.channel,
                chat_id=message.chat_id,
                session_id=session.session_id,
                correlation_id=message.correlation_id,
                causation_id=message.message_id,
                payload={
                    "action": result.action,
                    "reason": result.reason,
                    "score": result.score,
                    "retrieval_hits": result.retrieval_hits,
                    "has_audio": bool(result.audio_path),
                    "route_name": result.route_name,
                    "route_action": result.route_action,
                    "route_reason": result.route_reason,
                    "route_score": result.route_score,
                    "route_candidates": result.route_candidates or [],
                },
            )
        )

        common_meta = {
            "action": result.action,
            "reason": result.reason,
            "score": result.score,
            "retrieval_hits": result.retrieval_hits,
            "route_name": result.route_name,
            "route_action": result.route_action,
            "route_reason": result.route_reason,
            "route_score": result.route_score,
            "route_candidates": result.route_candidates or [],
        }

        if result.audio_path:
            await self.bus.publish(
                outbound_audio(
                    channel=message.channel,
                    chat_id=message.chat_id,
                    session_id=session.session_id,
                    audio_path=result.audio_path,
                    caption="Audio generato",
                    correlation_id=message.correlation_id,
                    causation_id=message.message_id,
                    metadata=common_meta,
                )
            )

        await self.bus.publish(
            outbound_text(
                channel=message.channel,
                chat_id=message.chat_id,
                session_id=session.session_id,
                text=result.content,
                correlation_id=message.correlation_id,
                causation_id=message.message_id,
                metadata=common_meta,
            )
        )
