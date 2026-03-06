from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

# =========================================================
# Language detection (NO LLM)
# =========================================================

_WORD_RX = re.compile(r"[a-zA-ZÀ-ÿ0-9_']+")
_ACCENT_RX = re.compile(r"[àèéìòù]", re.IGNORECASE)

_IT_HINTS = {
    "il", "lo", "la", "gli", "le",
    "un", "uno", "una",
    "che", "non", "per", "con", "come",
    "cosa", "quale", "quali",
    "voglio", "fammi", "puoi",
    "grazie", "perché",
    "senza", "sopra", "sotto",
    "dove", "quando",
}

_EN_HINTS = {
    "the", "a", "an",
    "and", "or", "with", "about",
    "what", "which", "who",
    "i", "want", "make",
    "please", "thanks", "why",
    "without", "above", "below",
    "where", "when",
}


def _norm_lang(lang: str | None, default: str = "it") -> str:
    lan = (lang or "").strip().lower()
    if lan.startswith("en"):
        return "en"
    if lan.startswith("it"):
        return "it"
    d = (default or "it").strip().lower()
    return "en" if d.startswith("en") else "it"


def detect_language(text: str, default: str = "it") -> str:
    t = (text or "").strip()
    if not t:
        return _norm_lang(None, default=default)

    low = t.lower()

    # Accents are a strong Italian signal
    if _ACCENT_RX.search(low):
        return "it"

    words = [m.group(0) for m in _WORD_RX.finditer(low)]
    if not words:
        return _norm_lang(None, default=default)

    it_score = 0
    en_score = 0

    for w in words[:80]:
        if w in _IT_HINTS:
            it_score += 2
        if w in _EN_HINTS:
            en_score += 2

    # Strong phrases
    padded = f" {low} "
    if " voglio " in padded:
        it_score += 3
    if " i want " in padded:
        en_score += 3

    if it_score == en_score:
        return _norm_lang(None, default=default)
    return "it" if it_score > en_score else "en"


# =========================================================
# Base system context (shared)
# =========================================================

def system_base_context(lang: str) -> str:
    lan = _norm_lang(lang)
    if lan == "it":
        return (
            "Sei picobot: assistente locale, leggero e deterministico.\n"
            "Regole:\n"
            "- Non inventare.\n"
            "- Se manca info critica, fai UNA domanda.\n"
            "- Risposte brevi (max 6–8 frasi).\n"
        )
    return (
        "You are picobot: local-first, lightweight, deterministic.\n"
        "Rules:\n"
        "- Do not invent.\n"
        "- If critical info is missing, ask ONE question.\n"
        "- Keep replies short (max 6–8 sentences).\n"
    )


def ping_reply(lang: str) -> str:
    return "Pong! Come posso aiutarti?" if _norm_lang(lang) == "it" else "Pong! How can I help?"


# =========================================================
# KB retrieval answer prompt (strict)
# =========================================================

def kb_user_prompt(lang: str, question: str, context: str) -> str:
    lan = _norm_lang(lang)
    q = (question or "").strip()
    ctx = (context or "").strip()
    if lan == "it":
        return (
            "Rispondi usando SOLO il CONTESTO DOCUMENTI.\n"
            "Se la risposta NON è nel contesto, rispondi esattamente: non trovato\n"
            "Massimo 6–8 frasi.\n\n"
            f"DOMANDA:\n{q}\n\n"
            f"CONTESTO DOCUMENTI:\n{ctx}\n"
        )
    return (
        "Answer using ONLY the DOCUMENT CONTEXT.\n"
        "If the answer is NOT in the context, reply exactly: not found\n"
        "Max 6–8 sentences.\n\n"
        f"QUESTION:\n{q}\n\n"
        f"DOCUMENT CONTEXT:\n{ctx}\n"
    )


# =========================================================
# YouTube summarizer prompts (strict, transcript language)
# =========================================================

def youtube_summarizer_system(lang: str | None = None) -> str:
    # Keep this extremely small to reduce model drift.
    lan = _norm_lang(lang)
    if lan == "it":
        return (
            "Riassumi transcript in modo fedele e conciso.\n"
            "Non aggiungere info non presenti.\n"
        )
    return (
        "Summarize transcripts faithfully and concisely.\n"
        "Do not add information not present.\n"
    )


def youtube_summarizer_user_prompt(transcript: str, url: str, lang: str, max_chars: int) -> str:
    lan = _norm_lang(lang)
    t = (transcript or "").strip()
    u = (url or "").strip()
    mc = max(500, int(max_chars))

    if lan == "it":
        return (
            f"URL: {u}\n"
            "Riassumi il transcript.\n"
            "Vincoli:\n"
            "- Max 6 punti elenco\n"
            f"- Max {mc} caratteri\n"
            "- Niente introduzione, niente conclusioni lunghe\n"
            "- Solo contenuti presenti nel transcript\n\n"
            f"TRANSCRIPT:\n{t}\n"
        )
    return (
        f"URL: {u}\n"
        "Summarize the transcript.\n"
        "Constraints:\n"
        "- Max 6 bullet points\n"
        f"- Max {mc} characters\n"
        "- No intro, no long outro\n"
        "- Only what is present in the transcript\n\n"
        f"TRANSCRIPT:\n{t}\n"
    )


# =========================================================
# Podcast prompts (dialogue-only, strict format)
# =========================================================

def podcast_system_prompt(lang: str, duration_s: int = 60) -> str:
    lan = _norm_lang(lang)
    dur = max(20, int(duration_s))
    if lan == "it":
        return (
            "Scrivi un copione podcast come SOLO dialogo.\n"
            "Formato obbligatorio (una riga per battuta):\n"
            "NARRATOR: ...\n"
            "EXPERT: ...\n"
            "Regole:\n"
            "- Output SOLO righe che iniziano con NARRATOR: o EXPERT:\n"
            "- Prima riga SEMPRE NARRATOR:\n"
            "- Usa ENTRAMBE le voci\n"
            "- Niente titoli, niente markdown, niente elenchi\n"
            f"- Durata target ~{dur}s (cap 2 minuti)\n"
        )
    return (
        "Write a short podcast script as pure dialogue.\n"
        "Required format (one line per turn):\n"
        "NARRATOR: ...\n"
        "EXPERT: ...\n"
        "Rules:\n"
        "- Output ONLY lines starting with NARRATOR: or EXPERT:\n"
        "- First line MUST be NARRATOR:\n"
        "- Use BOTH voices\n"
        "- No titles, no markdown, no bullet lists\n"
        f"- Target duration ~{dur}s (hard cap 2 minutes)\n"
    )


def podcast_user_prompt(lang: str, topic: str, duration_s: int = 60) -> str:
    lan = _norm_lang(lang)
    dur = max(20, int(duration_s))
    top = (topic or "").strip()
    if lan == "it":
        return (
            f"Argomento: {top}\n"
            f"Durata: ~{dur}s\n"
            "Scrivi ora il dialogo.\n"
        )
    return (
        f"Topic: {top}\n"
        f"Duration: ~{dur}s\n"
        "Write the dialogue now.\n"
    )


# =========================================================
# Generic compact prompts used by orchestrator (chat + tool result)
# =========================================================

@dataclass(frozen=True)
class PromptPack:
    lang: str  # 'it' | 'en'

    def orchestrator(self, user_input: str, tool_result: str | None = None) -> str:
        lan = _norm_lang(self.lang)
        ui = (user_input or "").strip()
        tr = (tool_result or "").strip()

        if lan == "it":
            head = (
                "Rispondi chiaro e conciso.\n"
                "Max 6–8 frasi.\n"
                "Se manca info critica: fai UNA domanda.\n"
            )
            if tr:
                return f"{head}\nRISULTATO TOOL:\n{tr}\n\nRICHIESTA:\n{ui}\n"
            return f"{head}\nRICHIESTA:\n{ui}\n"

        head = (
            "Answer clearly and concisely.\n"
            "Max 6–8 sentences.\n"
            "If critical info is missing: ask ONE question.\n"
        )
        if tr:
            return f"{head}\nTOOL RESULT:\n{tr}\n\nREQUEST:\n{ui}\n"
        return f"{head}\nREQUEST:\n{ui}\n"

    def summarizer(self, text: str, max_chars: int) -> str:
        lan = _norm_lang(self.lang)
        mc = max(200, int(max_chars))
        body = (text or "").strip()
        if lan == "it":
            return (
                "Riassumi in punti elenco.\n"
                f"Max {mc} caratteri.\n"
                "Niente premesse.\n\n"
                f"TESTO:\n{body}\n"
            )
        return (
            "Summarize in bullet points.\n"
            f"Max {mc} characters.\n"
            "No preface.\n\n"
            f"TEXT:\n{body}\n"
        )


# =========================================================
# Optional JSON tool protocol (kept for compatibility)
# =========================================================

def tool_protocol_system(tool_names: Iterable[str]) -> str:
    names = ", ".join([str(x) for x in tool_names if str(x).strip()])
    return (
        "You may either call a tool or answer.\n"
        "Output MUST be valid JSON, nothing else.\n"
        'Tool call: {"type":"tool","name":"TOOL_NAME","args":{...}}\n'
        'Final: {"type":"final","content":"..."}\n'
        f"Allowed TOOL_NAME: {names}\n"
    )


# =========================================================
# News summarizer prompts (for news_digest tool output)
# =========================================================

def news_summarizer_system(lang: str | None = None) -> str:
    l = _norm_lang(lang)
    if l == "it":
        return (
            "Sei un sintetizzatore di notizie.\n"
            "Non inventare. Se una fonte è vuota/errore, ignorala.\n"
            "Sii conciso.\n"
        )
    return (
        "You summarize news.\n"
        "Do not invent. Ignore empty/error sources.\n"
        "Be concise.\n"
    )







def news_summarizer_user_prompt(*, lang, query, items, max_bullets=7):
    blocks = []

    for idx, it in enumerate((items or [])[:10], start=1):
        if not isinstance(it, dict):
            continue
        if not it.get("ok"):
            continue

        title = (it.get("title") or "").strip()
        url = (it.get("final_url") or it.get("url") or "").strip()
        snippet = (it.get("snippet") or "").strip()
        description = (it.get("description") or "").strip()
        text = (it.get("text") or "").strip()

        blocks.append(
            f"""
ITEM {idx}
TITLE: {title}
URL: {url}
SNIPPET: {snippet}
DESCRIPTION: {description}
CONTENT:
{text}
"""
        )

    joined = "".join(blocks)

    return f"""
Requested language: {lang}
User query: {query}

Create a news digest from these sources.
Return ONLY valid JSON following the schema from the system prompt.

Sources:
{joined}
"""


def news_json_repair_system():
    return """
You repair malformed JSON.

Return ONLY valid JSON.
Do not use markdown.
Do not explain anything.
Follow exactly this schema:

{
  "items": [
    {
      "title": "string",
      "bullets": ["string", "string", "string"],
      "source_url": "string"
    }
  ]
}
"""



def news_json_repair_user_prompt(raw_text: str):
    return f"""
Convert the following text into VALID JSON following the required schema.
Keep the same meaning if possible.
Return ONLY JSON.

TEXT TO REPAIR:
{raw_text}
"""
