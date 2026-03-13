from __future__ import annotations

from picobot.ui.status_formatter import debug_line_from_runtime


def _safe_preview(text: str, limit: int = 80) -> str:
    clean = " ".join((text or "").strip().split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1] + "…"


def _format_outbound(msg) -> str | None:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})

    if mtype == "outbound.status":
        text = str(payload.get("text") or "").strip()
        if text:
            return f"🟡 status    {text}"
        return None

    if mtype == "outbound.text":
        text = str(payload.get("text") or "").strip()
        if text:
            return f'💬 outbound  text="{_safe_preview(text)}"'
        return None

    if mtype == "outbound.error":
        text = str(payload.get("text") or payload.get("error") or "").strip()
        if text:
            return f'❌ outbound  error="{_safe_preview(text)}"'
        return None

    if mtype == "outbound.audio":
        audio_path = str(payload.get("audio_path") or "").strip()
        if audio_path:
            return f"🎧 outbound  audio={audio_path}"
        return "🎧 outbound  audio"

    return None


def _format_inbound(msg) -> str | None:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})
    chat_id = str(getattr(msg, "chat_id", "") or "").strip()

    if mtype == "inbound.text":
        text = str(payload.get("text") or "").strip()
        return f'📲 inbound   chat_id={chat_id} text="{_safe_preview(text)}"'

    if mtype == "inbound.telegram.voice_note":
        audio_path = str(payload.get("audio_path") or "").strip()
        return f"🎙 voice     chat_id={chat_id} audio={audio_path}"

    if mtype == "inbound.document":
        file_name = str(payload.get("file_name") or payload.get("path") or "").strip()
        return f"📄 document  chat_id={chat_id} file={file_name}"

    return None


class TelegramMirror:
    def __init__(self, *, bus, print_debug) -> None:
        self.bus = bus
        self.print_debug = print_debug
        self._unsubscribe = []

    async def start(self) -> None:
        self._unsubscribe.append(self.bus.subscribe("inbound.*", self._on_inbound))
        self._unsubscribe.append(self.bus.subscribe("runtime.*", self._on_runtime))
        self._unsubscribe.append(self.bus.subscribe("outbound.*", self._on_outbound))

    async def stop(self) -> None:
        while self._unsubscribe:
            fn = self._unsubscribe.pop()
            try:
                fn()
            except Exception:
                pass

    async def _on_inbound(self, msg) -> None:
        if str(getattr(msg, "channel", "") or "") != "telegram":
            return
        formatted = _format_inbound(msg)
        if formatted:
            self.print_debug(formatted)

    async def _on_runtime(self, msg) -> None:
        if str(getattr(msg, "channel", "") or "") != "telegram":
            return
        formatted = debug_line_from_runtime(msg)
        if formatted:
            self.print_debug(formatted)

    async def _on_outbound(self, msg) -> None:
        if str(getattr(msg, "channel", "") or "") != "telegram":
            return
        formatted = _format_outbound(msg)
        if formatted:
            self.print_debug(formatted)
