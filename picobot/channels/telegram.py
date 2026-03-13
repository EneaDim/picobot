from __future__ import annotations

import logging
import time
from pathlib import Path
from uuid import uuid4

from picobot.bus.events import (
    OutboundMessage,
    RuntimeEvent,
    inbound_document,
    inbound_text,
    inbound_voice_note,
)
from picobot.bus.queue import MessageBus
from picobot.channels.base import Channel
from picobot.ui.commands import handle_command
from picobot.ui.status_formatter import (
    debug_line_from_runtime,
    short_status_from_runtime,
    telegram_status_text,
    telegram_trace_footer,
)

logger = logging.getLogger(__name__)

try:
    from telegram import BotCommand, BotCommandScopeAllPrivateChats, Update
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
    TELEGRAM_AVAILABLE = True
except Exception:
    Update = object  # type: ignore[assignment]
    ContextTypes = object  # type: ignore[assignment]
    Application = object  # type: ignore[assignment]
    CommandHandler = object  # type: ignore[assignment]
    MessageHandler = object  # type: ignore[assignment]
    filters = object  # type: ignore[assignment]
    TELEGRAM_AVAILABLE = False


def _normalize_inbound_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def _normalize_telegram_command(text: str) -> str:
    raw = _normalize_inbound_text(text)
    if not raw.startswith("/"):
        return raw

    parts = raw.split(" ", 1)
    head = parts[0]
    tail = parts[1] if len(parts) > 1 else ""

    if "@" in head:
        head = head.split("@", 1)[0]

    return f"{head} {tail}".strip()


class TelegramChannel(Channel):
    """
    Telegram channel adapter bus-aware.

    Telegram UX differs from CLI:
    - one short progress message is edited while a turn runs
    - final answer is sent as a normal message
    - optional short debug trace can be appended when enabled
    """

    def __init__(
        self,
        *,
        bus: MessageBus,
        token: str,
        download_dir: str | Path,
        default_session_prefix: str = "tg",
        cfg=None,
    ) -> None:
        super().__init__(name="telegram", bus=bus)
        self.token = str(token or "").strip()
        self.download_dir = Path(download_dir).expanduser().resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.default_session_prefix = str(default_session_prefix or "tg").strip() or "tg"
        self._app = None
        self._started = False
        self.cfg = cfg
        self.channel_manager = None
        self.workspace = self.download_dir.parent
        self.orchestrator = None

        telegram_cfg = getattr(cfg, "telegram", None) if cfg is not None else None
        self._debug_trace_enabled = bool(getattr(telegram_cfg, "debug_terminal", False))

        self._status_state: dict[str, dict] = {}

    def _session_id_for_chat(self, chat_id: int | str) -> str:
        return f"{self.default_session_prefix}-{chat_id}"

    def bind_runtime_context(self, *, channel_manager=None, orchestrator=None, workspace=None) -> None:
        self.channel_manager = channel_manager
        if orchestrator is not None:
            self.orchestrator = orchestrator
        if workspace is not None:
            self.workspace = Path(workspace).expanduser().resolve()

    def bind_channel_manager(self, channel_manager) -> None:
        self.bind_runtime_context(channel_manager=channel_manager)


    def _chat_dir(self, chat_id: int | str) -> Path:
        path = self.download_dir / str(chat_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    async def start(self) -> None:
        if self._started:
            return

        if not TELEGRAM_AVAILABLE:
            raise RuntimeError(
                "python-telegram-bot non disponibile. Installa la dipendenza Telegram."
            )

        if not self.token:
            raise RuntimeError("Telegram token mancante.")

        app = Application.builder().token(self.token).build()
        app.add_handler(CommandHandler("start", self._on_start))
        app.add_handler(MessageHandler(filters.TEXT, self._on_text_message))
        app.add_handler(MessageHandler(filters.VOICE, self._on_voice_message))
        app.add_handler(MessageHandler(filters.Document.ALL, self._on_document_message))

        await app.initialize()

        commands = [
            BotCommand("help", "Show available commands"),
            BotCommand("status", "Show runtime status"),
            BotCommand("tools", "List tools"),
            BotCommand("mem", "Show or clean memory"),
            BotCommand("kb", "Knowledge base commands"),
            BotCommand("news", "Summarize news"),
            BotCommand("yt", "Summarize a YouTube video"),
            BotCommand("python", "Run Python in sandbox"),
            BotCommand("tts", "Text to speech"),
            BotCommand("stt", "Speech to text"),
            BotCommand("fetch", "Fetch a webpage"),
            BotCommand("file", "Read a file"),
            BotCommand("podcast", "Generate a podcast"),
        ]

        await app.bot.set_my_commands(commands)
        await app.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
        await app.start()
        await app.updater.start_polling()

        self._app = app
        self._started = True
        logger.info("TelegramChannel started")

    async def stop(self) -> None:
        if not self._started or self._app is None:
            return

        try:
            if self._app.updater:
                await self._app.updater.stop()
        finally:
            await self._app.stop()
            await self._app.shutdown()
            self._started = False
            self._app = None
            logger.info("TelegramChannel stopped")

    async def _publish_inbound_text(
        self,
        *,
        chat_id: int | str,
        text: str,
        user_id: int | str | None = None,
        username: str | None = None,
    ) -> str:
        session_id = self._session_id_for_chat(chat_id)

        msg = inbound_text(
            channel=self.name,
            chat_id=str(chat_id),
            session_id=session_id,
            text=_normalize_inbound_text(text),
            metadata={
                "telegram_user_id": str(user_id) if user_id is not None else "",
                "telegram_username": username or "",
            },
        )
        await self.bus.publish(msg)
        return msg.correlation_id

    async def _on_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_message:
            return

        await update.effective_message.reply_text(
            "👋 Hi! I’m connected to the Picobot runtime.\n\n"
            "You can send free text, slash commands, voice notes, or documents."
        )

    async def _on_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not message or not chat:
            return

        text = _normalize_telegram_command(message.text or "")
        if not text:
            return

        # Show immediate visible status, even before runtime starts.
        local_correlation_id = uuid4().hex
        await self._ensure_status_message(
            chat_id=str(chat.id),
            correlation_id=local_correlation_id,
            text="📨 Received…",
        )

        result = handle_command(
            text,
            cfg=self.cfg,
            workspace=Path(self.workspace),
            session_id=self._session_id_for_chat(chat.id),
            orchestrator=self.orchestrator,
        )

        if getattr(result, "handled", False):
            bus_text = str(getattr(result, "bus_text", "") or "").strip()
            direct_text = str(getattr(result, "text", "") or "").strip()

            if bus_text:
                # Rebind the temporary status bucket to the runtime correlation id later.
                runtime_corr = await self._publish_inbound_text(
                    chat_id=chat.id,
                    text=bus_text,
                    user_id=getattr(user, "id", None),
                    username=getattr(user, "username", None),
                )
                if local_correlation_id in self._status_state:
                    self._status_state[runtime_corr] = self._status_state.pop(local_correlation_id)
                return

            await self._finalize_status_message(
                chat_id=str(chat.id),
                correlation_id=local_correlation_id,
                success=True,
            )
            if direct_text:
                await message.reply_text(direct_text)
            return

        runtime_corr = await self._publish_inbound_text(
            chat_id=chat.id,
            text=text,
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
        )
        if local_correlation_id in self._status_state:
            self._status_state[runtime_corr] = self._status_state.pop(local_correlation_id)

    async def _on_voice_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not message or not chat or not message.voice:
            return

        voice = message.voice
        tg_file = await context.bot.get_file(voice.file_id)

        chat_dir = self._chat_dir(chat.id)
        file_path = chat_dir / f"voice_{uuid4().hex}.ogg"
        await tg_file.download_to_drive(custom_path=str(file_path))

        msg = inbound_voice_note(
            channel=self.name,
            chat_id=str(chat.id),
            session_id=self._session_id_for_chat(chat.id),
            audio_path=str(file_path),
            metadata={
                "telegram_user_id": str(getattr(user, "id", "") or ""),
                "telegram_username": getattr(user, "username", "") or "",
                "telegram_file_id": voice.file_id,
                "telegram_duration_sec": getattr(voice, "duration", 0) or 0,
            },
        )
        await self.bus.publish(msg)

    async def _on_document_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not message or not chat or not message.document:
            return

        document = message.document
        tg_file = await context.bot.get_file(document.file_id)

        suffix = ""
        if document.file_name and "." in document.file_name:
            suffix = "." + document.file_name.split(".")[-1]

        chat_dir = self._chat_dir(chat.id)
        file_path = chat_dir / f"document_{uuid4().hex}{suffix}"
        await tg_file.download_to_drive(custom_path=str(file_path))

        msg = inbound_document(
            channel=self.name,
            chat_id=str(chat.id),
            session_id=self._session_id_for_chat(chat.id),
            file_path=str(file_path),
            file_name=document.file_name or "",
            mime_type=document.mime_type or "",
            metadata={
                "telegram_user_id": str(getattr(user, "id", "") or ""),
                "telegram_username": getattr(user, "username", "") or "",
                "telegram_file_id": document.file_id,
            },
        )
        await self.bus.publish(msg)

    def _state_for(self, correlation_id: str, chat_id: str) -> dict:
        state = self._status_state.get(correlation_id)
        if state is None:
            state = {
                "chat_id": chat_id,
                "message_id": None,
                "last_text": "",
                "last_edit_at": 0.0,
                "trace": [],
            }
            self._status_state[correlation_id] = state
        return state

    async def _ensure_status_message(self, *, chat_id: str, correlation_id: str, text: str) -> None:
        if self._app is None:
            return

        bot = self._app.bot
        state = self._state_for(correlation_id, chat_id)
        rendered = telegram_status_text(text)

        if state["message_id"] is None:
            sent = await bot.send_message(chat_id=chat_id, text=rendered)
            state["message_id"] = sent.message_id
            state["last_text"] = rendered
            state["last_edit_at"] = time.monotonic()
            return

        if state["last_text"] == rendered:
            return

        now = time.monotonic()
        if now - float(state["last_edit_at"]) < 0.25:
            return

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state["message_id"],
                text=rendered,
            )
            state["last_text"] = rendered
            state["last_edit_at"] = now
        except Exception:
            logger.exception("Telegram status edit failed")

    async def _finalize_status_message(self, *, chat_id: str, correlation_id: str, success: bool = True) -> None:
        if self._app is None:
            return

        state = self._status_state.get(correlation_id)
        if not state or state.get("message_id") is None:
            return

        bot = self._app.bot
        final_text = "✅ Completed" if success else "❌ Failed"

        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=state["message_id"],
                text=final_text,
            )
            state["last_text"] = final_text
        except Exception:
            logger.debug("Telegram status finalize skipped", exc_info=True)

    async def handle_runtime(self, message: RuntimeEvent) -> None:
        if self._app is None:
            return

        chat_id = str(message.chat_id or "").strip()
        correlation_id = str(message.correlation_id or "").strip()
        if not chat_id or not correlation_id:
            return

        state = self._state_for(correlation_id, chat_id)

        short = short_status_from_runtime(message, channel="telegram")
        if short:
            await self._ensure_status_message(
                chat_id=chat_id,
                correlation_id=correlation_id,
                text=short,
            )

        if self._debug_trace_enabled:
            line = debug_line_from_runtime(message)
            if line:
                state["trace"].append(line)

    async def handle_outbound(self, message: OutboundMessage) -> None:
        if self._app is None:
            logger.warning("Telegram outbound dropped: app not started")
            return

        chat_id = str(message.chat_id or "").strip()
        if not chat_id:
            logger.warning("Telegram outbound dropped: missing chat_id")
            return

        correlation_id = str(message.correlation_id or "").strip()
        payload = dict(message.payload or {})
        mtype = message.message_type
        bot = self._app.bot

        try:
            if mtype == "outbound.status":
                text = str(payload.get("text") or "").strip()
                if text and correlation_id:
                    await self._ensure_status_message(
                        chat_id=chat_id,
                        correlation_id=correlation_id,
                        text=text,
                    )
                return

            if mtype == "outbound.text":
                text = str(payload.get("text") or "").strip()
                if not text:
                    return

                if self._debug_trace_enabled and correlation_id:
                    state = self._status_state.get(correlation_id, {})
                    trace = telegram_trace_footer(list(state.get("trace", []) or []))
                    if trace:
                        text = f"{text}\n\n{trace}"

                await self._finalize_status_message(chat_id=chat_id, correlation_id=correlation_id, success=True)
                await bot.send_message(chat_id=chat_id, text=text)
                if correlation_id:
                    self._status_state.pop(correlation_id, None)
                return

            if mtype == "outbound.error":
                text = str(payload.get("text") or payload.get("error") or "").strip()
                if not text:
                    return

                await self._finalize_status_message(chat_id=chat_id, correlation_id=correlation_id, success=False)
                await bot.send_message(chat_id=chat_id, text=f"❌ Error\n{text}")
                if correlation_id:
                    self._status_state.pop(correlation_id, None)
                return

            if mtype == "outbound.audio":
                audio_path = str(payload.get("audio_path") or "").strip()
                caption = str(payload.get("caption") or "").strip() or "🎧 Audio ready"
                if not audio_path:
                    return

                await self._finalize_status_message(chat_id=chat_id, correlation_id=correlation_id, success=True)
                with open(audio_path, "rb") as f:
                    await bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        caption=caption,
                    )
                if correlation_id:
                    self._status_state.pop(correlation_id, None)
                return

        except Exception:
            logger.exception("Telegram outbound failed")
