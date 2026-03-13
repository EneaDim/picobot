from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DispatchResult:
    handled: bool
    text: str = ""
    kind: str = "text"   # text | error
    stop: bool = True


def _safe_strip(text: str) -> str:
    return " ".join((text or "").strip().split())


def dispatch_shared_command(*, text: str, cfg: Any, bus: Any, channel_manager: Any = None) -> DispatchResult:
    """
    Shared command dispatcher usable from CLI, Telegram, and future channels.

    Intentionally handles only deterministic commands that should NOT go through
    the LLM/router.
    """
    raw = _safe_strip(text)

    if not raw.startswith("/"):
        return DispatchResult(handled=False, stop=False)

    # help
    if raw == "/help":
        return DispatchResult(
            handled=True,
            text=(
                "🤖 Picobot commands\n\n"
                "System:\n"
                "• /help\n"
                "• /status\n"
                "• /tools\n\n"
                "Memory:\n"
                "• /mem\n"
                "• /mem clean\n\n"
                "Tools:\n"
                "• /tts <text>\n"
                "• /stt <audio_path>\n"
                "• /yt <url>\n"
                "• /python <code>\n"
                "• /fetch <url>\n"
                "• /podcast <topic>"
            ),
        )

    # status
    if raw == "/status":
        telegram_enabled = False
        try:
            tg = getattr(cfg, "telegram", None)
            telegram_enabled = bool(getattr(tg, "enabled", False))
        except Exception:
            telegram_enabled = False

        return DispatchResult(
            handled=True,
            text=(
                "ℹ️ Runtime status\n\n"
                f"• Telegram: {'enabled' if telegram_enabled else 'disabled'}\n"
                "• Sandbox: docker\n"
                "• Providers: Ollama, Gemini"
            ),
        )

    # tools
    if raw == "/tools":
        return DispatchResult(
            handled=True,
            text=(
                "🛠 Available tools\n\n"
                "• /tts\n"
                "• /stt\n"
                "• /yt\n"
                "• /python\n"
                "• /fetch\n"
                "• /podcast"
            ),
        )

    # mem
    if raw == "/mem":
        try:
            # best-effort generic summary; keep deterministic
            return DispatchResult(
                handled=True,
                text="🧠 Memory\n\nUse /mem clean to clear the current session memory.",
            )
        except Exception as exc:
            return DispatchResult(
                handled=True,
                kind="error",
                text=f"❌ Error /mem: {exc}",
            )

    # mem clean
    if raw == "/mem clean":
        try:
            # Defensive approach: support a few possible APIs if present
            cleaned = False

            # common option 1: cfg/session_store
            if hasattr(cfg, "session_store") and hasattr(cfg.session_store, "clear"):
                cfg.session_store.clear()
                cleaned = True

            # common option 2: bus/session state
            if hasattr(bus, "clear_session_state"):
                bus.clear_session_state()
                cleaned = True

            # common option 3: channel manager / runtime store (best effort)
            if channel_manager is not None and hasattr(channel_manager, "clear_session_memory"):
                channel_manager.clear_session_memory()
                cleaned = True

            # even if no explicit backend hook exists, return deterministic success
            # because the Telegram/CLI UX should not fall back to LLM chat.
            return DispatchResult(
                handled=True,
                text=(
                    "🧠 Memory cleared\n\n"
                    "The current session memory has been reset."
                    if cleaned
                    else
                    "🧠 Memory clean requested\n\n"
                    "The command was handled, but no explicit memory backend hook was available."
                ),
            )
        except Exception as exc:
            return DispatchResult(
                handled=True,
                kind="error",
                text=f"❌ Error /mem clean: {exc}",
            )

    return DispatchResult(handled=False, stop=False)
