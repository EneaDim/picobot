from __future__ import annotations

import asyncio
import os
from pathlib import Path

from picobot.bus.queue import MessageBus
from picobot.channels import CLIChannel, ChannelManager, TelegramChannel
from picobot.config.loader import load_config
from picobot.providers.ollama import OllamaProvider
from picobot.runtime import AgentRuntime
from picobot.ui.commands import handle_local_command
from picobot.ui.terminal import TerminalUI
from picobot.app.telegram_monitor import TelegramMirror


DEBUG_CLI = os.getenv("PICOBOT_TRACE_INTERNAL", "0").strip().lower() in {"1", "true", "yes", "on"}


def _debug(msg: str) -> None:
    if DEBUG_CLI:
        print(f"[trace] {msg}")


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


async def run_cli() -> None:
    cfg = load_config()
    workspace = Path(cfg.workspace).expanduser().resolve()
    _debug(f"workspace={workspace}")

    ui = TerminalUI(cfg=cfg, workspace=workspace)

    bus = MessageBus()
    await bus.start()
    _debug("message bus started")

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
    telegram_mirror = None
    tg_channel = None

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
                cfg=cfg,
            )
            tg_channel.bind_runtime_context(
                channel_manager=channel_manager,
                workspace=workspace,
            )
            channel_manager.register(tg_channel)
            _debug("Telegram channel registered")
        except Exception as exc:
            ui.print_error(f"[telegram] init failed: {exc}")
    else:
        _debug("Telegram channel disabled or token missing/placeholder")

    await runtime.start()
    _debug("runtime started")
    await channel_manager.start()
    if telegram_enabled and DEBUG_CLI:
        telegram_mirror = TelegramMirror(bus=bus, print_debug=ui.print_debug)
        await telegram_mirror.start()
        print("👀 Telegram monitor active.")
    _debug("channel manager started")

    ui.print_banner(telegram_enabled=telegram_enabled)

    try:
        while True:
            try:
                user_text = await ui.prompt()
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break

            if not user_text:
                continue

            cmd = handle_local_command(
                raw_text=user_text,
                cfg=cfg,
                workspace=workspace,
                session_id="default",
                orchestrator=runtime.orchestrator,
            )

            if cmd.handled:
                if cmd.text:
                    ui.print_info(cmd.text)
                if cmd.should_exit:
                    break
                if not cmd.bus_text:
                    continue
                user_text = cmd.bus_text

            correlation_id = await cli_channel.send_text(
                text=user_text,
                session_id="default",
            )
            _debug(f"sent inbound.text correlation_id={correlation_id} text={user_text!r}")

            await ui.drain_messages(
                cli_channel=cli_channel,
                correlation_id=correlation_id,
                debug_cb=_debug,
            )

    finally:
        ui.clear_status()
        if telegram_mirror is not None:
            await telegram_mirror.stop()
        await channel_manager.stop()
        _debug("channel manager stopped")
        await runtime.stop()
        _debug("runtime stopped")
        await bus.stop()
        _debug("message bus stopped")




def _format_debug_runtime_event(message) -> str | None:
    mtype = str(getattr(message, "message_type", "") or "")
    payload = dict(getattr(message, "payload", {}) or {})

    if mtype == "runtime.turn_started":
        return f"[runtime] turn_started text_len={payload.get('text_len', '?')}"

    if mtype == "runtime.turn.route_selected":
        lines = [
            f"[router] selected {payload.get('route_action', '?')}:{payload.get('route_name', '?')}"
            f" source={payload.get('route_source', '?')}"
            f" score={payload.get('route_score', 0.0):.3f}"
        ]
        reason = payload.get("route_reason")
        if reason:
            lines.append(f'[router] reason="{reason}"')
        candidates = list(payload.get("route_candidates", []) or [])
        if candidates:
            lines.append("[router] candidates:")
            for item in candidates[:4]:
                lines.append(f"  {item}")
        return "\n".join(lines)

    if mtype == "runtime.retrieval.started":
        return (
            f"[retrieval] started kb={payload.get('kb_name', '?')} "
            f"top_k={payload.get('top_k', '?')}"
        )

    if mtype == "runtime.retrieval.completed":
        if payload.get("ok") is False:
            return f"[retrieval] failed error={payload.get('error', '?')}"
        return (
            f"[retrieval] completed hits={payload.get('hits', 0)} "
            f"context_chars={payload.get('context_chars', 0)}"
        )

    if mtype == "runtime.turn.context_built":
        return (
            f"[context] workflow={payload.get('workflow_name', '?')} "
            f"history={payload.get('history_messages_count', 0)} "
            f"facts={payload.get('memory_facts_count', 0)} "
            f"summary={'yes' if payload.get('summary_present') else 'no'} "
            f"retrieval={'yes' if payload.get('retrieval_present') else 'no'}"
        )

    if mtype == "runtime.tool.started":
        return (
            f"[tool] started name={payload.get('tool_name', '?')} "
            f"workflow={payload.get('workflow_name', '?')}"
        )

    if mtype == "runtime.tool.completed":
        return (
            f"[tool] completed name={payload.get('tool_name', '?')} "
            f"ok={payload.get('ok', True)}"
        )

    if mtype == "runtime.tool.failed":
        return (
            f"[tool] failed name={payload.get('tool_name', '?')} "
            f"error={payload.get('error', '?')}"
        )

    if mtype == "runtime.turn_completed":
        return (
            f"[turn] completed action={payload.get('action', '?')} "
            f"reason={payload.get('reason', '?')} "
            f"provider={payload.get('provider_name', '-') or '-'} "
            f"hits={payload.get('retrieval_hits', 0)} "
            f"audio={'yes' if payload.get('has_audio') else 'no'}"
        )

    if mtype == "runtime.turn_failed":
        return f"[turn] failed error={payload.get('error', '?')}"

    return None


def main() -> None:
    asyncio.run(run_cli())


if __name__ == "__main__":
    main()
