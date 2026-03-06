from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Awaitable, Callable, Optional

from picobot.agent.prompts import (
    detect_language,
    podcast_script_system_prompt,
    podcast_script_user_prompt,
)
from picobot.tools.tts import synthesize_speech

StatusCb = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class PodcastResult:
    audio_path: str
    script: str
    run_dir: str


def _slug(s: str, max_len: int = 48) -> str:
    text = (s or "").strip().lower()
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[^a-z0-9_\-]+", "", text)
    text = text.strip("-_")
    return text[: max(12, int(max_len))] or "podcast"


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


def _norm_lang(lang: str | None, default: str = "it") -> str:
    value = (lang or "").strip().lower()
    if value.startswith("en"):
        return "en"
    if value.startswith("it"):
        return "it"
    fallback = (default or "it").strip().lower()
    return "en" if fallback.startswith("en") else "it"


def detect_podcast_request(text: str, cfg) -> Optional[tuple[str, str]]:
    raw = (text or "").strip()
    if not raw:
        return None

    pcfg = getattr(cfg, "podcast", None)
    if not pcfg or not getattr(pcfg, "enabled", False):
        return None

    default_lang = getattr(cfg, "default_language", "it")
    lang = detect_language(raw, default=default_lang)
    low = raw.lower()

    triggers = []
    try:
        tcfg = getattr(pcfg, "triggers", None)
        if tcfg:
            triggers = list(getattr(tcfg, lang) or [])
    except Exception:
        triggers = []

    for trig in triggers:
        t = (trig or "").strip().lower()
        if not t:
            continue
        if low.startswith(t):
            topic = raw[len(trig):].strip(" \t\r\n:,-")
            return (topic or "podcast", lang)

    if low.startswith("podcast"):
        topic = raw[len("podcast"):].strip(" \t\r\n:,-")
        return (topic or "podcast", lang)

    return None


def _workspace(cfg) -> Path:
    return Path(getattr(cfg, "workspace", ".picobot/workspace")).expanduser().resolve()


def _output_root(cfg) -> Path:
    out = str(getattr(getattr(cfg, "podcast", None), "output_dir", "") or "outputs/podcasts")
    path = Path(out).expanduser()
    if not path.is_absolute():
        path = (_workspace(cfg) / path).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_dir(cfg, topic: str) -> Path:
    run = _output_root(cfg) / f"{_utc_stamp()}_{_slug(topic)}"
    run.mkdir(parents=True, exist_ok=True)
    return run


async def _generate_script(cfg, provider, *, topic: str, lang: str) -> str:
    pcfg = getattr(cfg, "podcast", None)
    minutes = int(getattr(pcfg, "default_minutes", 1) or 1)
    max_minutes = int(getattr(pcfg, "max_minutes", 2) or 2)
    wpm = int(getattr(pcfg, "target_words_per_minute", 150) or 150)

    minutes = max(1, min(minutes, max(1, max_minutes)))

    response = await provider.chat(
        messages=[
            {"role": "system", "content": podcast_script_system_prompt(lang)},
            {"role": "user", "content": podcast_script_user_prompt(topic, lang, minutes, wpm)},
        ],
        tools=None,
        max_tokens=1200,
        temperature=0.3,
    )

    text = (response.content or "").strip()
    if not text:
        if lang == "it":
            text = f"Oggi parliamo di {topic}. In questo breve episodio vediamo i punti principali in modo semplice e concreto."
        else:
            text = f"Today we talk about {topic}. In this short episode we cover the main points in a simple and concrete way."

    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _write_artifacts(run_dir: Path, script: str, topic: str, lang: str) -> tuple[Path, Path]:
    script_path = run_dir / "script.txt"
    meta_path = run_dir / "meta.json"

    script_path.write_text(script, encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "topic": topic,
                "lang": lang,
                "script_path": str(script_path),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return script_path, meta_path


async def generate_podcast(
    cfg,
    provider,
    *,
    topic: str,
    lang: str | None = None,
    status: StatusCb | None = None,
) -> PodcastResult:
    raw_topic = (topic or "").strip() or "podcast"
    language = _norm_lang(lang, default=getattr(cfg, "default_language", "it"))

    if status:
        await status("📝 Sto scrivendo il copione…")

    run_dir = _run_dir(cfg, raw_topic)
    script = await _generate_script(cfg, provider, topic=raw_topic, lang=language)
    script_path, meta_path = _write_artifacts(run_dir, script, raw_topic, language)

    if status:
        await status("🔊 Sto sintetizzando l’audio…")

    tts_res = await synthesize_speech(
        cfg,
        text=script,
        lang=language,
        output_dir=run_dir,
        output_stem="podcast",
    )

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        meta = {}

    meta["audio_path"] = tts_res.audio_path
    meta["tts_backend"] = tts_res.backend
    meta["tts_ok"] = tts_res.ok
    meta["tts_detail"] = tts_res.detail
    meta["script_path"] = str(script_path)

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    return PodcastResult(
        audio_path=tts_res.audio_path,
        script=script,
        run_dir=str(run_dir),
    )
