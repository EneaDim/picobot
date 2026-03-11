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
    CommandSpec("/route <testo>", "Mostra la route deterministica senza eseguire il turno"),
    CommandSpec("/mem", "Mostra session state"),
    CommandSpec("/mem tail", "Mostra history"),
    CommandSpec("/mem summary", "Mostra summary"),
    CommandSpec("/mem facts", "Mostra facts"),
    CommandSpec("/mem clean", "Pulisce memoria sessione"),
    CommandSpec("/kb", "Mostra KB attiva"),
    CommandSpec("/kb list", "Lista KB"),
    CommandSpec("/kb use <name>", "Seleziona KB"),
    CommandSpec("/kb ingest <path>", "Ingest PDF nella KB"),
    CommandSpec("/kb query <testo>", "Query locale raw e deterministica nella KB"),
    CommandSpec("/news <query>", "Pass-through al runtime per news digest"),
    CommandSpec("/yt <url>", "Pass-through al runtime per YouTube summary"),
    CommandSpec("/python <code>", "Pass-through al runtime per tool python"),
    CommandSpec("/py <code>", "Alias breve di /python"),
    CommandSpec("/tts <testo>", "Pass-through al runtime per TTS"),
    CommandSpec("/fetch <url|query>", "Pass-through al runtime per web tool"),
    CommandSpec("/file <path>", "Pass-through al runtime per file tool"),
    CommandSpec("/stt <audio_path>", "Pass-through al runtime per STT"),
    CommandSpec("/podcast <topic>", "Pass-through al runtime per podcast"),
]


def command_words() -> list[str]:
    return [spec.command for spec in COMMAND_SPECS]


def build_help_text() -> str:
    sections = {
        "Sistema": ["/help", "/exit", "/quit", "/status", "/tools", "/route <testo>"],
        "Memoria": ["/mem", "/mem tail", "/mem summary", "/mem facts", "/mem clean"],
        "KB": ["/kb", "/kb list", "/kb use <name>", "/kb ingest <path>", "/kb query <testo>"],
        "Pass-through runtime": [
            "/news <query>",
            "/yt <url>",
            "/python <code>",
            "/py <code>",
            "/tts <testo>",
            "/fetch <url|query>",
            "/file <path>",
            "/stt <audio_path>",
            "/podcast <topic>",
        ],
    }

    lines = [
        "Comandi disponibili",
        "",
        "Nota: /kb query resta locale e deterministico; le domande naturali con KB attiva passano invece dal runtime/router.",
        "",
    ]

    for title, commands in sections.items():
        lines.append(title)
        for cmd in commands:
            lines.append(f"  {cmd}")
        lines.append("")

    return "\n".join(lines).rstrip()


HELP_TEXT = build_help_text()
COMMAND_WORDS = command_words()
