from __future__ import annotations

from pathlib import Path


def banner_lines() -> list[str]:
    return [
        "Picobot CLI",
        "Digita /help per i comandi disponibili.",
    ]


def prompt_label() -> str:
    return "❯ "


def info_block(text: str) -> str:
    body = (text or "").strip()
    return f"ℹ️ Info\n{body}" if body else "ℹ️ Info"


def assistant_block(text: str) -> str:
    body = (text or "").strip()
    return f"🤖 Picobot\n{body}" if body else "🤖 Picobot"


def error_block(text: str) -> str:
    body = (text or "").strip()
    return f"⚠️ Errore\n{body}" if body else "⚠️ Errore"


def audio_block(text: str) -> str:
    body = (text or "").strip()
    return f"🎧 Audio\n{body}" if body else "🎧 Audio"


def _format_audio_payload(payload: dict) -> str:
    audio_path = str(payload.get("audio_path") or "").strip()
    caption = str(payload.get("caption") or "").strip()
    backend = str(payload.get("backend") or "").strip()

    lines: list[str] = []
    if caption:
        lines.append(caption)
    if audio_path:
        lines.append(f"Path: {audio_path}")
    if backend:
        lines.append(f"Backend: {backend}")

    if not lines and payload:
        for k, v in payload.items():
            lines.append(f"{k}: {v}")

    return "\n".join(lines).strip()


def outbound_kind_and_text(msg) -> tuple[str, str]:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})

    if mtype == "outbound.status":
        return "status", str(payload.get("text") or "").strip()

    if mtype == "outbound.error":
        return "error", str(payload.get("text") or "").strip()

    if mtype == "outbound.text":
        return "assistant", str(payload.get("text") or "").strip()

    if mtype == "outbound.audio":
        return "audio", _format_audio_payload(payload)

    return "unknown", ""
