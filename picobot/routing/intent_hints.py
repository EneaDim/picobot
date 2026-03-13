from __future__ import annotations

import re
import unicodedata


def _fold(text: str) -> str:
    t = "".join(
        ch for ch in unicodedata.normalize("NFKD", text or "")
        if not unicodedata.combining(ch)
    )
    t = t.lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


RECENCY_PATTERNS = [
    r"\blatest\b",
    r"\brecent\b",
    r"\bcurrent\b",
    r"\bnow\b",
    r"\btoday\b",
    r"\bthis week\b",
    r"\bwhat is happening\b",
    r"\bwhat's happening\b",
    r"\bwhat happened\b",
    r"\bupdates?\b",
    r"\bbreaking\b",
    r"\bultime notizie\b",
    r"\bultimi aggiornamenti\b",
    r"\baggiornamenti\b",
    r"\boggi\b",
    r"\badesso\b",
    r"\bin questo momento\b",
    r"\bche succede\b",
    r"\bcosa sta succedendo\b",
]

NEWS_PATTERNS = [
    r"\bnews\b",
    r"\bheadline\b",
    r"\bheadlines\b",
    r"\bsearch about\b",
    r"\bsearch news\b",
    r"\bnotizie\b",
    r"\bcerca notizie\b",
    r"\bultime\b",
]

CONFLICT_PATTERNS = [
    r"\bwar\b",
    r"\bconflict\b",
    r"\bcrisis\b",
    r"\battack\b",
    r"\battacks\b",
    r"\bmissile\b",
    r"\bmissiles\b",
    r"\binvasion\b",
    r"\bceasefire\b",
    r"\bguerra\b",
    r"\bconflitto\b",
    r"\bcrisi\b",
    r"\battacco\b",
    r"\battacchi\b",
    r"\binvasione\b",
    r"\bcessate il fuoco\b",
]

GEOPOLITICAL_TERMS = [
    "iran",
    "us",
    "u.s.",
    "usa",
    "united states",
    "america",
    "israel",
    "palestine",
    "gaza",
    "ukraine",
    "russia",
    "china",
    "taiwan",
    "syria",
    "lebanon",
    "yemen",
    "eu",
    "european union",
    "nato",
]


def looks_like_current_events_news(text: str) -> bool:
    t = _fold(text)
    if not t:
        return False

    score = 0

    if any(re.search(pat, t) for pat in RECENCY_PATTERNS):
        score += 2

    if any(re.search(pat, t) for pat in NEWS_PATTERNS):
        score += 2

    if any(re.search(pat, t) for pat in CONFLICT_PATTERNS):
        score += 1

    if sum(1 for term in GEOPOLITICAL_TERMS if term in t) >= 1:
        score += 1

    if ("what is happening" in t or "cosa sta succedendo" in t or "che succede" in t) and any(term in t for term in GEOPOLITICAL_TERMS):
        score += 2

    if ("search about" in t or "cerca" in t) and any(term in t for term in GEOPOLITICAL_TERMS):
        score += 2

    return score >= 3


def looks_like_personal_memory_query(text: str) -> bool:
    t = _fold(text)
    if not t:
        return False

    patterns = [
        r"\bricordati\b",
        r"\bremember that\b",
        r"\bti ho detto\b",
        r"\bi told you\b",
        r"\bqual e la parola chiave\b",
        r"\bwhat is the keyword\b",
        r"\bwhat's the keyword\b",
        r"\bqual e il mio\b",
        r"\bqual e la mia\b",
        r"\bwhat is my\b",
        r"\bwhats my\b",
        r"\bwhat's my\b",
        r"\bdo you remember\b",
        r"\bti ricordi\b",
        r"\bcosa ti ho detto\b",
        r"\bwhat did i tell you\b",
        r"\bcome mi chiamo\b",
        r"\bwhat is my name\b",
        r"\bchi sono\b",
        r"\bwho am i\b",
        r"\bil mio colore preferito\b",
        r"\bmy favorite color\b",
        r"\bla mia preferenza\b",
        r"\bmy preference\b",
        r"\bparola chiave\b",
        r"\bkeyword\b",
    ]
    return any(re.search(pat, t) for pat in patterns)


def looks_like_youtube_transcript_request(text: str) -> bool:
    t = _fold(text)
    if not t:
        return False

    patterns = [
        r"\byt transcript\b",
        r"\byoutube transcript\b",
        r"\bfull transcript\b",
        r"\braw transcript\b",
        r"\btrascrivi il video\b",
        r"\btrascrivi il video youtube\b",
        r"\btrascrizione youtube\b",
        r"\bdammi il transcript\b",
        r"\bdammi la trascrizione\b",
        r"\btranscribe the youtube video\b",
        r"\bget the transcript\b",
        r"\bshow the transcript\b",
    ]
    return any(re.search(pat, t) for pat in patterns)


def looks_like_youtube_summary_request(text: str) -> bool:
    t = _fold(text)
    if not t:
        return False

    patterns = [
        r"\byt summary\b",
        r"\byoutube summary\b",
        r"\bsummarize youtube\b",
        r"\bsummarize the youtube video\b",
        r"\briassumi youtube\b",
        r"\briassumi il video youtube\b",
        r"\briassunto youtube\b",
    ]
    return any(re.search(pat, t) for pat in patterns)

