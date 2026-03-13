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


NEWS_PATTERNS = [
    r"\blatest\b",
    r"\bnews\b",
    r"\bupdate\b",
    r"\bupdates\b",
    r"\bwhat is happening\b",
    r"\bwhat's happening\b",
    r"\bsearch about\b",
    r"\bsearch news\b",
    r"\bwar\b",
    r"\bconflict\b",
    r"\bcrisis\b",
    r"\bbreaking\b",
    r"\bultime notizie\b",
    r"\bnotizie\b",
    r"\baggiornamenti\b",
    r"\bguerra\b",
    r"\bconflitto\b",
    r"\bcerca notizie\b",
]

GEOPOLITICAL_TERMS = [
    "iran",
    "usa",
    "united states",
    "israel",
    "gaza",
    "ukraine",
    "russia",
    "china",
    "taiwan",
]


def looks_like_current_events_news(text: str) -> bool:
    t = _fold(text)
    if not t:
        return False

    score = 0
    for pat in NEWS_PATTERNS:
        if re.search(pat, t):
            score += 1

    for term in GEOPOLITICAL_TERMS:
        if term in t:
            score += 1

    return score >= 2
