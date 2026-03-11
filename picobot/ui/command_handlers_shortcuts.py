from __future__ import annotations

import json

from picobot.ui.command_models import CommandResult


def dispatch_shortcut_command(*, text: str) -> CommandResult | None:
    if text.startswith("/news "):
        arg = text[len("/news "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /news <query>")
        return CommandResult(handled=True, bus_text=f"/news {arg}")

    if text.startswith("/yt "):
        arg = text[len("/yt "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /yt <youtube-url>")
        return CommandResult(handled=True, bus_text=f"riassumi questo video {arg}")

    if text.startswith("/python "):
        arg = text[len("/python "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /python <code>")
        payload = json.dumps({"code": arg}, ensure_ascii=False)
        return CommandResult(handled=True, bus_text=f"tool python {payload}")

    if text.startswith("/tts "):
        arg = text[len("/tts "):].strip()
        if not arg:
            return CommandResult(handled=True, text="Uso: /tts <testo>")
        payload = json.dumps({"text": arg}, ensure_ascii=False)
        return CommandResult(handled=True, bus_text=f"tool tts {payload}")

    return None
