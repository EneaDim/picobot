from __future__ import annotations

import asyncio
import os
from pathlib import Path

from picobot.bus.queue import MessageBus
from picobot.channels import CLIChannel, ChannelManager, TelegramChannel
from picobot.config.loader import load_config
from picobot.providers.ollama import OllamaProvider
from picobot.runtime import AgentRuntime


DEBUG_CLI = os.getenv("PICOBOT_DEBUG_CLI", "0").strip().lower() in {"1", "true", "yes", "on"}


def _debug(msg: str) -> None:
    if DEBUG_CLI:
        print(f"[debug] {msg}")


def _render_outbound_message(message) -> str | None:
    mtype = getattr(message, "message_type", "")
    payload = getattr(message, "payload", {}) or {}

    if mtype == "outbound.status":
        text = str(payload.get("text") or "").strip()
        return text or None

    if mtype == "outbound.error":
        text = str(payload.get("text") or "").strip()
        return text or "Errore sconosciuto."

    if mtype == "outbound.audio":
        audio_path = str(payload.get("audio_path") or "").strip()
        caption = str(payload.get("caption") or "").strip()
        if caption and audio_path:
            return f"{caption}\n{audio_path}"
        if audio_path:
            return f"Audio generato: {audio_path}"
        return caption or "Audio generato."

    if mtype == "outbound.text":
        text = str(payload.get("text") or "").strip()
        return text or None

    return None


def _get_telegram_settings(cfg) -> tuple[bool, str]:
    telegram_cfg = getattr(cfg, "telegram", None)
    if telegram_cfg is None:
        return False, ""

    enabled = bool(getattr(telegram_cfg, "enabled", False))
    token = getattr(telegram_cfg, "token", "") or getattr(telegram_cfg, "bot_token", "")
    token = str(token or "").strip()

    if not enabled:
        return False, ""

    if not token or token == "YOUR_BOT_TOKEN":
        return False, ""

    return True, token


async def _drain_cli_messages_live(cli_channel: CLIChannel, correlation_id: str) -> None:
    while True:
        msg = await cli_channel.outbound_queue.get()

        if getattr(msg, "correlation_id", None) != correlation_id:
            _debug(
                f"skip message type={getattr(msg, 'message_type', '?')} "
                f"corr={getattr(msg, 'correlation_id', None)} expected={correlation_id}"
            )
            continue

        mtype = getattr(msg, "message_type", "?")
        payload = getattr(msg, "payload", {}) or {}
        _debug(f"recv type={mtype} payload_keys={list(payload.keys())}")

        rendered = _render_outbound_message(msg)
        if rendered:
            print(rendered)

        if mtype in {"outbound.text", "outbound.error"}:
            break


async def run_cli() -> None:
    cfg = load_config()
    workspace = Path(cfg.workspace).expanduser().resolve()
    _debug(f"workspace={workspace}")

    bus = MessageBus()

    ollama_cfg = getattr(cfg, "ollama", None)
    base_url = getattr(ollama_cfg, "base_url", None) or "http://localhost:11434"
    model = getattr(ollama_cfg, "model", None) or getattr(cfg, "model", None)
    timeout_s = getattr(ollama_cfg, "timeout_s", None)

    if not model:
        raise RuntimeError("Ollama model non configurato in .picobot/config.json")

    _debug(f"provider base_url={base_url} model={model} timeout_s={timeout_s}")

    try:
        provider = OllamaProvider(base_url, model, timeout_s=timeout_s)
    except TypeError:
        try:
            provider = OllamaProvider(base_url, model, timeout_s)
        except TypeError:
            provider = OllamaProvider(base_url, model)

    runtime = AgentRuntime(
        bus=bus,
        cfg=cfg,
        provider=provider,
        workspace=workspace,
    )

    channel_manager = ChannelManager(bus=bus)

    cli_channel = CLIChannel(bus=bus, session_id="default")
    channel_manager.register(cli_channel)
    _debug("CLI channel registered")

    telegram_enabled, telegram_token = _get_telegram_settings(cfg)
    if telegram_enabled:
        try:
            tg_channel = TelegramChannel(
                bus=bus,
                token=telegram_token,
                download_dir=workspace / "telegram_uploads",
            )
            channel_manager.register(tg_channel)
            _debug("Telegram channel registered")
        except Exception as exc:
            print(f"[telegram] init failed: {exc}")
    else:
        _debug("Telegram channel disabled or token missing/placeholder")

    await runtime.start()
    _debug("runtime started")
    await channel_manager.start()
    _debug("channel manager started")

    print("picobot ready. CLI attiva. Scrivi /exit per uscire.")
    if telegram_enabled:
        print("Telegram channel abilitato.")

    try:
        while True:
            try:
                user_text = input("> ").strip()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break

            if not user_text:
                continue

            if user_text in {"/exit", "/quit"}:
                break

            correlation_id = await cli_channel.send_text(
                text=user_text,
                session_id="default",
            )
            _debug(f"sent inbound.text correlation_id={correlation_id} text={user_text!r}")

            await _drain_cli_messages_live(cli_channel, correlation_id)

    finally:
        await channel_manager.stop()
        _debug("channel manager stopped")
        await runtime.stop()
        _debug("runtime stopped")


def main() -> None:
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
