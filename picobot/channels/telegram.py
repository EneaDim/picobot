from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from picobot.bus.events import (
    OutboundMessage,
    inbound_document,
    inbound_text,
    inbound_voice_note,
)
from picobot.bus.queue import MessageBus
from picobot.channels.base import Channel

logger = logging.getLogger(__name__)

try:
    from telegram import Update
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


class TelegramChannel(Channel):
    """
    Telegram channel adapter bus-aware.

    Supporto attuale:
    - inbound text
    - inbound voice_note
    - inbound document
    - outbound text / status / error / audio

    Nota:
    gli slash command non vengono interpretati nel channel;
    vengono inoltrati come testo al runtime, così la surface resta
    quasi paritetica con la CLI.
    """

    def __init__(
        self,
        *,
        bus: MessageBus,
        token: str,
        download_dir: str | Path,
        default_session_prefix: str = "tg",
    ) -> None:
        super().__init__(name="telegram", bus=bus)
        self.token = str(token or "").strip()
        self.download_dir = Path(download_dir).expanduser().resolve()
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.default_session_prefix = str(default_session_prefix or "tg").strip() or "tg"
        self._app = None
        self._started = False

    def _session_id_for_chat(self, chat_id: int | str) -> str:
        return f"{self.default_session_prefix}-{chat_id}"

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
            "Ciao! 👋 Sono collegato al runtime di picobot. Puoi scrivermi testo libero, slash command, inviare un vocale o un PDF."
        )

    async def _on_text_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        message = update.effective_message
        chat = update.effective_chat
        user = update.effective_user

        if not message or not chat:
            return

        text = _normalize_inbound_text(message.text or "")
        if not text:
            return

        await self._publish_inbound_text(
            chat_id=chat.id,
            text=text,
            user_id=getattr(user, "id", None),
            username=getattr(user, "username", None),
        )

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

    async def handle_outbound(self, message: OutboundMessage) -> None:
        if self._app is None:
            logger.warning("Telegram outbound dropped: app not started")
            return

        chat_id = str(message.chat_id or "").strip()
        if not chat_id:
            logger.warning("Telegram outbound dropped: missing chat_id")
            return

        payload = dict(message.payload or {})
        mtype = message.message_type

        bot = self._app.bot

        try:
            if mtype in {"outbound.text", "outbound.status", "outbound.error"}:
                text = str(payload.get("text") or "").strip()
                if text:
                    await bot.send_message(chat_id=chat_id, text=text)
                return

            if mtype == "outbound.audio":
                audio_path = str(payload.get("audio_path") or "").strip()
                caption = str(payload.get("caption") or "").strip() or None
                if not audio_path:
                    return

                with open(audio_path, "rb") as f:
                    await bot.send_audio(
                        chat_id=chat_id,
                        audio=f,
                        caption=caption,
                    )
                return

        except Exception:
            logger.exception("Telegram outbound failed")
