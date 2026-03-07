from __future__ import annotations


def detect_language(text: str, default: str = "it") -> str:
    """
    Rilevatore minimale it/en.

    Non deve essere perfetto.
    Deve solo dare una scelta pratica e stabile.
    """
    raw = (text or "").strip().lower()
    if not raw:
        return "en" if str(default).lower().startswith("en") else "it"

    en_hits = sum(word in raw for word in [
        " the ", " and ", " what ", " how ", " why ", " summarize ",
        " summary ", " please ", " explain ", " podcast about ",
    ])
    it_hits = sum(word in raw for word in [
        " il ", " lo ", " la ", " gli ", " come ", " perché ",
        " riassumi ", " spiegami ", " voglio un podcast su ",
        " fammi un podcast su ",
    ])

    if raw.startswith("i want") or raw.startswith("make a podcast") or raw.startswith("summarize"):
        return "en"

    if raw.startswith("voglio") or raw.startswith("fammi") or raw.startswith("riassumi"):
        return "it"

    if en_hits > it_hits:
        return "en"
    return "it"
