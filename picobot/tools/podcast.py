from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from picobot.agent.prompts import detect_language, system_base_context
from picobot.tools.tts import synthesize_speech

StatusCb = Callable[[str], Awaitable[None]]


@dataclass(slots=True)
class PodcastResult:
    topic: str
    lang: str
    script: str
    audio_path: str


def _normalize_text(value: str | None) -> str:
    return str(value or "").strip()


def detect_podcast_request(user_text: str, cfg=None) -> tuple[str, str] | None:
    text = _normalize_text(user_text)
    if not text:
        return None

    low = text.lower()

    podcast_cfg = getattr(cfg, "podcast", None)

    triggers_it = []
    triggers_en = []

    if podcast_cfg is not None:
        triggers = getattr(podcast_cfg, "triggers", None)
        if triggers is not None:
            triggers_it = list(getattr(triggers, "it", []) or [])
            triggers_en = list(getattr(triggers, "en", []) or [])

    default_it = [
        "voglio un podcast su",
        "fammi un podcast su",
        "/podcast",
    ]
    default_en = [
        "i want a podcast about",
        "make a podcast about",
    ]

    for trig in [*triggers_it, *default_it]:
        t = _normalize_text(trig).lower()
        if t and low.startswith(t):
            topic = text[len(trig):].strip() if len(text) >= len(trig) else ""
            return topic, "it"

    for trig in [*triggers_en, *default_en]:
        t = _normalize_text(trig).lower()
        if t and low.startswith(t):
            topic = text[len(trig):].strip() if len(text) >= len(trig) else ""
            return topic, "en"

    return None


def _target_words(cfg, minutes: int) -> int:
    podcast_cfg = getattr(cfg, "podcast", None)
    wpm = int(getattr(podcast_cfg, "target_words_per_minute", 150) or 150) if podcast_cfg else 150
    return max(120, int(minutes) * wpm)


def _default_minutes(cfg) -> int:
    podcast_cfg = getattr(cfg, "podcast", None)
    return int(getattr(podcast_cfg, "default_minutes", 1) or 1) if podcast_cfg else 1


def _output_dir(cfg) -> str:
    podcast_cfg = getattr(cfg, "podcast", None)
    value = str(getattr(podcast_cfg, "output_dir", "outputs/podcasts") or "outputs/podcasts") if podcast_cfg else "outputs/podcasts"
    return value


def _audio_format(cfg) -> str:
    podcast_cfg = getattr(cfg, "podcast", None)
    fmt = str(getattr(podcast_cfg, "audio_format", "wav") or "wav") if podcast_cfg else "wav"
    # Piper helper attuale genera wav. Manteniamo coerenza.
    return "wav" if fmt.lower() != "wav" else "wav"


def _safe_stem(text: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "-", _normalize_text(text).lower()).strip("-")
    return stem[:60] or "podcast"


def _build_script_prompt(topic: str, *, lang: str, target_words: int) -> tuple[str, str]:
    if (lang or "").lower().startswith("it"):
        system_prompt = system_base_context("it")
        user_prompt = (
            "Scrivi un breve script per un podcast in italiano.\n"
            "\n"
            "Vincoli:\n"
            f"- argomento: {topic}\n"
            f"- lunghezza target: circa {target_words} parole\n"
            "- tono chiaro, naturale, informativo\n"
            "- niente introduzioni meta sul fatto che sei un AI\n"
            "- niente markdown\n"
            "- testo pronto per essere letto ad alta voce\n"
            "- chiudi con una conclusione breve\n"
        )
        return system_prompt, user_prompt

    system_prompt = system_base_context("en")
    user_prompt = (
        "Write a short podcast script in English.\n"
        "\n"
        "Constraints:\n"
        f"- topic: {topic}\n"
        f"- target length: around {target_words} words\n"
        "- clear, natural, informative tone\n"
        "- no meta commentary about being an AI\n"
        "- no markdown\n"
        "- text should be ready to be read aloud\n"
        "- end with a short conclusion\n"
    )
    return system_prompt, user_prompt


async def _call_status(status: StatusCb | None, text: str) -> None:
    if status is None:
        return
    await status(text)


async def generate_podcast(
    cfg,
    provider,
    *,
    topic: str,
    lang: str | None = None,
    minutes: int | None = None,
    status: StatusCb | None = None,
) -> PodcastResult:
    topic = _normalize_text(topic)
    if not topic:
        raise ValueError("podcast topic is empty")

    final_lang = _normalize_text(lang) or detect_language(topic, default="it")
    final_minutes = int(minutes or _default_minutes(cfg))
    target_words = _target_words(cfg, final_minutes)

    await _call_status(status, "📝 Sto scrivendo lo script del podcast…")

    system_prompt, user_prompt = _build_script_prompt(
        topic,
        lang=final_lang,
        target_words=target_words,
    )

    resp = await provider.chat(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        tools=None,
        max_tokens=1400,
        temperature=0.4,
    )

    script = _normalize_text(getattr(resp, "content", ""))
    if not script:
        raise RuntimeError("podcast script generation returned empty content")

    out_dir = _output_dir(cfg)
    fmt = _audio_format(cfg)
    stem = _safe_stem(topic)

    await _call_status(status, "🎤 Sto sintetizzando l'audio del podcast…")

    audio_path = await asyncio.to_thread(
        synthesize_speech,
        cfg,
        script,
        lang=final_lang,
        output_dir=out_dir,
        file_stem=stem,
        audio_format=fmt,
    )

    meta = {
        "topic": topic,
        "lang": final_lang,
        "minutes": final_minutes,
        "target_words": target_words,
        "audio_path": audio_path,
    }

    out_dir_path = Path(out_dir).expanduser().resolve()
    out_dir_path.mkdir(parents=True, exist_ok=True)

    script_path = out_dir_path / f"{stem}.txt"
    meta_path = out_dir_path / f"{stem}.meta.json"

    script_path.write_text(script, encoding="utf-8")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return PodcastResult(
        topic=topic,
        lang=final_lang,
        script=script,
        audio_path=audio_path,
    )
