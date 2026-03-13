from __future__ import annotations

import re
import unicodedata

from picobot.routing.intent_hints import (
    looks_like_current_events_news,
    looks_like_youtube_summary_request,
    looks_like_youtube_transcript_request,
)


def _ascii_fold(text: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(ch)
    )


def _clean(text: str) -> str:
    t = _ascii_fold(text or "").lower().strip()
    t = t.replace("pod cast", "podcast")
    t = t.replace("you tube", "youtube")
    t = re.sub(r"[“”\"'`]", "", t)
    t = re.sub(r"[^a-z0-9:/._?&=%+\-]+", " ", t)
    return " ".join(t.split())


def _strip_polite_prefixes(text: str) -> str:
    prefixes = [
        "please ",
        "per favore ",
        "can you ",
        "could you ",
        "would you ",
        "puoi ",
        "potresti ",
        "mi puoi ",
        "mi potresti ",
        "vorrei che ",
        "voglio che ",
    ]
    out = text
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if out.startswith(prefix):
                out = out[len(prefix):].strip()
                changed = True
    return out


def spoken_text_to_command(text: str) -> str | None:
    original = (text or "").strip()
    t = _strip_polite_prefixes(_clean(original))
    if not t:
        return None

    if t.startswith("/"):
        return original

    rules: list[tuple[re.Pattern[str], str | callable]] = [
        (re.compile(r"^(help|show help|open help|aiuto|mostra aiuto|mostrami l aiuto)$"), "/help"),
        (re.compile(r"^(status|show status|runtime status|stato|mostra stato|mostrami lo stato)$"), "/status"),
        (re.compile(r"^(tools|show tools|list tools|strumenti|mostra strumenti|mostrami gli strumenti)$"), "/tools"),
        (re.compile(r"^(mem|memory|show memory|mostra memoria)$"), "/mem"),
        (re.compile(r"^(mem clean|memory clean|clear memory|reset memory|pulisci memoria|cancella memoria|svuota memoria)$"), "/mem clean"),
        (re.compile(r"^(kb|knowledge base|show kb|mostra kb|mostra knowledge base)$"), "/kb"),

        (re.compile(r"^(session|show session|mostra sessione)$"), "/session"),
        (
            re.compile(r"^(switch session to|use session|change session to|cambia sessione a|usa sessione|passa alla sessione)\s+(.+)$"),
            lambda m: f"/session use {m.group(2).strip()}",
        ),

        (re.compile(r"^(news|latest news|recent news|notizie|ultime notizie|aggiornamenti)$"), "/news"),
        (
            re.compile(
                r"^(latest news on|latest news about|news on|news about|search about|search news about|what is happening in|whats happening in|what is going on in|notizie su|cerca notizie su|cerca su|ultime notizie su|cosa sta succedendo in|che succede in)\s+(.+)$"
            ),
            lambda m: f"/news {m.group(2).strip()}",
        ),

        (re.compile(r"^(podcast)\s+(.+)$"), lambda m: f"/podcast {m.group(2).strip()}"),
        (
            re.compile(
                r"^(generate a podcast about|make a podcast about|create a podcast about|produce a podcast about|generate podcast about|make podcast about|create podcast about)\s+(.+)$"
            ),
            lambda m: f"/podcast {m.group(2).strip()}",
        ),
        (
            re.compile(
                r"^(genera un podcast su|crea un podcast su|fammi un podcast su|fai un podcast su|voglio un podcast su|vorrei un podcast su)\s+(.+)$"
            ),
            lambda m: f"/podcast {m.group(2).strip()}",
        ),

        (
            re.compile(r"^(yt|youtube)\s+transcript\s+(.+)$"),
            lambda m: f"/yt transcript {m.group(2).strip()}",
        ),
        (
            re.compile(r"^(yt|youtube)\s+summary\s+(.+)$"),
            lambda m: f"/yt summary {m.group(2).strip()}",
        ),
        (
            re.compile(
                r"^(transcribe the youtube video|get the youtube transcript|show the youtube transcript|trascrivi il video youtube|dammi il transcript youtube|dammi la trascrizione youtube)\s+(.+)$"
            ),
            lambda m: f"/yt transcript {m.group(2).strip()}",
        ),
        (
            re.compile(
                r"^(summarize youtube|summarize the youtube video|summarize this youtube video|riassumi youtube|riassumi il video youtube|riassumi questo video youtube|riassumi il video su youtube)\s+(.+)$"
            ),
            lambda m: f"/yt summary {m.group(2).strip()}",
        ),
        (re.compile(r"^(youtube|yt)\s+(.+)$"), lambda m: f"/yt summary {m.group(2).strip()}"),

        (re.compile(r"^(fetch|open url|fetch url|apri url|scarica pagina|apri pagina)\s+(.+)$"),
         lambda m: f"/fetch {m.group(2).strip()}"),

        (re.compile(r"^(python|run python|execute python|esegui python)\s+(.+)$"),
         lambda m: f"/python {m.group(2).strip()}"),

        (re.compile(r"^(tts|text to speech|say|read aloud|leggi|di)\s+(.+)$"),
         lambda m: f"/tts {m.group(2).strip()}"),

        (re.compile(r"^(stt|speech to text|transcribe|trascrivi)\s+(.+)$"),
         lambda m: f"/stt {m.group(2).strip()}"),
    ]

    for pattern, target in rules:
        match = pattern.match(t)
        if not match:
            continue
        if callable(target):
            return str(target(match))
        return target

    if "youtube" in t or "youtu.be" in t or "youtube.com" in t:
        if looks_like_youtube_transcript_request(t):
            return f"/yt transcript {t}"
        if looks_like_youtube_summary_request(t):
            return f"/yt summary {t}"
        return f"/yt summary {t}"

    if looks_like_current_events_news(t):
        return f"/news {t}"

    return None
