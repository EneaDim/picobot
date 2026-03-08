from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4

ChannelName = Literal["cli", "telegram", "cron", "heartbeat", "system"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_message_id() -> str:
    return uuid4().hex


@dataclass(slots=True, frozen=True)
class BusMessage:
    message_id: str
    message_type: str
    created_at: datetime
    source: str
    channel: str
    chat_id: str
    session_id: str | None
    correlation_id: str | None
    causation_id: str | None
    payload: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class InboundMessage(BusMessage):
    pass


@dataclass(slots=True, frozen=True)
class OutboundMessage(BusMessage):
    pass


@dataclass(slots=True, frozen=True)
class RuntimeEvent(BusMessage):
    pass


def make_inbound_message(
    *,
    message_type: str,
    channel: str,
    chat_id: str,
    session_id: str | None,
    payload: dict[str, Any] | None = None,
    source: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> InboundMessage:
    return InboundMessage(
        message_id=new_message_id(),
        message_type=message_type,
        created_at=utc_now(),
        source=source or channel,
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=payload or {},
        metadata=metadata or {},
    )


def inbound_text(
    *,
    channel: str,
    chat_id: str,
    session_id: str,
    text: str,
    source: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> InboundMessage:
    return make_inbound_message(
        message_type="inbound.text",
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        payload={"text": text},
        source=source,
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata=metadata,
    )


def inbound_cron_tick(
    *,
    job_name: str,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> InboundMessage:
    return make_inbound_message(
        message_type="inbound.cron_tick",
        channel="cron",
        chat_id="cron",
        session_id=session_id,
        payload={"job_name": job_name},
        source="cron",
        metadata=metadata,
    )


def inbound_heartbeat_tick(
    *,
    tick_name: str = "default",
    metadata: dict[str, Any] | None = None,
) -> InboundMessage:
    return make_inbound_message(
        message_type="inbound.heartbeat_tick",
        channel="heartbeat",
        chat_id="heartbeat",
        session_id=None,
        payload={"tick_name": tick_name},
        source="heartbeat",
        metadata=metadata,
    )


def make_outbound_message(
    *,
    message_type: str,
    channel: str,
    chat_id: str,
    session_id: str | None,
    payload: dict[str, Any] | None = None,
    source: str = "runtime",
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OutboundMessage:
    return OutboundMessage(
        message_id=new_message_id(),
        message_type=message_type,
        created_at=utc_now(),
        source=source,
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=payload or {},
        metadata=metadata or {},
    )


def outbound_status(
    *,
    channel: str,
    chat_id: str,
    session_id: str | None,
    text: str,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OutboundMessage:
    return make_outbound_message(
        message_type="outbound.status",
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        payload={"text": text},
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata=metadata,
    )


def outbound_text(
    *,
    channel: str,
    chat_id: str,
    session_id: str | None,
    text: str,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OutboundMessage:
    return make_outbound_message(
        message_type="outbound.text",
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        payload={"text": text},
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata=metadata,
    )


def outbound_error(
    *,
    channel: str,
    chat_id: str,
    session_id: str | None,
    text: str,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OutboundMessage:
    return make_outbound_message(
        message_type="outbound.error",
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        payload={"text": text},
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata=metadata,
    )


def outbound_audio(
    *,
    channel: str,
    chat_id: str,
    session_id: str | None,
    audio_path: str,
    caption: str | None = None,
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> OutboundMessage:
    payload: dict[str, Any] = {"audio_path": audio_path}
    if caption:
        payload["caption"] = caption

    return make_outbound_message(
        message_type="outbound.audio",
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        payload=payload,
        correlation_id=correlation_id,
        causation_id=causation_id,
        metadata=metadata,
    )


def runtime_event(
    *,
    event_type: str,
    channel: str,
    chat_id: str,
    session_id: str | None,
    payload: dict[str, Any] | None = None,
    source: str = "runtime",
    correlation_id: str | None = None,
    causation_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> RuntimeEvent:
    return RuntimeEvent(
        message_id=new_message_id(),
        message_type=event_type,
        created_at=utc_now(),
        source=source,
        channel=channel,
        chat_id=chat_id,
        session_id=session_id,
        correlation_id=correlation_id,
        causation_id=causation_id,
        payload=payload or {},
        metadata=metadata or {},
    )
