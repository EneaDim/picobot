from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command: str
    description: str


COMMAND_SPECS: list[CommandSpec] = [
    CommandSpec("/help", "Mostra aiuto"),
    CommandSpec("/exit", "Esce"),
    CommandSpec("/quit", "Esce"),
    CommandSpec("/status", "Stato runtime"),
    CommandSpec("/tools", "Lista tool registrati"),
    CommandSpec("/mem", "Mostra session state"),
    CommandSpec("/mem tail", "Mostra history"),
    CommandSpec("/mem summary", "Mostra summary"),
    CommandSpec("/mem facts", "Mostra facts"),
    CommandSpec("/mem clean", "Pulisce memoria sessione"),
    CommandSpec("/kb", "Mostra KB attiva"),
    CommandSpec("/kb list", "Lista KB"),
    CommandSpec("/kb use <name>", "Seleziona KB"),
    CommandSpec("/kb ingest <path>", "Ingest PDF nella KB"),
    CommandSpec("/kb query <testo>", "Query locale nella KB"),
    CommandSpec("/news <query>", "Shortcut news digest"),
    CommandSpec("/yt <url>", "Shortcut YouTube summary"),
    CommandSpec("/python <code>", "Shortcut python"),
    CommandSpec("/tts <testo>", "Shortcut TTS"),
]


def command_words() -> list[str]:
    return [spec.command for spec in COMMAND_SPECS]


def build_help_text() -> str:
    sections = {
        "Sistema": ["/help", "/exit", "/quit", "/status", "/tools"],
        "Memoria": ["/mem", "/mem tail", "/mem summary", "/mem facts", "/mem clean"],
        "KB": ["/kb", "/kb list", "/kb use <name>", "/kb ingest <path>", "/kb query <testo>"],
        "Shortcut": ["/news <query>", "/yt <url>", "/python <code>", "/tts <testo>"],
    }

    lines = ["Comandi disponibili", ""]

    for title, commands in sections.items():
        lines.append(title)
        for cmd in commands:
            lines.append(f"  {cmd}")
        lines.append("")

    return "\n".join(lines).rstrip()


HELP_TEXT = build_help_text()
COMMAND_WORDS = command_words()
