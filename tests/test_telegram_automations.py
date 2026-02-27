from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from picobot.config.schema import Config
from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse
from picobot.channels.telegram import TelegramChannel


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(content="ok", tool_calls=[])


@dataclass
class FakeChat:
    id: int


class FakeFile:
    def __init__(self, content: bytes):
        self._content = content

    async def download_to_drive(self, custom_path: str):
        Path(custom_path).write_bytes(self._content)


class FakeBot:
    def __init__(self, content: bytes):
        self._content = content
        self.get_file_calls = 0

    async def get_file(self, file_id: str):
        self.get_file_calls += 1
        return FakeFile(self._content)

    async def send_chat_action(self, chat_id: int, action: str):
        return None


class FakeContext:
    def __init__(self, bot: FakeBot):
        self.bot = bot
        self.args = []


class FakeDocument:
    def __init__(self, file_id: str, file_name: str, file_size: int, mime_type: str = "application/pdf"):
        self.file_id = file_id
        self.file_name = file_name
        self.file_size = file_size
        self.mime_type = mime_type


class FakeVoice:
    def __init__(self, file_id: str, duration: int):
        self.file_id = file_id
        self.duration = duration


class FakeMessage:
    def __init__(self, text: str | None = None, document=None, voice=None, audio=None):
        self.text = text
        self.document = document
        self.voice = voice
        self.audio = audio
        self.replies: list[str] = []

    async def reply_text(self, text: str):
        self.replies.append(text)
        return self

    async def edit_text(self, text: str):
        return None

    async def delete(self):
        return None


class FakeUpdate:
    def __init__(self, chat_id: int, message: FakeMessage):
        self.effective_chat = FakeChat(chat_id)
        self.effective_message = message


@pytest.mark.asyncio
async def test_pdf_auto_ingest_and_dedup(tmp_path: Path, monkeypatch):
    cfg = Config(workspace=str(tmp_path))
    cfg.telegram.bot_token = "dummy"
    cfg.telegram.pdf_auto_ingest = True
    cfg.telegram.kb_per_chat = True

    # patch pdf extraction to avoid needing a real PDF parser
    simple_text = "hello pdf\n" * 50

    def fake_pdf_to_text(_path: Path) -> str:
        return simple_text

    import picobot.tools.retrieval as tool_mod
    import picobot.retrieval.ingest as ingest_mod

    monkeypatch.setattr(tool_mod, "pdf_to_text", fake_pdf_to_text)
    monkeypatch.setattr(ingest_mod, "pdf_to_text", fake_pdf_to_text)

    sm = SessionManager(tmp_path)
    orch = Orchestrator(cfg, DummyProvider(), tmp_path)

    ch = TelegramChannel(cfg, sm, orch, build_app=False)

    pdf_bytes = b"%PDF-1.4\n%fake\n"
    bot = FakeBot(pdf_bytes)
    ctx = FakeContext(bot)

    msg = FakeMessage(document=FakeDocument("f1", "demo.pdf", len(pdf_bytes)))
    upd = FakeUpdate(123, msg)

    await ch._on_pdf_document(upd, ctx)
    assert any("Ingest OK" in r for r in msg.replies)
    assert bot.get_file_calls == 1

    # second time: dedup hit
    msg2 = FakeMessage(document=FakeDocument("f1", "demo.pdf", len(pdf_bytes)))
    upd2 = FakeUpdate(123, msg2)
    await ch._on_pdf_document(upd2, ctx)
    assert any("dedup hit" in r.lower() for r in msg2.replies)
    assert bot.get_file_calls == 2  # still downloads, but does not reingest


@pytest.mark.asyncio
async def test_voice_guardrail_max_duration(tmp_path: Path):
    cfg = Config(workspace=str(tmp_path))
    cfg.telegram.bot_token = "dummy"
    cfg.telegram.stt_auto = True
    cfg.telegram.max_voice_seconds = 10

    sm = SessionManager(tmp_path)
    orch = Orchestrator(cfg, DummyProvider(), tmp_path)
    ch = TelegramChannel(cfg, sm, orch, build_app=False)

    bot = FakeBot(b"dummy")
    ctx = FakeContext(bot)

    msg = FakeMessage(voice=FakeVoice("v1", duration=999))
    upd = FakeUpdate(123, msg)

    await ch._on_voice_or_audio(upd, ctx)
    assert any("too long" in r.lower() for r in msg.replies)
    assert bot.get_file_calls == 0
