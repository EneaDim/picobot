from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from telegram import Update
    from telegram.constants import ChatAction
    from telegram.ext import Application, ContextTypes, MessageHandler, CommandHandler, filters
except Exception:  # pragma: no cover
    Update = Any  # type: ignore
    ChatAction = Any  # type: ignore
    Application = None  # type: ignore
    ContextTypes = Any  # type: ignore
    MessageHandler = Any  # type: ignore
    CommandHandler = Any  # type: ignore
    filters = None  # type: ignore

from picobot.agent.orchestrator import Orchestrator
from picobot.config.schema import Config
from picobot.session.manager import SessionManager, sanitize_session_id
from picobot.tools.retrieval import make_kb_ingest_pdf_tool
from picobot.ui.commands import handle_command


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


@dataclass
class TelegramDedupMap:
    path: Path

    def load(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {}

    def save(self, d: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def has_pdf(self, chat_id: str, key: str) -> bool:
        d = self.load()
        return bool(d.get(chat_id, {}).get("pdf", {}).get(key))

    def record_pdf(self, chat_id: str, key: str, meta: dict[str, Any]) -> None:
        d = self.load()
        d.setdefault(chat_id, {}).setdefault("pdf", {})[key] = meta
        self.save(d)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


async def _run_subprocess(cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
    p = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(p.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        try:
            p.kill()
        except Exception:
            pass
        raise RuntimeError(f"Command timed out after {timeout_s:.0f}s: {' '.join(cmd[:4])} ...")
    out = (out_b or b"").decode("utf-8", errors="replace")
    err = (err_b or b"").decode("utf-8", errors="replace")
    return int(p.returncode or 0), out, err


class TelegramChannel:
    def __init__(self, cfg: Config, sm: SessionManager, orch: Orchestrator, build_app: bool = True) -> None:
        self.cfg = cfg
        self.sm = sm
        self.orch = orch
        ws = Path(cfg.workspace).expanduser().resolve()
        self.map = TelegramSessionMap(ws / "channels" / "telegram" / "session_map.json")
        self.dedup = TelegramDedupMap(ws / "channels" / "telegram" / "dedup.json")
        self.inbox_dir = ws / "channels" / "telegram" / "inbox"
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

        if not cfg.telegram.bot_token:
            raise ValueError("telegram.bot_token is empty")

        self.app = None
        if build_app:
            if Application is None or filters is None:
                raise ImportError(
                    "python-telegram-bot is required for TelegramChannel. Install: pip install python-telegram-bot"
                )
            self.app = Application.builder().token(cfg.telegram.bot_token).build()

            # commands
            self.app.add_handler(CommandHandler("start", self._cmd_start))
            self.app.add_handler(CommandHandler("help", self._cmd_help))
            self.app.add_handler(CommandHandler("session", self._cmd_session))

            # messages
            self.app.add_handler(MessageHandler(filters.COMMAND, self._on_command), group=1)
            self.app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_text))
            self.app.add_handler(
                MessageHandler(filters.Document.MimeType("application/pdf"), self._on_pdf_document)
            )
            self.app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, self._on_voice_or_audio))

    def _dbg_enabled(self) -> bool:
        try:
            return bool(getattr(self.cfg.telegram, "debug_terminal", False) or getattr(self.cfg.debug, "enabled", False))
        except Exception:
            return False

    def _dbg(self, s: str) -> None:
        if self._dbg_enabled():
            print(f"[telegram] {s}", flush=True)

    def _ui(self, text: str) -> str:
        if self.cfg.ui.use_emojis:
            return text
        return text.replace("🧭 ", "").replace("🔎 ", "").replace("💭 ", "").replace("✅ ", "")

    def _kb_name_for_chat(self, chat_id: str) -> str:
        kb_per_chat = bool(getattr(self.cfg.telegram, "kb_per_chat", True))
        if kb_per_chat:
            return f"kb_{chat_id}"
        return getattr(self.cfg, "default_kb_name", "default")

    def _stt_enabled(self) -> bool:
        if hasattr(self.cfg.telegram, "stt_auto"):
            return bool(getattr(self.cfg.telegram, "stt_auto"))
        return bool(getattr(self.cfg.telegram, "voice_stt_enabled", True))

    def _pdf_auto_ingest(self) -> bool:
        return bool(getattr(self.cfg.telegram, "pdf_auto_ingest", True))

    def _echo_transcript(self) -> bool:
        if hasattr(self.cfg.telegram, "send_transcript_flag"):
            return bool(getattr(self.cfg.telegram, "send_transcript_flag"))
        return bool(getattr(self.cfg.telegram, "echo_transcript", False))

    def _max_voice_seconds(self) -> int:
        v = getattr(self.cfg.telegram, "max_voice_seconds", 240)
        try:
            return int(v)
        except Exception:
            return 240

    async def _typing(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            if update.effective_chat:
                await ctx.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.TYPING)
        except Exception:
            pass

    async def _transient(self, msg, text: str) -> Any:
        try:
            return await msg.reply_text(self._ui(text))
        except Exception:
            return None

    async def _transient_set(self, m: Any, text: str) -> None:
        if not m:
            return
        try:
            await m.edit_text(self._ui(text))
        except Exception:
            pass

    async def _transient_clear(self, m: Any) -> None:
        if not m:
            return
        await asyncio.sleep(1.0)
        try:
            await m.delete()
        except Exception:
            pass

    async def _cmd_start(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return
        self._dbg(f"/start chat_id={chat.id}")
        await self._typing(update, ctx)
        await msg.reply_text(
            "✅ Picobot is running.\n"
            "Send me a message to chat.\n"
            "Send a PDF to ingest into the KB for this chat.\n"
            "Send a voice note to transcribe (if enabled).\n\n"
            "Commands:\n"
            "/help\n"
            "/session list\n"
            "/session set <id>\n"
        )

    async def _cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return
        self._dbg(f"/help chat_id={chat.id}")
        await self._typing(update, ctx)
        await msg.reply_text("/help\n/session list\n/session set <id>\n")

    async def _cmd_session(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._typing(update, ctx)
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return
        chat_id = str(chat.id)
        self._dbg(f"/session chat_id={chat_id} args={getattr(ctx,'args',None)}")

        args = ctx.args or []
        if not args:
            sid = self.map.get_session_for_chat(chat_id)
            await msg.reply_text(f"Current session: {sid}")
            return

        if args[0] == "list":
            sessions = self.sm.list()
            mapping = self.map.list_chats()
            lines = ["Sessions:", *(f"- {s}" for s in sessions)]
            lines.append("")
            lines.append("Telegram chat mappings:")
            for k, v in sorted(mapping.items()):
                lines.append(f"- {k} -> {v}")
            await msg.reply_text("\n".join(lines).strip())
            return

        if args[0] == "set" and len(args) >= 2:
            sid = self.map.set_session_for_chat(chat_id, args[1])
            _ = self.sm.get(sid)
            await msg.reply_text("✅ Session set to: " + sid)
            return

        await msg.reply_text("Usage: /session list | /session set <id>")
    async def _on_command(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return

        chat_id = str(chat.id)
        raw = (msg.text or "").strip()
        if not raw.startswith("/"):
            return

        # Let explicit /start keep working (it provides onboarding text)
        cmd = raw.split()[0].lower()
        if cmd in ("/start",):
            return

        self._dbg(f"COMMAND chat_id={chat_id} text={raw!r}")

        # Resolve current session for this chat
        session_id = self.map.get_session_for_chat(chat_id)
        session = self.sm.get(session_id)

        cr = handle_command(raw, session=session, session_manager=self.sm)
        if cr.handled:
            if cr.new_session_id:
                # Persist mapping for this chat too
                self.map.set_session_for_chat(chat_id, cr.new_session_id)
                _ = self.sm.get(cr.new_session_id)
            await self._typing(update, ctx)
            await msg.reply_text(self._ui(cr.reply))
            return

        await self._typing(update, ctx)
        await msg.reply_text(self._ui("Unknown command. Try /help"))
        return


    async def _on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return

        chat_id = str(chat.id)
        user_text = (msg.text or "").strip()
        if not user_text:
            return

        self._dbg(f"TEXT chat_id={chat_id} len={len(user_text)}")

        session_id = self.map.get_session_for_chat(chat_id)
        session = self.sm.get(session_id)
        session.set_state({"kb_name": self._kb_name_for_chat(chat_id)})

        await self._typing(update, ctx)

        status_msg = None
        last_status = None

        async def status_cb(s: str) -> None:
            nonlocal status_msg, last_status
            s = self._ui(s)
            if last_status is not None and s != last_status:
                await asyncio.sleep(1.0)
            last_status = s
            try:
                if status_msg is None:
                    status_msg = await msg.reply_text(s)
                else:
                    await status_msg.edit_text(s)
            except Exception:
                pass

        try:
            res = await self.orch.one_turn(session, user_text, status=status_cb)
            await msg.reply_text(res.content or "(empty)")
        except Exception as e:
            self._dbg(f"TEXT error: {e!r}")
            await msg.reply_text(f"⚠️ Error: {e}")
        finally:
            await asyncio.sleep(1.0)
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

    async def _on_pdf_document(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return
        if not self._pdf_auto_ingest():
            self._dbg("PDF received but pdf_auto_ingest disabled")
            return

        doc = getattr(msg, "document", None)
        if not doc or (getattr(doc, "mime_type", "") or "").lower() != "application/pdf":
            return

        chat_id = str(chat.id)
        self._dbg(f"PDF chat_id={chat_id} file_id={getattr(doc,'file_id',None)} name={getattr(doc,'file_name',None)}")

        session_id = self.map.get_session_for_chat(chat_id)
        session = self.sm.get(session_id)
        kb_name = self._kb_name_for_chat(chat_id)
        session.set_state({"kb_name": kb_name})

        await self._typing(update, ctx)

        status = await self._transient(msg, "🔎 Downloading PDF…")

        file_name = (getattr(doc, "file_name", None) or f"{doc.file_id}.pdf").strip()
        safe_name = sanitize_session_id(file_name).replace("-", "_")
        if not safe_name.lower().endswith(".pdf"):
            safe_name += ".pdf"

        dest_dir = self.inbox_dir / chat_id / "pdf"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / safe_name

        try:
            tg_file = await ctx.bot.get_file(doc.file_id)
            await tg_file.download_to_drive(custom_path=str(dest_path))
        except Exception as e:
            await self._transient_set(status, "⚠️ Download failed.")
            await self._transient_clear(status)
            await msg.reply_text(f"⚠️ Could not download PDF: {e}")
            self._dbg(f"PDF download error: {e!r}")
            return

        try:
            size = int(getattr(doc, "file_size", 0) or dest_path.stat().st_size)
        except Exception:
            size = 0

        try:
            sha = _sha256_file(dest_path)
        except Exception as e:
            await self._transient_set(status, "⚠️ Hash failed.")
            await self._transient_clear(status)
            await msg.reply_text(f"⚠️ Could not hash PDF for dedup: {e}")
            self._dbg(f"PDF hash error: {e!r}")
            return

        dedup_key = f"{sha}:{size}"
        if self.dedup.has_pdf(chat_id, dedup_key):
            await self._transient_set(status, "✅ Already ingested (dedup).")
            await self._transient_clear(status)
            await msg.reply_text("✅ PDF already ingested for this chat. (dedup hit)")
            self._dbg("PDF dedup hit")
            return

        await self._transient_set(status, "🧠 Ingesting into KB…")

        tool = make_kb_ingest_pdf_tool(self.orch.docs_root)
        try:
            model = tool.validate(
                {
                    "kb_name": kb_name,
                    "pdf_path": str(dest_path),
                    "doc_name": Path(file_name).stem or "document",
                    "chunk_chars": int(getattr(self.cfg.retrieval, "chunk_chars", 900)),
                    "overlap": int(getattr(self.cfg.retrieval, "chunk_overlap", 120)),
                }
            )
            data = await tool.handler(model)
        except Exception as e:
            await self._transient_set(status, "⚠️ Ingest failed.")
            await self._transient_clear(status)
            await msg.reply_text(f"⚠️ PDF ingest failed: {e}")
            self._dbg(f"PDF ingest error: {e!r}")
            return

        self.dedup.record_pdf(
            chat_id,
            dedup_key,
            {
                "file_name": file_name,
                "size": size,
                "sha256": sha,
                "kb_name": kb_name,
                "source_pdf": data.get("source_pdf"),
                "chunks": data.get("chunks"),
            },
        )

        await self._transient_set(status, "✅ Ingest OK.")
        await self._transient_clear(status)

        await msg.reply_text(
            f"✅ Ingest OK into KB '{kb_name}'.\n"
            f"Document: {file_name}\n"
            f"Chunks: {data.get('chunks')}"
        )

    def _resolve_whisper_main(self) -> Path:
        p = Path(getattr(self.cfg.tools, "whisper_cpp_main_path", "") or "").expanduser()
        if p and not p.is_absolute():
            p = (Path.cwd() / p).resolve()
        if p and p.exists():
            return p

        d = Path(getattr(self.cfg.tools, "whisper_cpp_dir", "") or "").expanduser()
        if d and not d.is_absolute():
            d = (Path.cwd() / d).resolve()
        cand = d / "main"
        if cand.exists():
            return cand

        return (Path.cwd() / "whisper.cpp" / "main").resolve()

    async def _on_voice_or_audio(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        chat = update.effective_chat
        msg = update.effective_message
        if not chat or not msg:
            return
        if not self._stt_enabled():
            self._dbg("VOICE/AUDIO received but stt_auto disabled")
            return

        chat_id = str(chat.id)

        voice = getattr(msg, "voice", None)
        audio = getattr(msg, "audio", None)
        media = voice or audio
        if not media:
            return

        duration = int(getattr(media, "duration", 0) or 0)
        max_s = self._max_voice_seconds()
        self._dbg(f"VOICE/AUDIO chat_id={chat_id} file_id={getattr(media,'file_id',None)} duration={duration}s max={max_s}s")

        if duration and max_s and duration > max_s:
            await msg.reply_text(f"⚠️ Voice/audio too long ({duration}s). Max allowed: {max_s}s.")
            return

        session_id = self.map.get_session_for_chat(chat_id)
        session = self.sm.get(session_id)
        session.set_state({"kb_name": self._kb_name_for_chat(chat_id)})

        await self._typing(update, ctx)

        status = await self._transient(msg, "🔎 Downloading audio…")

        dest_dir = self.inbox_dir / chat_id / "voice"
        dest_dir.mkdir(parents=True, exist_ok=True)

        ext = "ogg" if voice else (Path(getattr(audio, "file_name", "audio")).suffix.lstrip(".") or "bin")
        in_path = dest_dir / f"{media.file_id}.{ext}"
        wav_path = dest_dir / f"{media.file_id}.wav"
        out_prefix = dest_dir / f"{media.file_id}_whisper"

        try:
            tg_file = await ctx.bot.get_file(media.file_id)
            await tg_file.download_to_drive(custom_path=str(in_path))
        except Exception as e:
            await self._transient_set(status, "⚠️ Download failed.")
            await self._transient_clear(status)
            await msg.reply_text(f"⚠️ Could not download voice/audio: {e}")
            self._dbg(f"VOICE download error: {e!r}")
            return

        await self._transient_set(status, "🔎 Converting with ffmpeg…")

        ffmpeg = str(getattr(self.cfg.tools, "ffmpeg_bin", "ffmpeg") or "ffmpeg")
        
        lang = (getattr(self.cfg.tools, "whisper_language", "auto") or "auto").strip()

        cmd = [str(whisper_main), "-m", str(model), "-f", str(wav_path)]
        if lang:
            cmd += ["-l", lang]          # <-- auto / it / en
        cmd += ["-otxt", "-of", str(out_prefix)]

        try:
            rc, out, err = await _run_subprocess(
                cmd,
                timeout_s=max(90.0, float(max_s) * 1.5 if max_s else 180.0),
            )
            if rc != 0:
                await self._transient_set(status, "⚠️ ffmpeg failed.")
                await self._transient_clear(status)
                await msg.reply_text(f"⚠️ ffmpeg failed: {err.strip()[:400]}")
                self._dbg(f"ffmpeg rc={rc} err={err.strip()[:400]!r}")
                return
        except Exception as e:
            await self._transient_set(status, "⚠️ ffmpeg error.")
            await self._transient_clear(status)
            await msg.reply_text(f"⚠️ ffmpeg error: {e}")
            self._dbg(f"ffmpeg exception: {e!r}")
            return

        await self._transient_set(status, "💭 Transcribing with whisper.cpp…")

        whisper_main = self._resolve_whisper_main()
        model = Path(getattr(self.cfg.tools, "whisper_model", "") or "").expanduser()
        if model and not model.is_absolute():
            model = (Path.cwd() / model).resolve()

        if not whisper_main.exists():
            await self._transient_set(status, "⚠️ whisper.cpp not found.")
            await self._transient_clear(status)
            await msg.reply_text("⚠️ whisper.cpp main not found. Configure tools.whisper_cpp_main_path/whisper_cpp_dir.")
            return
        if not model.exists():
            await self._transient_set(status, "⚠️ model not found.")
            await self._transient_clear(status)
            await msg.reply_text("⚠️ whisper model not found. Configure tools.whisper_model.")
            return

        try:
            rc, out, err = await _run_subprocess(
                [str(whisper_main), "-m", str(model), "-f", str(wav_path), "-otxt", "-of", str(out_prefix)],
                timeout_s=max(90.0, float(max_s) * 1.5 if max_s else 180.0),
            )
            if rc != 0:
                await self._transient_set(status, "⚠️ whisper.cpp failed.")
                await self._transient_clear(status)
                await msg.reply_text(f"⚠️ whisper.cpp failed: {err.strip()[:400]}")
                self._dbg(f"whisper rc={rc} err={err.strip()[:400]!r}")
                return
        except Exception as e:
            await self._transient_set(status, "⚠️ whisper.cpp error.")
            await self._transient_clear(status)
            await msg.reply_text(f"⚠️ whisper.cpp error: {e}")
            self._dbg(f"whisper exception: {e!r}")
            return

        txt_path = Path(str(out_prefix) + ".txt")
        transcript = ""
        try:
            if txt_path.exists():
                transcript = txt_path.read_text(encoding="utf-8", errors="replace").strip()
            if not transcript:
                transcript = (out or "").strip()
        except Exception:
            transcript = (out or "").strip()

        if not transcript:
            await self._transient_set(status, "⚠️ Empty transcript.")
            await self._transient_clear(status)
            await msg.reply_text("⚠️ Empty transcription.")
            return

        if self._echo_transcript():
            await msg.reply_text("💬 Transcript:\n" + transcript[:3500] + ("…" if len(transcript) > 3500 else ""))

        await self._transient_set(status, "🧭 Thinking…")

        status_msg = None
        last_status = None

        async def status_cb(s: str) -> None:
            nonlocal status_msg, last_status
            s = self._ui(s)
            if last_status is not None and s != last_status:
                await asyncio.sleep(1.0)
            last_status = s
            try:
                if status_msg is None:
                    status_msg = await msg.reply_text(s)
                else:
                    await status_msg.edit_text(s)
            except Exception:
                pass

        try:
            res = await self.orch.one_turn(session, transcript, status=status_cb)
            await msg.reply_text(res.content or "(empty)")
            await self._transient_set(status, "✅ Done.")
        except Exception as e:
            self._dbg(f"VOICE/AUDIO orchestrator error: {e!r}")
            await msg.reply_text(f"⚠️ Error: {e}")
            await self._transient_set(status, "⚠️ Error.")
        finally:
            await self._transient_clear(status)
            await asyncio.sleep(1.0)
            if status_msg:
                try:
                    await status_msg.delete()
                except Exception:
                    pass

    async def run(self) -> None:
        if self.app is None:
            raise RuntimeError("TelegramChannel initialized with build_app=False")
        self._dbg("Starting Telegram polling…")
        await self.app.initialize()
        await self.app.start()
        await self.app.updater.start_polling()
        self._dbg("Telegram polling started.")
        try:
            await asyncio.Event().wait()
        finally:
            self._dbg("Stopping Telegram polling…")
            await self.app.updater.stop()
            await self.app.stop()
            await self.app.shutdown()
