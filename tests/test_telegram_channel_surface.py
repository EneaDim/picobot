from pathlib import Path

from picobot.bus.queue import MessageBus
from picobot.channels.telegram import TelegramChannel, _normalize_inbound_text


def test_normalize_inbound_text_keeps_slash_command_semantics():
    assert _normalize_inbound_text("/fetch   https://example.com") == "/fetch https://example.com"
    assert _normalize_inbound_text("   /py   print(1+1)  ") == "/py print(1+1)"


def test_telegram_session_mapping(tmp_path: Path):
    bus = MessageBus()
    channel = TelegramChannel(
        bus=bus,
        token="dummy",
        download_dir=tmp_path,
    )
    assert channel._session_id_for_chat(12345) == "tg-12345"
