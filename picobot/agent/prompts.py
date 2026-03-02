from __future__ import annotations

import re
from dataclasses import dataclass


_WORD_RX = re.compile(r"[a-zA-ZÀ-ÿ0-9_']+")
_ACCENT_RX = re.compile(r"[àèéìòù]", re.IGNORECASE)

_IT_HINTS = {
    "il", "lo", "la", "gli", "le", "un", "uno", "una",
    "che", "non", "per", "con", "come", "cosa", "quale", "quali",
    "voglio", "fammi", "puoi", "podcast", "grazie",
    "perché", "anche", "senza", "sopra", "sotto", "dove", "quando",
}
_EN_HINTS = {
    "the", "a", "an", "and", "or", "with", "about", "what", "which", "who",
    "i", "want", "make", "podcast", "please", "thanks",
    "why", "also", "without", "above", "below", "where", "when",
}


def detect_language(text: str, default: str = "it") -> str:
    t = (text or "").strip()
    if not t:
        return "it" if (default or "it").lower().startswith("it") else "en"

    low = t.lower()

    if _ACCENT_RX.search(low):
        return "it"

    words = [m.group(0) for m in _WORD_RX.finditer(low)]
    if not words:
        return "it" if (default or "it").lower().startswith("it") else "en"

    it_score = 0
    en_score = 0

    for w in words[:80]:
        if w in _IT_HINTS:
            it_score += 2
        if w in _EN_HINTS:
            en_score += 2

    if " voglio " in f" {low} ":
        it_score += 3
    if " i want " in f" {low} ":
        en_score += 3

    if it_score == en_score:
        return "it" if (default or "it").lower().startswith("it") else "en"
    return "it" if it_score > en_score else "en"


@dataclass(frozen=True)
class PromptPack:
    lang: str  # 'it' | 'en'

    def router(self, user_input: str) -> str:
        if self.lang == "it":
            return (
                "Sei un router. Decidi: tool o chat.\n"
                "Output SOLO JSON in una riga:\n"
                "{\"route\":\"tool|chat\",\"tool_name\":\"...\",\"args\":{...}}\n"
                "Regole: azione/recupero -> tool; altrimenti chat. args solo validi.\n"
                f"Richiesta:\n{user_input}"
            )
        return (
            "You are a router. Decide: tool or chat.\n"
            "Output ONLY one-line JSON:\n"
            "{\"route\":\"tool|chat\",\"tool_name\":\"...\",\"args\":{...}}\n"
            "Rules: action/retrieval -> tool; otherwise chat. args only valid.\n"
            f"Request:\n{user_input}"
        )

    def orchestrator(self, user_input: str, tool_result: str | None = None) -> str:
        tool_result = (tool_result or "").strip()
        if self.lang == "it":
            head = "Rispondi chiaro e conciso. Max 8 frasi. Se manca info critica: UNA domanda."
            if tool_result:
                return f"{head}\n\nRisultato tool:\n{tool_result}\n\nRichiesta:\n{user_input}"
            return f"{head}\n\nRichiesta:\n{user_input}"
        head = "Answer clearly and concisely. Max 8 sentences. If critical info is missing: ask ONE question."
        if tool_result:
            return f"{head}\n\nTool result:\n{tool_result}\n\nRequest:\n{user_input}"
        return f"{head}\n\nRequest:\n{user_input}"

    def summarizer(self, text: str, max_chars: int) -> str:
        mc = int(max_chars)
        if self.lang == "it":
            return (
                f"Riassumi in punti elenco. Max {mc} caratteri.\n"
                "Niente premesse.\n\n"
                f"Testo:\n{text}"
            )
        return (
            f"Summarize in bullet points. Max {mc} characters.\n"
            "No preface.\n\n"
            f"Text:\n{text}"
        )

    def podcast_writer(self, topic: str, target_words: int, hard_cap_words: int = 300) -> str:
        tw = max(90, int(target_words))
        cap = max(120, int(hard_cap_words))

        if self.lang == "it":
            return (
                "Scrivi un dialogo REALISTICO per un podcast. SOLO dialogo.\n"
                "Scrivi SOLO in ITALIANO.\n"
                f"Target ~{tw} parole. HARD CAP {cap} parole.\n"
                "Output: SOLO righe che iniziano con NARRATOR: o EXPERT:.\n"
                "INIZIA SUBITO col dialogo: nessuna introduzione/meta (vietato: 'Ecco...', 'Ecco il dialogo', 'Oggi abbiamo').\n"
                "Niente liste, niente markdown, niente parentesi quadre.\n"
                "Stile: conversazione naturale. Se ci sono nomi/fatti dubbi, l'EXPERT lo dice e resta prudente.\n"
                "Vincoli: 8-14 battute, ogni battuta 1-2 frasi, alterna spesso.\n"
                "Divieti: 'Ecco', 'punti chiave', placeholder, '...'.\n"
                f"Tema: {topic}"
            )

        return (
            "Write a REALISTIC podcast dialogue. Dialogue ONLY.\n"
            "Write ONLY in ENGLISH.\n"
            f"Target ~{tw} words. HARD CAP {cap} words.\n"
            "Output: ONLY lines starting with NARRATOR: or EXPERT:.\n"
            "START IMMEDIATELY with dialogue: no meta/preface (forbidden: 'Here is...', 'Today we have').\n"
            "No lists, no markdown, no bracket tags.\n"
            "Style: natural conversation. If facts/names are doubtful, the EXPERT must say so and be cautious.\n"
            "Constraints: 8-14 turns, 1-2 sentences per turn, alternate often.\n"
            "Avoid: 'Here are key points', placeholders, '...'.\n"
            f"Topic: {topic}"
        )


def system_base_context(lang: str) -> str:
    if lang == "it":
        return (
            "Sei picobot (assistente leggero e deterministico). "
            "Usa la memoria di sessione solo per continuità. Non inventare."
        )
    return (
        "You are picobot (lightweight and deterministic). "
        "Use session memory only for continuity. Do not invent."
    )


def kb_user_prompt(lang: str, question: str, context: str) -> str:
    if lang == "it":
        return (
            "Rispondi usando SOLO il CONTESTO DOCUMENTI. "
            "Se la risposta non è nel contesto, scrivi: 'non trovato'.\n\n"
            f"DOMANDA:\n{question}\n\nCONTESTO DOCUMENTI:\n{context}"
        )
    return (
        "Answer using ONLY DOCUMENT CONTEXT. "
        "If the answer is not in the context, write: 'not found'.\n\n"
        f"QUESTION:\n{question}\n\nDOCUMENT CONTEXT:\n{context}"
    )
