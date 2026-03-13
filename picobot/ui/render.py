from __future__ import annotations

from textwrap import indent


def banner_lines() -> list[str]:
    return [
        "🤖 Picobot CLI",
        "✨ Tools, workflows, and LLM orchestration in one terminal.",
        "Type /help to explore commands.",
    ]


def prompt_label() -> str:
    return "❯ "


def _box(title: str, body: str) -> str:
    clean = (body or "").rstrip()
    if not clean:
        return title
    return f"{title}\n{clean}"


def assistant_block(text: str) -> str:
    return _box("🤖 Picobot", str(text or "").rstrip())


def error_block(text: str) -> str:
    return _box("❌ Error", str(text or "").rstrip())


def info_block(text: str) -> str:
    return _box("ℹ️ Info", str(text or "").rstrip())


def audio_block(text: str) -> str:
    return _box("🎧 Audio", str(text or "").rstrip())


def tool_block(text: str) -> str:
    return _box("🛠 Tool", str(text or "").rstrip())


def outbound_kind_and_text(msg) -> tuple[str, str]:
    mtype = str(getattr(msg, "message_type", "") or "")
    payload = dict(getattr(msg, "payload", {}) or {})

    if mtype == "outbound.status":
        return "status", str(payload.get("text") or "").strip()

    if mtype == "outbound.error":
        text = str(payload.get("text") or payload.get("error") or "").strip()
        return "error", text

    if mtype == "outbound.audio":
        text = str(payload.get("text") or "").strip()
        if not text:
            path = str(payload.get("audio_path") or "").strip()
            if path:
                text = f"Generated audio\nPath: {path}"
        return "audio", text

    if mtype == "outbound.tool":
        text = str(payload.get("text") or "").strip()
        return "tool", text

    if mtype == "outbound.text":
        text = str(payload.get("text") or "").strip()
        return "assistant", text

    return "unknown", ""


STATUS_EMOJI_MAP = {
    "bus": "📨",
    "turn": "📥",
    "route": "🧭",
    "thinking": "🧠",
    "retrieve": "🔎",
    "tool": "🛠",
    "tts": "🔊",
    "stt": "🎙",
    "youtube": "📺",
    "python": "🐍",
    "fetch": "🌐",
    "audio": "🎧",
    "memory": "🧠",
    "done": "✅",
    "error": "❌",
    "end": "🏁",
}
