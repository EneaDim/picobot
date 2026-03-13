from __future__ import annotations

import re
import unicodedata


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
    t = re.sub(r"[^a-z0-9:/._?&=%+-]+", " ", t)
    t = " ".join(t.split())
    return t


def _strip_polite_prefixes(text: str) -> str:
    prefixes = [
        "please ",
        "per favore ",
        "can you ",
        "could you ",
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
        for p in prefixes:
            if out.startswith(p):
                out = out[len(p):].strip()
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

        (re.compile(r"^(news|latest news|notizie|ultime notizie)$"), "/news"),
        (re.compile(r"^(news)\s+(.+)$"), lambda m: f"/news {m.group(2).strip()}"),
        (re.compile(r"^(latest news on|news about|search news about|notizie su|cerca notizie su|ultime notizie su)\s+(.+)$"),
         lambda m: f"/news {m.group(2).strip()}"),

        (re.compile(r"^(podcast)\s+(.+)$"), lambda m: f"/podcast {m.group(2).strip()}"),
        (re.compile(r"^(generate podcast about|make a podcast about|create a podcast about|create podcast about)\s+(.+)$"),
         lambda m: f"/podcast {m.group(2).strip()}"),
        (re.compile(r"^(genera un podcast su|crea un podcast su|fammi un podcast su|fai un podcast su)\s+(.+)$"),
         lambda m: f"/podcast {m.group(2).strip()}"),

        (re.compile(r"^(fetch|open url|fetch url|apri url|scarica pagina|apri pagina)\s+(.+)$"),
         lambda m: f"/fetch {m.group(2).strip()}"),

        (re.compile(r"^(python|run python|execute python|esegui python)\s+(.+)$"),
         lambda m: f"/python {m.group(2).strip()}"),

        (re.compile(r"^(tts|text to speech|say|read aloud|leggi|di)\s+(.+)$"),
         lambda m: f"/tts {m.group(2).strip()}"),

        (re.compile(r"^(stt|speech to text|transcribe|trascrivi)\s+(.+)$"),
         lambda m: f"/stt {m.group(2).strip()}"),

        (re.compile(r"^(youtube|yt)\s+(.+)$"),
         lambda m: f"/yt {m.group(2).strip()}"),
        (re.compile(r"^(summarize youtube|riassumi youtube|riassumi il video youtube|summarize the youtube video)\s+(.+)$"),
         lambda m: f"/yt {m.group(2).strip()}"),
    ]

    for pattern, target in rules:
        m = pattern.match(t)
        if not m:
            continue
        if callable(target):
            return str(target(m))
        return target

    return None
