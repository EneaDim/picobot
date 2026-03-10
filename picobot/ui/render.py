from __future__ import annotations


def banner_lines() -> list[str]:
    return [
        "🤖 Picobot",
        "Comandi: /help   Esci: /exit",
    ]


def prompt_label() -> str:
    return "❯ "


def section_title(title: str, emoji: str = "") -> str:
    return f"{emoji} {title}".strip()


def assistant_block(text: str) -> str:
    return f"{section_title('Picobot', '🤖')}\n{text}"


def info_block(text: str) -> str:
    return f"{section_title('Info', 'ℹ️')}\n{text}"


def error_block(text: str) -> str:
    return f"{section_title('Errore', '⚠️')}\n{text}"


def audio_block(text: str) -> str:
    return f"{section_title('Audio', '🎧')}\n{text}"


def outbound_kind_and_text(message) -> tuple[str, str | None]:
    mtype = getattr(message, "message_type", "")
    payload = getattr(message, "payload", {}) or {}

    if mtype == "outbound.status":
        text = str(payload.get("text") or "").strip()
        return "status", text or None

    if mtype == "outbound.error":
        text = str(payload.get("text") or "").strip()
        return "error", text or "Errore sconosciuto."

    if mtype == "outbound.audio":
        audio_path = str(payload.get("audio_path") or "").strip()
        caption = str(payload.get("caption") or "").strip()
        if caption and audio_path:
            return "audio", f"{caption}\n{audio_path}"
        if audio_path:
            return "audio", f"Audio generato: {audio_path}"
        return "audio", caption or "Audio generato."

    if mtype == "outbound.text":
        text = str(payload.get("text") or "").strip()
        return "assistant", text or None

    return "unknown", None
