from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from picobot.providers.types import ChatResponse
from picobot.tools.tts import synthesize_speech

_PODCAST_COMMAND_RX = re.compile(r"^\s*/podcast\b", re.IGNORECASE)

_EXPLICIT_REQUEST_RX = re.compile(
    r"\b("
    r"genera un podcast(?: su)?|"
    r"crea un podcast(?: su)?|"
    r"fammi un podcast(?: su)?|"
    r"voglio un podcast(?: su)?|"
    r"vorrei un podcast(?: su)?|"
    r"make a podcast(?: about)?|"
    r"generate a podcast(?: about)?|"
    r"produce a podcast(?: about)?|"
    r"i want a podcast(?: about)?|"
    r"i'd like a podcast(?: about)?"
    r")\b",
    re.IGNORECASE,
)

_EN_HINT_RX = re.compile(
    r"\b("
    r"make|generate|produce|about|episode|"
    r"local-first|agents|systems|architecture|"
    r"i want|i'd like"
    r")\b",
    re.IGNORECASE,
)

_IT_HINT_RX = re.compile(
    r"\b("
    r"voglio|vorrei|genera|crea|fammi|su|"
    r"sistemi|agenti|architettura|episodio"
    r")\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class PodcastResult:
    audio_path: str
    script: str


def _detect_podcast_lang(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return "it"

    en_score = len(_EN_HINT_RX.findall(raw))
    it_score = len(_IT_HINT_RX.findall(raw))

    if en_score > it_score:
        return "en"
    return "it"


def _slugify(value: str) -> str:
    slug = (
        str(value or "")
        .lower()
        .replace("/", "-")
        .replace(" ", "-")
        .replace("_", "-")
    )
    slug = re.sub(r"[^a-z0-9\-]+", "", slug)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")
    return slug or "podcast"


def detect_podcast_request(text: str, cfg=None) -> tuple[str, str] | None:
    raw = (text or "").strip()
    if not raw:
        return None

    if _PODCAST_COMMAND_RX.match(raw):
        topic = raw[len("/podcast"):].strip()
        return (topic or "podcast", _detect_podcast_lang(topic or raw))

    # Non trasformare domande normali in podcast.
    if "?" in raw and not _EXPLICIT_REQUEST_RX.search(raw):
        return None

    if _EXPLICIT_REQUEST_RX.search(raw):
        topic = _EXPLICIT_REQUEST_RX.sub("", raw).strip(" :.-")
        return (topic or "podcast", _detect_podcast_lang(raw))

    return None


async def generate_podcast(cfg, provider, *, topic: str, lang: str, status=None) -> PodcastResult:
    if status:
        await status("📝 Sto scrivendo lo script del podcast…")

    messages = [
        {
            "role": "system",
            "content": (
                "Sei un autore di podcast tecnico. "
                "Scrivi uno script chiaro, compatto e naturale, nella lingua richiesta. "
                "Strutturalo come un breve episodio parlato, fluido da ascoltare."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Scrivi uno script breve per un podcast in lingua '{lang}' "
                f"sul tema: {topic}"
            ),
        },
    ]

    resp: ChatResponse = await provider.chat(
        messages=messages,
        tools=None,
        max_tokens=1200,
        temperature=0.3,
    )

    script = (resp.content or "").strip() or (
        f"Breve podcast sul tema: {topic}" if lang == "it" else f"Short podcast about: {topic}"
    )

    if status:
        await status("🔊 Sto sintetizzando l'audio del podcast…")

    out_dir = Path(cfg.workspace).expanduser().resolve() / "outputs" / "podcasts"
    out_dir.mkdir(parents=True, exist_ok=True)

    file_stem = _slugify(topic)

    audio_path = synthesize_speech(
        cfg,
        script,
        lang=lang,
        output_dir=str(out_dir),
        file_stem=file_stem,
        audio_format="wav",
    )

    audio_path_str = str(audio_path).strip()
    if not audio_path_str:
        raise RuntimeError("podcast tts completed without audio_path")

    audio_file = Path(audio_path_str)
    if not audio_file.exists():
        raise RuntimeError(f"podcast audio file missing: {audio_file}")

    if audio_file.stat().st_size <= 0:
        raise RuntimeError(f"podcast audio file is empty: {audio_file}")

    return PodcastResult(
        audio_path=audio_path_str,
        script=script,
    )
