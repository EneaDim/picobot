from __future__ import annotations

import json
import re

from picobot.routing.schemas import RouteCandidate, RouteDecision, SessionRouteContext
from picobot.runtime_config import cfg_get

_EXPLICIT_TOOL_RX = re.compile(
    r"^\s*tool\s+([a-zA-Z0-9_:-]+)\s+(\{.*\})\s*$",
    re.DOTALL,
)

_NEWS_COMMAND_RX = re.compile(r"^\s*/news(?:\s+.*)?$", re.IGNORECASE)
_PY_COMMAND_RX = re.compile(r"^\s*/py(?:thon)?\b", re.IGNORECASE)
_FILE_COMMAND_RX = re.compile(r"^\s*/file\b", re.IGNORECASE)
_FETCH_COMMAND_RX = re.compile(r"^\s*/fetch\b", re.IGNORECASE)
_KB_INGEST_COMMAND_RX = re.compile(r"^\s*/kb\s+ingest\b", re.IGNORECASE)
_PODCAST_COMMAND_RX = re.compile(r"^\s*/podcast\b", re.IGNORECASE)

_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)

_GREETING_RX = re.compile(
    r"^\s*(ciao|hey|hello|salve|ehi|buongiorno|buonasera|hi)\s*[.!?]?\s*$",
    re.IGNORECASE,
)

_TTS_INTENT_RX = re.compile(
    r"\b("
    r"tts|"
    r"text to speech|"
    r"voice output|"
    r"speech synthesis|"
    r"pronuncia|"
    r"leggi ad alta voce|"
    r"leggi questo testo|"
    r"converti .* audio|"
    r"genera .* audio|"
    r"trasforma .* audio|"
    r"voce|"
    r"audio"
    r")\b",
    re.IGNORECASE,
)

# pattern abbastanza conservativi: tts solo quando c'è testo reale da sintetizzare
_TTS_QUOTED_RX = re.compile(
    r'(?:"([^"]+)"|\'([^\']+)\')',
    re.DOTALL,
)

_TTS_COLON_RX = re.compile(
    r"\b(?:tts|pronuncia|leggi ad alta voce|leggi questo testo|converti(?: il)? testo in audio|genera audio(?: da)?|trasforma(?: il)? testo in audio)\b\s*:\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_TTS_INLINE_RX = re.compile(
    r"\b(?:leggi ad alta voce|pronuncia|tts)\b\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_TTS_BAD_PAYLOADS = {
    "",
    "questo",
    "questo testo",
    "il testo",
    "testo",
    "in audio",
    "audio",
}


_PYTHON_INTENT_RX = re.compile(
    r"\b("
    r"usa python|"
    r"esegui in python|"
    r"run in python|"
    r"python:"
    r")\b",
    re.IGNORECASE,
)

_PYTHON_COLON_RX = re.compile(
    r"\b(?:python)\s*:\s*(.+)$",
    re.IGNORECASE | re.DOTALL,
)

_PYTHON_INLINE_RX = re.compile(
    r"\b(?:usa python per|esegui in python|run in python)\b\s+(.+)$",
    re.IGNORECASE | re.DOTALL,
)


def _extract_explicit_tool(text: str) -> tuple[str, dict] | None:
    match = _EXPLICIT_TOOL_RX.match(text or "")
    if not match:
        return None

    tool_name = match.group(1).strip()
    raw_args = match.group(2).strip()

    try:
        data = json.loads(raw_args)
    except Exception:
        data = {}

    if not isinstance(data, dict):
        data = {}

    return tool_name, data


def _candidate_score(candidate: RouteCandidate) -> float:
    for attr in ("final_score", "score", "combined_score"):
        value = getattr(candidate, attr, None)
        if value is not None:
            try:
                return float(value)
            except Exception:
                pass
    return 0.0


def _looks_like_greeting(text: str) -> bool:
    return bool(_GREETING_RX.match(text or ""))


def _looks_like_tts_request(text: str) -> bool:
    return bool(_TTS_INTENT_RX.search(text or ""))


def _normalize_tts_text(text: str) -> str | None:
    value = " ".join((text or "").strip().split())
    if not value:
        return None
    if value.lower() in _TTS_BAD_PAYLOADS:
        return None
    return value


def _extract_tts_args(text: str) -> dict | None:
    raw = (text or "").strip()

    # 1) priorità al testo tra virgolette
    m = _TTS_QUOTED_RX.search(raw)
    if m:
        payload = m.group(1) or m.group(2) or ""
        payload = _normalize_tts_text(payload)
        if payload:
            return {"text": payload}

    # 2) pattern con ":" -> molto affidabile
    m = _TTS_COLON_RX.search(raw)
    if m:
        payload = _normalize_tts_text(m.group(1))
        if payload:
            return {"text": payload}

    # 3) pattern inline solo per forme veramente esplicite
    m = _TTS_INLINE_RX.search(raw)
    if m:
        payload = _normalize_tts_text(m.group(1))
        if payload:
            return {"text": payload}

    return None


def _looks_like_python_request(text: str) -> bool:
    return bool(_PYTHON_INTENT_RX.search(text or ""))


def _normalize_python_code(text: str) -> str | None:
    value = (text or "").strip()
    if not value:
        return None
    lowered = " ".join(value.lower().split())
    if lowered in {"python", "codice", "script", "usa python", "esegui in python"}:
        return None
    return value


def _extract_python_args(text: str) -> dict | None:
    raw = (text or "").strip()

    m = _PYTHON_COLON_RX.search(raw)
    if m:
        payload = _normalize_python_code(m.group(1))
        if payload:
            return {"code": payload}

    m = _PYTHON_INLINE_RX.search(raw)
    if m:
        payload = _normalize_python_code(m.group(1))
        if payload:
            return {"code": payload}

    return None


class RouterPolicy:
    def __init__(self) -> None:
        self.accept_threshold = float(cfg_get("router.accept_threshold", 0.52))
        self.margin = float(cfg_get("router.margin", 0.08))

    def _explicit_decision(self, text: str) -> RouteDecision | None:
        raw = text or ""
        stripped = raw.strip()

        if _looks_like_greeting(stripped):
            return RouteDecision(
                action="workflow",
                name="chat",
                reason="greeting fallback to chat",
                args={},
                score=1.0,
                candidates=[],
            )

        explicit_tool = _extract_explicit_tool(stripped)
        if explicit_tool is not None:
            tool_name, args = explicit_tool
            return RouteDecision(
                action="tool",
                name=tool_name,
                reason="explicit tool call",
                args=args,
                score=1.0,
                candidates=[],
            )

        if _NEWS_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="news_digest",
                reason="explicit /news command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _PY_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="python",
                reason="explicit /py command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _FILE_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="file",
                reason="explicit /file command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _FETCH_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="web",
                reason="explicit /fetch command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _KB_INGEST_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="kb_ingest_pdf",
                reason="explicit /kb ingest command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _PODCAST_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="podcast",
                reason="explicit /podcast command",
                args={},
                score=1.0,
                candidates=[],
            )

        if _YT_RX.search(stripped):
            return RouteDecision(
                action="workflow",
                name="youtube_summarizer",
                reason="youtube url detected",
                args={},
                score=1.0,
                candidates=[],
            )

        return None

    def _apply_constraints(
        self,
        user_text: str,
        candidates: list[RouteCandidate],
        ctx: SessionRouteContext,
    ) -> list[RouteCandidate]:
        out: list[RouteCandidate] = []

        for candidate in candidates:
            record = candidate.record

            if record.requires_kb and (not ctx.has_kb or not ctx.kb_enabled):
                continue

            # TTS eleggibile solo se l'intento è davvero presente
            if record.name == "tts" and not _looks_like_tts_request(user_text):
                continue

            if record.name == "python" and not _looks_like_python_request(user_text):
                continue

            out.append(candidate)

        return out

    def decide(
        self,
        *,
        user_text: str,
        candidates: list[RouteCandidate],
        ctx: SessionRouteContext,
    ) -> RouteDecision:
        explicit = self._explicit_decision(user_text)
        if explicit is not None:
            return explicit

        filtered = self._apply_constraints(user_text, candidates, ctx)

        if not filtered:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason="no eligible candidates",
                args={},
                score=0.0,
                candidates=[],
            )

        filtered = sorted(filtered, key=_candidate_score, reverse=True)
        top1 = filtered[0]
        top2 = filtered[1] if len(filtered) > 1 else None

        top1_score = _candidate_score(top1)
        top2_score = _candidate_score(top2) if top2 is not None else None

        if top1_score < self.accept_threshold:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason=f"top score below threshold ({top1_score:.3f} < {self.accept_threshold:.3f})",
                args={},
                score=top1_score,
                candidates=filtered,
            )

        if top2 is not None and top2_score is not None and (top1_score - top2_score) < self.margin:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason=f"ambiguous top candidates (margin {(top1_score - top2_score):.3f} < {self.margin:.3f})",
                args={},
                score=top1_score,
                candidates=filtered,
            )

        record = top1.record
        action = "tool" if record.kind == "tool" else "workflow"
        args: dict = {}

        # Se selezioniamo TTS ma non riusciamo a ricavare il testo,
        # meglio fallback a chat che chiamare il tool con args vuoti.
        if record.name == "tts":
            tts_args = _extract_tts_args(user_text)
            if not tts_args:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="tts intent detected but missing explicit text payload",
                    args={},
                    score=top1_score,
                    candidates=filtered,
                )
            args = tts_args

        if record.name == "python":
            py_args = _extract_python_args(user_text)
            if not py_args:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="python intent detected but missing explicit code payload",
                    args={},
                    score=top1_score,
                    candidates=filtered,
                )
            args = py_args

        return RouteDecision(
            action=action,
            name=record.name,
            reason=f"selected top candidate: {record.id}",
            args=args,
            score=top1_score,
            candidates=filtered,
        )
