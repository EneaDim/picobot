from __future__ import annotations

# Telegram channel con supporto:
# - testo
# - PDF ingest
# - voice/audio -> STT tool -> orchestrator -> opzionale TTS tool
#
# Principio architetturale:
# - STT e TTS restano tool reali
# - Telegram non "fa magia"
# - il canale coordina la pipeline, ma usa il registry tool dell'orchestrator
#
# Flusso voice:
# 1. scarica audio locale
# 2. esegue tool "stt"
# 3. opzionalmente mostra transcript
# 4. passa transcript all'orchestrator
# 5. restituisce testo
# 6. opzionalmente esegue tool "tts" sulla risposta e invia audio
import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from telegram import Update
    from telegram.constants import ChatAction
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        MessageHandler,
        filters,
    )
except Exception:  # pragma: no cover
    Update = Any  # type: ignore
    ChatAction = Any  # type: ignore
    Application = None  # type: ignore
    CommandHandler = Any  # type: ignore
    ContextTypes = Any  # type: ignore
    MessageHandler = Any  # type: ignore
    filters = None  # type: ignore

from picobot.agent.orchestrator import Orchestrator
from picobot.config.schema import Config
from picobot.retrieval.ingest import ingest_kb
from picobot.retrieval.store import copy_source_file, ensure_kb_dirs
from picobot.session.manager import SessionManager, sanitize_session_id
from picobot.ui import handle_command

# -----------------------------------------------------------------------------
# Persistence helpers
# -----------------------------------------------------------------------------

@dataclass
class TelegramSessionMap:
    """
    Mappa chat_id -> session_id persistita su JSON.
    """
    path: Path

    def load(self) -> dict[str, str]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
        except Exception:
            pass
        return {}

    def save(self, data: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get(self, chat_id: str) -> str:
        mapping = self.load()
        return mapping.get(chat_id, f"tg-{chat_id}")

    def set(self, chat_id: str, session_id: str) -> str:
        sid = sanitize_session_id(session_id)
        mapping = self.load()
        mapping[chat_id] = sid
        self.save(mapping)
        return sid


@dataclass
class TelegramDedupMap:
    """
    Mappa per evitare ingest multipli dello stesso PDF.
    """
    path: Path

    def load(self) -> dict[str, dict[str, Any]]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            pass
        return {}

    def save(self, data: dict[str, dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def has(self, chat_id: str, digest: str) -> bool:
        data = self.load()
        return bool(data.get(chat_id, {}).get(digest))

    def put(self, chat_id: str, digest: str, meta: dict[str, Any]) -> None:
        data = self.load()
        data.setdefault(chat_id, {})[digest] = meta
        self.save(data)


# -----------------------------------------------------------------------------
# Utility
# -----------------------------------------------------------------------------

def _sha256_file(path: Path) -> str:
    """
    Hash del file per dedup PDF.
    """
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _maybe_bool(value: Any, default: bool = False) -> bool:
    """
    Converte in bool con fallback robusto.
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        low = value.strip().lower()
        if low in {"1", "true", "yes", "y", "on"}:
            return True
        if low in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


class TelegramChannel:
    """
    Canale Telegram principale.
    """

    def __init__(self, cfg: Config, sm: SessionManager, orch: Orchestrator, build_app: bool = True) -> None:
        self.cfg = cfg
        self.sm = sm
        self.orch = orch

        self.workspace = Path(cfg.workspace).expanduser().resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

        self.session_map = TelegramSessionMap(
            self.workspace / "channels" / "telegram" / "session_map.json"
        )
        self.dedup_map = TelegramDedupMap(
            self.workspace / "channels" / "telegram" / "pdf_dedup.json"
        )

        base_inbox = self.workspace / "channels" / "telegram" / "inbox"
        base_inbox.mkdir(parents=True, exist_ok=True)
        self.inbox_dir = base_inbox

        self.audio_dir = self.workspace / "channels" / "telegram" / "audio"
        self.audio_dir.mkdir(parents=True, exist_ok=True)

        if not cfg.telegram.bot_token:
            raise ValueError("telegram.bot_token is empty")

        self.app = None
        if build_app:
            if Application is None or filters is None:
                raise ImportError(
                    "python-telegram-bot non installato. Installa: pip install python-telegram-bot"
                )

            self.app = Application.builder().token(cfg.telegram.bot_token).build()
            self._register_handlers()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _register_handlers(self) -> None:
        """
        Registra gli handler Telegram.
        """
        assert self.app is not None

        self.app.add_handler(CommandHandler("start", self._cmd_start))
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("session", self._cmd_session))

        # Slash commands generici.
        self.app.add_handler(MessageHandler(filters.COMMAND, self._on_command), group=1)

        # PDF.
        self.app.add_handler(
            MessageHandler(filters.Document.PDF, self._on_pdf_document),
            group=2,
        )

        # Voice notes e audio files.
        self.app.add_handler(
            MessageHandler(filters.VOICE | filters.AUDIO, self._on_voice_or_audio),
            group=2,
        )

        # Testo normale.
        self.app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text),
            group=3,
        )

    async def _set_my_commands(self) -> None:
        """
        Suggerimenti slash command nel client Telegram.
        """
        if self.app is None:
            return

        cmds = [
            ("help", "Mostra aiuto"),
            ("session", "Mostra o cambia sessione"),
            ("new", "Crea nuova sessione"),
            ("kb", "Gestisci KB"),
            ("route", "Debug router"),
        ]

        try:
            bot = self.app.bot
            await bot.set_my_commands(cmds)
        except Exception:
            return

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _telegram_cfg_bool(self, name: str, default: bool = False) -> bool:
        """
        Legge un flag bool dal blocco telegram, supportando anche extra fields.
        """
        tg = getattr(self.cfg, "telegram", None)
        if tg is None:
            return default
        return _maybe_bool(getattr(tg, name, default), default=default)

    def _stt_enabled(self) -> bool:
        """
        Flag effettivo per pipeline voice->text.
        """
        return (
            self._telegram_cfg_bool("stt_auto", default=True)
            or self._telegram_cfg_bool("voice_stt_enabled", default=False)
        )

    def _tts_auto_reply_enabled(self) -> bool:
        """
        Opzione facoltativa per rispondere anche con audio sintetizzato.
        """
        return self._telegram_cfg_bool("tts_auto_reply", default=False)

    def _echo_transcript_enabled(self) -> bool:
        """
        Se attivo, invia anche il transcript in chat.
        """
        return (
            self._telegram_cfg_bool("send_transcript_flag", default=False)
            or self._telegram_cfg_bool("echo_transcript", default=False)
        )

    def _max_voice_seconds(self) -> int:
        """
        Durata massima accettata per note vocali/audio.
        """
        try:
            return int(getattr(self.cfg.telegram, "max_voice_seconds", 240) or 240)
        except Exception:
            return 240

    # ------------------------------------------------------------------
    # Small helpers
    # ------------------------------------------------------------------

    def _kb_name_for_chat(self, chat_id: str) -> str:
        """
        Namespace KB per chat Telegram.
        """
        if bool(getattr(self.cfg.telegram, "kb_per_chat", True)):
            return f"kb_{sanitize_session_id(chat_id)}"
        return sanitize_session_id(self.cfg.default_kb_name or "default")

    def _session_for_chat(self, chat_id: str):
        """
        Sessione corrente della chat.
        """
        sid = self.session_map.get(chat_id)
        return self.sm.get(sid)

    async def _typing(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Invio stato "typing".
        """
        try:
            if update.effective_chat:
                await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except Exception:
            pass

    async def _record_voice(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Invio stato "record voice" / upload audio dove disponibile.
        """
        try:
            if update.effective_chat:
                await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.RECORD_VOICE)
        except Exception:
            pass

    async def _status_message(self, msg, text: str):
        """
        Messaggio temporaneo di stato.
        """
        try:
            return await msg.reply_text(text)
        except Exception:
            return None

    async def _status_edit(self, status_msg, text: str) -> None:
        """
        Aggiorna il messaggio di stato.
        """
        if not status_msg:
            return
        try:
            await status_msg.edit_text(text)
        except Exception:
            pass

    async def _safe_reply(self, msg, text: str) -> None:
        """
        Reply robusto.
        """
        try:
            await msg.reply_text(text)
        except Exception:
            pass

    async def _safe_reply_audio(self, msg, file_path: Path, caption: str = "") -> None:
        """
        Invia un file audio. Se Telegram non lo accetta come audio, fallback a document.
        """
        try:
            if file_path.suffix.lower() in {".mp3", ".wav", ".m4a"}:
                with file_path.open("rb") as f:
                    await msg.reply_audio(audio=f, caption=caption or None)
                return
        except Exception:
            pass

        try:
            with file_path.open("rb") as f:
                await msg.reply_document(document=f, filename=file_path.name, caption=caption or None)
        except Exception:
            pass

    async def _run_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """
        Esegue un tool dal registry dell'orchestrator.

        Manteniamo STT/TTS come tool veri, non funzioni speciali del canale.
        """
        resolved = self.orch.tools.resolve_name(tool_name)
        tool = self.orch.tools.get(resolved)
        model = tool.validate(args or {})
        return await tool.handler(model)

    def _ensure_chat_session_state(self, chat_id: str):
        """
        Garantisce che la sessione Telegram abbia una KB assegnata.
        """
        session = self._session_for_chat(chat_id)
        if not session.get_state().get("kb_name"):
            kb_name = self._kb_name_for_chat(chat_id)
            ensure_kb_dirs(self.workspace, kb_name)
            session.set_state({"kb_name": kb_name, "kb_enabled": True})
        return session

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Onboarding iniziale.
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return

        session = self._session_for_chat(str(chat.id))
        kb_name = self._kb_name_for_chat(str(chat.id))

        ensure_kb_dirs(self.workspace, kb_name)
        session.set_state({"kb_name": kb_name, "kb_enabled": True})

        text = (
            "👋 Ciao, sono Picobot.\n\n"
            "Cosa puoi fare qui:\n"
            "• chattare normalmente\n"
            "• caricare PDF nella KB di questa chat\n"
            "• mandare note vocali se STT è attivo\n"
            "• usare comandi come /help, /session, /kb, /route\n\n"
            f"Sessione attuale: {session.session_id}\n"
            f"KB attiva: {kb_name}"
        )
        await self._safe_reply(msg, text)

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Help rapido.
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return

        session = self._session_for_chat(str(chat.id))
        cmd = handle_command(
            "/help",
            session=session,
            session_manager=self.sm,
            cfg=self.cfg,
            workspace=self.workspace,
        )
        extra = (
            "\n\nVoice:\n"
            "• invia una nota vocale per trascriverla\n"
            "• se tts_auto_reply è attivo, posso rispondere anche con audio"
        )
        await self._safe_reply(msg, cmd.reply + extra)

    async def _cmd_session(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Session info / set dedicato.
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return

        raw = msg.text or "/session"
        session = self._session_for_chat(str(chat.id))

        cmd = handle_command(
            raw,
            session=session,
            session_manager=self.sm,
            cfg=self.cfg,
            workspace=self.workspace,
        )

        if cmd.new_session_id:
            self.session_map.set(str(chat.id), cmd.new_session_id)

        await self._safe_reply(msg, cmd.reply)

    # ------------------------------------------------------------------
    # Generic slash commands
    # ------------------------------------------------------------------

    async def _on_command(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Qualsiasi slash command non gestito da un handler dedicato
        passa qui e usa il command layer condiviso.
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return

        raw = (msg.text or "").strip()
        if not raw:
            return

        if raw.split()[0].lower() in {"/start", "/help", "/session"}:
            return

        session = self._session_for_chat(str(chat.id))

        cmd = handle_command(
            raw,
            session=session,
            session_manager=self.sm,
            cfg=self.cfg,
            workspace=self.workspace,
        )

        if cmd.new_session_id:
            self.session_map.set(str(chat.id), cmd.new_session_id)

        if cmd.handled:
            await self._safe_reply(msg, cmd.reply)
            return

        await self._safe_reply(msg, "Comando non riconosciuto. Usa /help.")

    # ------------------------------------------------------------------
    # Text chat
    # ------------------------------------------------------------------

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Messaggio testuale normale -> orchestrator.
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return

        text = (msg.text or "").strip()
        if not text:
            return

        session = self._ensure_chat_session_state(str(chat.id))

        await self._typing(update, ctx)
        status_msg = await self._status_message(msg, "🧭 Sto capendo la richiesta…")

        async def status_cb(text: str) -> None:
            await self._status_edit(status_msg, text)

        try:
            result = await self.orch.one_turn(
                session=session,
                user_text=text,
                status=status_cb,
            )
        except Exception as e:
            await self._status_edit(status_msg, "⚠️ Errore interno")
            await self._safe_reply(msg, f"Errore interno: {e}")
            return

        await self._status_edit(status_msg, "✅ Fatto")
        await self._safe_reply(msg, result.content)

        if result.audio_path:
            try:
                path = Path(result.audio_path)
                if path.exists() and path.is_file():
                    await self._safe_reply_audio(msg, path)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # PDF ingest
    # ------------------------------------------------------------------

    async def _on_pdf_document(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Upload PDF -> inbox -> KB source -> rebuild ingest.
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat or not msg.document:
            return

        doc = msg.document
        chat_id = str(chat.id)

        kb_name = self._kb_name_for_chat(chat_id)
        ensure_kb_dirs(self.workspace, kb_name)

        session = self._session_for_chat(chat_id)
        session.set_state({"kb_name": kb_name, "kb_enabled": True})

        await self._typing(update, ctx)
        status_msg = await self._status_message(msg, "📥 Ricevuto PDF, lo scarico…")

        safe_name = sanitize_session_id(Path(doc.file_name or "upload.pdf").stem) + ".pdf"
        local_path = self.inbox_dir / f"{chat_id}_{safe_name}"

        try:
            tg_file = await ctx.bot.get_file(doc.file_id)
            await tg_file.download_to_drive(custom_path=str(local_path))
        except Exception as e:
            await self._status_edit(status_msg, "⚠️ Download fallito")
            await self._safe_reply(msg, f"Download PDF fallito: {e}")
            return

        digest = _sha256_file(local_path)
        if self.dedup_map.has(chat_id, digest):
            await self._status_edit(status_msg, "ℹ️ PDF già presente")
            await self._safe_reply(
                msg,
                f"Questo PDF risulta già ingestato per la chat.\nKB: {kb_name}",
            )
            return

        await self._status_edit(status_msg, "🧱 Copio e indicizzo nella knowledge base…")

        try:
            copied = copy_source_file(self.workspace, kb_name, local_path)
            result = ingest_kb(self.workspace, kb_name)
        except Exception as e:
            await self._status_edit(status_msg, "⚠️ Ingest fallito")
            await self._safe_reply(msg, f"Ingest PDF fallito: {e}")
            return

        self.dedup_map.put(
            chat_id,
            digest,
            {
                "filename": safe_name,
                "local_path": str(local_path),
                "copied_path": str(copied),
                "kb_name": kb_name,
                "chunk_files": result.chunk_files,
                "indexed_points": result.indexed_points,
            },
        )

        await self._status_edit(status_msg, "✅ PDF indicizzato")
        await self._safe_reply(
            msg,
            (
                f"✅ PDF ingest completato.\n"
                f"KB: {kb_name}\n"
                f"File: {safe_name}\n"
                f"Chunk: {result.chunk_files}\n"
                f"Punti indicizzati: {result.indexed_points}"
            ),
        )

    # ------------------------------------------------------------------
    # Voice / audio pipeline
    # ------------------------------------------------------------------

    async def _download_telegram_audio(self, msg, ctx: ContextTypes.DEFAULT_TYPE, target_path: Path) -> None:
        """
        Scarica voice note o audio file Telegram su disco.
        """
        if msg.voice:
            tg_file = await ctx.bot.get_file(msg.voice.file_id)
            await tg_file.download_to_drive(custom_path=str(target_path))
            return

        if msg.audio:
            tg_file = await ctx.bot.get_file(msg.audio.file_id)
            await tg_file.download_to_drive(custom_path=str(target_path))
            return

        raise RuntimeError("no downloadable audio payload found")

    def _audio_duration_seconds(self, msg) -> int:
        """
        Durata audio/voice in secondi, se disponibile.
        """
        if getattr(msg, "voice", None) and getattr(msg.voice, "duration", None) is not None:
            return int(msg.voice.duration or 0)
        if getattr(msg, "audio", None) and getattr(msg.audio, "duration", None) is not None:
            return int(msg.audio.duration or 0)
        return 0

    def _audio_suffix(self, msg) -> str:
        """
        Estensione di file coerente con il payload Telegram.
        """
        if getattr(msg, "voice", None):
            return ".ogg"

        if getattr(msg, "audio", None):
            filename = str(getattr(msg.audio, "file_name", "") or "").strip()
            suffix = Path(filename).suffix.lower()
            if suffix:
                return suffix

        return ".bin"

    def _audio_basename(self, msg, chat_id: str) -> str:
        """
        Nome base file per salvataggio locale.
        """
        if getattr(msg, "audio", None):
            filename = str(getattr(msg.audio, "file_name", "") or "").strip()
            if filename:
                return sanitize_session_id(Path(filename).stem)

        return f"{chat_id}_{getattr(msg, 'message_id', 'audio')}"

    async def _on_voice_or_audio(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        """
        Pipeline:
        Telegram voice/audio -> STT tool -> orchestrator -> opzionale TTS tool
        """
        msg = update.effective_message
        chat = update.effective_chat
        if not msg or not chat:
            return

        if not self._stt_enabled():
            await self._safe_reply(
                msg,
                "🎙️ Ho ricevuto l’audio, ma STT non è attivo nella configurazione.",
            )
            return

        duration_s = self._audio_duration_seconds(msg)
        max_voice = self._max_voice_seconds()

        if duration_s > 0 and duration_s > max_voice:
            await self._safe_reply(
                msg,
                f"🎙️ Audio troppo lungo: {duration_s}s. Limite configurato: {max_voice}s.",
            )
            return

        session = self._ensure_chat_session_state(str(chat.id))

        suffix = self._audio_suffix(msg)
        base = self._audio_basename(msg, str(chat.id))
        local_audio = self.audio_dir / f"{base}{suffix}"

        await self._typing(update, ctx)
        status_msg = await self._status_message(msg, "🎙️ Ricevuto audio, lo scarico…")

        try:
            await self._download_telegram_audio(msg, ctx, local_audio)
        except Exception as e:
            await self._status_edit(status_msg, "⚠️ Download audio fallito")
            await self._safe_reply(msg, f"Download audio fallito: {e}")
            return

        await self._status_edit(status_msg, "📝 Trascrivo l’audio…")

        try:
            stt_result = await self._run_tool(
                "stt",
                {
                    "audio_path": str(local_audio),
                    "lang": "auto",
                },
            )
        except Exception as e:
            await self._status_edit(status_msg, "⚠️ Errore STT")
            await self._safe_reply(msg, f"Errore STT: {e}")
            return

        if not stt_result.get("ok"):
            err = str(stt_result.get("error") or "stt failed")
            await self._status_edit(status_msg, "⚠️ Trascrizione fallita")
            await self._safe_reply(msg, f"Trascrizione fallita: {err}")
            return

        stt_data = stt_result.get("data") or {}
        transcript = str(stt_data.get("text") or "").strip()
        transcript_lang = str(stt_data.get("language") or "auto").strip() or "auto"

        if not transcript:
            await self._status_edit(status_msg, "⚠️ Transcript vuoto")
            await self._safe_reply(msg, "Non sono riuscito a estrarre testo dall’audio.")
            return

        if self._echo_transcript_enabled():
            await self._safe_reply(
                msg,
                f"📝 Transcript ({transcript_lang}):\n{transcript}",
            )

        await self._status_edit(status_msg, "🧭 Uso il transcript per preparare la risposta…")

        async def status_cb(text: str) -> None:
            await self._status_edit(status_msg, text)

        try:
            turn = await self.orch.one_turn(
                session=session,
                user_text=transcript,
                status=status_cb,
            )
        except Exception as e:
            await self._status_edit(status_msg, "⚠️ Errore interno")
            await self._safe_reply(msg, f"Errore interno: {e}")
            return

        await self._status_edit(status_msg, "✅ Fatto")
        await self._safe_reply(msg, turn.content)

        # Se il workflow ha già prodotto un audio (es. podcast), lo inviamo.
        if turn.audio_path:
            try:
                path = Path(turn.audio_path)
                if path.exists() and path.is_file():
                    await self._record_voice(update, ctx)
                    await self._safe_reply_audio(msg, path)
                    return
            except Exception:
                pass

        # TTS opzionale sulla risposta testuale del bot.
        if self._tts_auto_reply_enabled() and turn.content.strip():
            await self._status_edit(status_msg, "🔊 Sintetizzo la risposta…")
            try:
                tts_res = await self._run_tool(
                    "tts",
                    {
                        "text": turn.content,
                        "lang": transcript_lang if transcript_lang != "auto" else self.cfg.default_language,
                        "output_dir": str(self.audio_dir),
                        "output_stem": f"reply_{chat.id}_{getattr(msg, 'message_id', 'x')}",
                    },
                )
            except Exception as e:
                await self._safe_reply(msg, f"TTS fallito: {e}")
                return

            if not tts_res.get("ok"):
                err = str(tts_res.get("error") or "tts failed")
                await self._safe_reply(msg, f"TTS fallito: {err}")
                return

            tts_data = tts_res.get("data") or {}
            audio_path = str(tts_data.get("audio_path") or "").strip()
            if audio_path:
                audio_file = Path(audio_path)
                if audio_file.exists() and audio_file.is_file():
                    await self._record_voice(update, ctx)
                    await self._safe_reply_audio(msg, audio_file, caption="🔊 Risposta audio")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def run_polling(self) -> None:
        """
        Avvio polling Telegram.
        """
        if self.app is None:
            raise RuntimeError("Telegram application not built")

        await self._set_my_commands()
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        try:
            while True:
                await asyncio.sleep(3600)
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
