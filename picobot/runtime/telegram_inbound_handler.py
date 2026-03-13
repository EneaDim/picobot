from __future__ import annotations

from pathlib import Path
from typing import Any

from picobot.agent.application import Orchestrator
from picobot.bus.events import (
    BusMessage,
    InboundMessage,
    inbound_text,
)
from picobot.bus.queue import MessageBus
from picobot.runtime.event_publisher import RuntimeEventPublisher
from picobot.runtime.spoken_commands import spoken_text_to_command
from picobot.session.manager import SessionManager


class TelegramInboundHandler:
    """
    Handler runtime per inbound speciali provenienti da Telegram.

    Supporto attuale:
    - inbound.telegram.voice_note -> STT -> ripubblica inbound.text
    - inbound.telegram.document   -> PDF KB ingest best-effort
    """

    def __init__(
        self,
        *,
        bus: MessageBus,
        events: RuntimeEventPublisher,
        orchestrator: Orchestrator,
        session_manager: SessionManager,
    ) -> None:
        self.bus = bus
        self.events = events
        self.orchestrator = orchestrator
        self.sessions = session_manager

    async def handle_voice_note(self, message: BusMessage) -> None:
        if not isinstance(message, InboundMessage):
            return

        session_id = (message.session_id or "default").strip() or "default"
        session = self.sessions.get(session_id)
        audio_path = str(message.payload.get("audio_path") or "").strip()

        if not audio_path:
            await self.events.publish_error(
                inbound=message,
                session=session,
                text="Voice note ricevuta senza audio_path.",
            )
            return

        await self.events.publish_runtime_event(
            inbound=message,
            session_id=session.session_id,
            event_type="runtime.telegram.voice_note.received",
            payload={
                "audio_path": audio_path,
            },
        )

        await self.events.publish_status(
            inbound=message,
            session=session,
            text="🎙️ Trascrivo il messaggio vocale…",
        )

        try:
            result = await self.orchestrator._call_tool(
                "stt",
                {"audio_path": audio_path},
                workflow_name="telegram_voice_note",
            )
        except Exception as exc:
            await self.events.publish_runtime_event(
                inbound=message,
                session_id=session.session_id,
                event_type="runtime.telegram.voice_note.failed",
                payload={
                    "audio_path": audio_path,
                    "error": str(exc),
                },
            )
            await self.events.publish_error(
                inbound=message,
                session=session,
                text=f"Errore STT: {exc}",
            )
            return

        if not isinstance(result, dict) or not result.get("ok"):
            err = ""
            if isinstance(result, dict):
                err = str(result.get("error") or "stt failed")
            else:
                err = "invalid stt result"
            await self.events.publish_runtime_event(
                inbound=message,
                session_id=session.session_id,
                event_type="runtime.telegram.voice_note.failed",
                payload={
                    "audio_path": audio_path,
                    "error": err,
                },
            )
            await self.events.publish_error(
                inbound=message,
                session=session,
                text=f"Errore STT: {err}",
            )
            return

        data = result.get("data") or {}
        transcript = (
            str(data.get("text") or "").strip()
            or str(data.get("transcript") or "").strip()
        )

        if not transcript:
            await self.events.publish_error(
                inbound=message,
                session=session,
                text="Trascrizione vuota.",
            )
            return

        await self.events.publish_runtime_event(
            inbound=message,
            session_id=session.session_id,
            event_type="runtime.telegram.voice_note.transcribed",
            payload={
                "audio_path": audio_path,
                "transcript_len": len(transcript),
            },
        )

        spoken_cmd = spoken_text_to_command(transcript)
        final_text = spoken_cmd or transcript

        await self.events.publish_runtime_event(
            inbound=message,
            session_id=session.session_id,
            event_type="runtime.telegram.voice_note.normalized",
            payload={
                "audio_path": audio_path,
                "transcript": transcript,
                "normalized_text": final_text,
                "is_command": bool(spoken_cmd),
            },
        )

        await self.bus.publish(
            inbound_text(
                channel=message.channel,
                chat_id=str(message.chat_id),
                session_id=session.session_id,
                text=final_text,
                correlation_id=message.correlation_id,
                causation_id=message.message_id,
                metadata={
                    **dict(message.metadata or {}),
                    "origin": "telegram_voice_note",
                    "audio_path": audio_path,
                    "voice_transcript": transcript,
                    "voice_normalized_command": spoken_cmd or "",
                },
            )
        )

    async def handle_document(self, message: BusMessage) -> None:
        if not isinstance(message, InboundMessage):
            return

        session_id = (message.session_id or "default").strip() or "default"
        session = self.sessions.get(session_id)

        file_path = str(message.payload.get("file_path") or "").strip()
        file_name = str(message.payload.get("file_name") or "").strip()
        mime_type = str(message.payload.get("mime_type") or "").strip()

        if not file_path:
            await self.events.publish_error(
                inbound=message,
                session=session,
                text="Documento ricevuto senza file_path.",
            )
            return

        await self.events.publish_runtime_event(
            inbound=message,
            session_id=session.session_id,
            event_type="runtime.telegram.document.received",
            payload={
                "file_path": file_path,
                "file_name": file_name,
                "mime_type": mime_type,
            },
        )

        lower_name = file_name.lower()
        is_pdf = mime_type == "application/pdf" or lower_name.endswith(".pdf") or file_path.lower().endswith(".pdf")

        if not is_pdf:
            await self.events.publish_status(
                inbound=message,
                session=session,
                text="📎 Documento ricevuto. Per ora l’ingest automatico via bus supporta solo PDF.",
            )
            return

        await self.events.publish_status(
            inbound=message,
            session=session,
            text="📄 PDF ricevuto. Avvio ingest nella knowledge base…",
        )

        kb_name = str(session.get_state().get("kb_name") or self.orchestrator.cfg.default_kb_name or "default").strip()

        last_error = "kb ingest failed"
        result: dict[str, Any] | None = None

        try:
            maybe = await self.orchestrator._call_tool(
                "kb_ingest_pdf",
                {
                    "file_path": file_path,
                    "kb_name": kb_name,
                },
                workflow_name="telegram_document_ingest",
            )
        except Exception as exc:
            last_error = str(exc)
        else:
            if isinstance(maybe, dict) and maybe.get("ok"):
                result = maybe
            elif isinstance(maybe, dict):
                last_error = str(maybe.get("error") or last_error)
            else:
                last_error = "invalid kb_ingest_pdf result"

        if not result:
            await self.events.publish_runtime_event(
                inbound=message,
                session_id=session.session_id,
                event_type="runtime.telegram.document.failed",
                payload={
                    "file_path": file_path,
                    "file_name": file_name,
                    "error": last_error,
                },
            )
            await self.events.publish_error(
                inbound=message,
                session=session,
                text=f"Ingest PDF fallito: {last_error}",
            )
            return

        await self.events.publish_runtime_event(
            inbound=message,
            session_id=session.session_id,
            event_type="runtime.telegram.document.ingested",
            payload={
                "file_path": file_path,
                "file_name": file_name,
                "kb_name": kb_name,
            },
        )

        await self.events.publish_status(
            inbound=message,
            session=session,
            text=f"✅ PDF ingestito nella KB '{kb_name}'.",
        )
