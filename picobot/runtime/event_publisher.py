from __future__ import annotations

from picobot.agent.models import RuntimeHooks
from picobot.bus.events import InboundMessage, outbound_audio, outbound_error, outbound_status, outbound_text, runtime_event
from picobot.bus.queue import MessageBus
from picobot.session.manager import Session


class RuntimeEventPublisher:
    def __init__(self, *, bus: MessageBus) -> None:
        self.bus = bus

    async def publish_runtime_event(
        self,
        *,
        inbound: InboundMessage,
        session_id: str | None,
        event_type: str,
        payload: dict,
    ) -> None:
        await self.bus.publish(
            runtime_event(
                event_type=event_type,
                channel=inbound.channel,
                chat_id=inbound.chat_id,
                session_id=session_id,
                correlation_id=inbound.correlation_id,
                causation_id=inbound.message_id,
                payload=payload,
            )
        )

    def make_turn_hooks(self, *, inbound: InboundMessage, session_id: str) -> RuntimeHooks:
        async def _route_selected(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.turn.route_selected", payload=payload)

        async def _context_built(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.turn.context_built", payload=payload)

        async def _tool_started(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.tool.started", payload=payload)

        async def _tool_completed(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.tool.completed", payload=payload)

        async def _tool_failed(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.tool.failed", payload=payload)

        async def _retrieval_started(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.retrieval.started", payload=payload)

        async def _retrieval_completed(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.retrieval.completed", payload=payload)

        async def _memory_updated(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.memory.updated", payload=payload)

        async def _audio_generated(payload: dict) -> None:
            await self.publish_runtime_event(inbound=inbound, session_id=session_id, event_type="runtime.audio.generated", payload=payload)

        return RuntimeHooks(
            on_route_selected=_route_selected,
            on_context_built=_context_built,
            on_tool_started=_tool_started,
            on_tool_completed=_tool_completed,
            on_tool_failed=_tool_failed,
            on_retrieval_started=_retrieval_started,
            on_retrieval_completed=_retrieval_completed,
            on_memory_updated=_memory_updated,
            on_audio_generated=_audio_generated,
        )

    async def publish_turn_started(
        self,
        *,
        inbound: InboundMessage,
        session: Session,
        user_text: str,
    ) -> None:
        await self.publish_runtime_event(
            inbound=inbound,
            session_id=session.session_id,
            event_type="runtime.turn_started",
            payload={"input_type": inbound.message_type, "text_len": len(user_text)},
        )

    async def publish_turn_completed(
        self,
        *,
        inbound: InboundMessage,
        session: Session,
        result,
    ) -> None:
        await self.publish_runtime_event(
            inbound=inbound,
            session_id=session.session_id,
            event_type="runtime.turn_completed",
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
                "route_source": result.route_source,
                "provider_name": result.provider_name,
                "kb_probe_score": result.kb_probe_score,
                "kb_name": result.kb_name,
                "audit": dict(result.audit or {}),
            },
        )

    async def publish_turn_failed(
        self,
        *,
        inbound: InboundMessage,
        session: Session,
        error: Exception,
    ) -> None:
        await self.publish_runtime_event(
            inbound=inbound,
            session_id=session.session_id,
            event_type="runtime.turn_failed",
            payload={"error": str(error)},
        )

    async def publish_inbound_ignored(self, *, inbound: InboundMessage, reason: str) -> None:
        await self.publish_runtime_event(
            inbound=inbound,
            session_id=inbound.session_id,
            event_type="runtime.inbound_ignored",
            payload={"reason": reason, "message_type": inbound.message_type},
        )

    async def publish_heartbeat_snapshot(
        self,
        *,
        inbound: InboundMessage,
        runtime_started: bool,
        workspace: str,
        session_manager_name: str,
        orchestrator_name: str,
    ) -> None:
        await self.publish_runtime_event(
            inbound=inbound,
            session_id=inbound.session_id,
            event_type="runtime.heartbeat.snapshot",
            payload={
                "tick_name": str(inbound.payload.get("tick_name") or "default"),
                "runtime_started": runtime_started,
                "workspace": workspace,
                "session_manager": session_manager_name,
                "orchestrator": orchestrator_name,
            },
        )

    async def publish_status(self, *, inbound: InboundMessage, session: Session, text: str) -> None:
        await self.bus.publish(
            outbound_status(
                channel=inbound.channel,
                chat_id=inbound.chat_id,
                session_id=session.session_id,
                text=text,
                correlation_id=inbound.correlation_id,
                causation_id=inbound.message_id,
            )
        )

    async def publish_error(self, *, inbound: InboundMessage, session: Session, text: str) -> None:
        await self.bus.publish(
            outbound_error(
                channel=inbound.channel,
                chat_id=inbound.chat_id,
                session_id=session.session_id,
                text=text,
                correlation_id=inbound.correlation_id,
                causation_id=inbound.message_id,
            )
        )

    async def publish_empty_input_error(self, *, inbound: InboundMessage, session: Session) -> None:
        await self.publish_error(inbound=inbound, session=session, text="Input vuoto.")

    async def publish_turn_outputs(
        self,
        *,
        inbound: InboundMessage,
        session: Session,
        result,
    ) -> None:
        audit = dict(getattr(result, "audit", {}) or {})
        suppress_text_when_audio = bool(audit.get("suppress_text_when_audio"))
        audio_caption = str(audit.get("audio_caption") or "").strip() or None

        text = str(result.content or "").strip()
        has_audio = bool(result.audio_path)

        if text and not (has_audio and suppress_text_when_audio):
            await self.bus.publish(
                outbound_text(
                    channel=inbound.channel,
                    chat_id=inbound.chat_id,
                    session_id=session.session_id,
                    text=text,
                    correlation_id=inbound.correlation_id,
                    causation_id=inbound.message_id,
                )
            )

        if has_audio:
            await self.bus.publish(
                outbound_audio(
                    channel=inbound.channel,
                    chat_id=inbound.chat_id,
                    session_id=session.session_id,
                    audio_path=result.audio_path,
                    caption=audio_caption or (text if text and not suppress_text_when_audio else None),
                    correlation_id=inbound.correlation_id,
                    causation_id=inbound.message_id,
                )
            )
