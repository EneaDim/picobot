from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import Application, ContextTypes, MessageHandler, CommandHandler, filters

from picobot.agent.orchestrator import Orchestrator
from picobot.config.schema import Config
from picobot.session.manager import SessionManager, sanitize_session_id


@dataclass
class TelegramSessionMap:
    path: Path

    def load(self) -> dict[str, str]:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save(self, m: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(m, indent=2), encoding="utf-8")

    def get_session_for_chat(self, chat_id: str) -> str:
        m = self.load()
        return m.get(chat_id, f"tg-{chat_id}")

    def set_session_for_chat(self, chat_id: str, session_id: str) -> str:
        m = self.load()
        sid = sanitize_session_id(session_id)
        m[chat_id] = sid
        self.save(m)
        return sid

    def list_chats(self) -> dict[str, str]:
        return self.load()


class TelegramChannel:
    """
    Telegram adapter:
    - maps telegram chat_id -> session_id
    - supports /session list, /session set <id>
    - sends typing action + transient status message (edit/delete)
    - minimum 1s display for status transitions
    """
    def __init__(self, cfg: Config, sm: SessionManager, orch: Orchestrator) -> None:
        self.cfg = cfg
        self.sm = sm
        self.orch = orch
        ws = Path(cfg.workspace).expanduser().resolve()
        self.map = TelegramSessionMap(ws / "channels" / "telegram" / "session_map.json")

        if not cfg.telegram.bot_token:
            raise ValueError("telegram.bot_token is empty")
        self.app = Application.builder().token(cfg.telegram.bot_token).build()

        # commands
        self.app.add_handler(CommandHandler("help", self._cmd_help))
        self.app.add_handler(CommandHandler("session", self._cmd_session))

        # messages
        self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))

        # voice STT will be added next step (kept adapter-only), so for now ignore voice
        # self.app.add_handler(MessageHandler(filters.VOICE, self._on_voice))

    def _ui(self, text: str) -> str:
        if self.cfg.ui.use_emojis:
            return text
        return text.replace("🧭 ", "").replace("🔎 ", "").replace("💭 ", "").replace("✅ ", "")

    async def _typing(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if update.effective_chat:
                await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except Exception:
            pass

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._typing(update, ctx)
        msg = (
            "/help\n"
            "/session list\n"
            "/session set <id>\n"
        )
        await update.effective_message.reply_text(msg)

    async def _cmd_session(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._typing(update, ctx)
        chat = update.effective_chat
        if not chat:
            return
        chat_id = str(chat.id)

        args = ctx.args or []
        if not args:
            sid = self.map.get_session_for_chat(chat_id)
            await update.effective_message.reply_text(f"Current session: {sid}")
            return

        if args[0] == "list":
            sessions = self.sm.list()
            mapping = self.map.list_chats()
            lines = ["Sessions:", *(f"- {s}" for s in sessions)]
            lines.append("")
            lines.append("Telegram chat mappings:")
            for k, v in sorted(mapping.items()):
                lines.append(f"- {k} -> {v}")
            await update.effective_message.reply_text("\n".join(lines).strip())
            return

        if args[0] == "set" and len(args) >= 2:
            sid = self.map.set_session_for_chat(chat_id, args[1])
            _ = self.sm.get(sid)
            await update.effective_message.reply_text(f"✅ Session set to: {sid}")
            return

        await update.effective_message.reply_text("Usage: /session list | /session set <id>")

    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return

        chat_id = str(chat.id)
        user_text = (msg.text or "").strip()
        if not user_text:
            return

        session_id = self.map.get_session_for_chat(chat_id)
        session = self.sm.get(session_id)

        await self._typing(update, ctx)

        status_msg = None
        last_status = None

        async def status_cb(s: str) -> None:
            nonlocal status_msg, last_status
            s = self._ui(s)

            # ensure a minimum display time between transitions
            if last_status is not None and s != last_status:
                await asyncio.sleep(1.0)

            last_status = s
            try:
                if status_msg is None:
                    status_msg = await msg.reply_text(s)
                else:
                    await status_msg.edit_text(s)
            except Exception:
                # if editing fails, just ignore
                pass

        try:
            res = await self.orch.one_turn(session, user_text, status=status_cb)
            await msg.reply_text(res.content or "(empty)")
        finally:
            # allow last status to be visible for at least 1s
            await asyncio.sleep(1.0)
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

    async def run(self) -> None:
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        try:
            await asyncio.Event().wait()
        finally:
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
