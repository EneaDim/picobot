from __future__ import annotations

import json
import re
from urllib.parse import urlparse

from picobot.routing.schemas import RouteCandidate, RouteDecision, SessionRouteContext
from picobot.runtime_config import cfg_get

_EXPLICIT_TOOL_RX = re.compile(
    r"^\s*tool\s+([a-zA-Z0-9_:-]+)\s+(\{.*\})\s*$",
    re.DOTALL,
)

_NEWS_COMMAND_RX = re.compile(r"^\s*/news(?:\s+.*)?$", re.IGNORECASE)
_PY_COMMAND_RX = re.compile(r"^\s*/py(?:thon)?\b(?:\s+(?P<code>.+))?$", re.IGNORECASE | re.DOTALL)
_FILE_COMMAND_RX = re.compile(r"^\s*/file\b(?:\s+(?P<path>.+))?$", re.IGNORECASE | re.DOTALL)
_FETCH_COMMAND_RX = re.compile(r"^\s*/fetch\b(?:\s+(?P<target>.+))?$", re.IGNORECASE | re.DOTALL)
_STT_COMMAND_RX = re.compile(r"^\s*/stt\b(?:\s+(?P<audio_path>.+))?$", re.IGNORECASE | re.DOTALL)
_TTS_COMMAND_RX = re.compile(r"^\s*/tts\b(?:\s+(?P<text>.+))?$", re.IGNORECASE | re.DOTALL)
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

_TTS_QUOTED_RX = re.compile(r"(?:\"([^\"]+)\"|'([^']+)')", re.DOTALL)

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

_STT_INTENT_RX = re.compile(
    r"\b("
    r"stt|"
    r"speech to text|"
    r"trascrivi|"
    r"trascrizione|"
    r"transcribe|"
    r"transcription|"
    r"voice note|"
    r"audio file|"
    r"messaggio vocale"
    r")\b",
    re.IGNORECASE,
)

_AUDIO_PATH_RX = re.compile(
    r"(?P<path>(?:[A-Za-z]:[\\/]|/|\.{1,2}/|~?/)?[^\s\"']+\.(?:wav|mp3|m4a|ogg|opus|flac|aac|mp4|mpeg|mpga))",
    re.IGNORECASE,
)

_TEXT_GEN_RX = re.compile(
    r"\b("
    r"write|"
    r"scrivi|"
    r"explain|"
    r"spiega|"
    r"show me|"
    r"fammi|"
    r"dammi|"
    r"generate|"
    r"genera|"
    r"create|"
    r"crea|"
    r"draft|"
    r"command|"
    r"terminal command|"
    r"bash command|"
    r"shell command|"
    r"cat command|"
    r"markdown|"
    r"script|"
    r"snippet|"
    r"code"
    r")\b",
    re.IGNORECASE,
)

_QUESTION_LIKE_RX = re.compile(
    r"^\s*("
    r"chi\b|"
    r"che\b|"
    r"cosa\b|"
    r"qual\b|"
    r"quale\b|"
    r"quali\b|"
    r"quando\b|"
    r"dove\b|"
    r"come\b|"
    r"perché\b|"
    r"perche\b|"
    r"in quale\b|"
    r"come si chiama\b|"
    r"what\b|"
    r"which\b|"
    r"where\b|"
    r"when\b|"
    r"why\b|"
    r"how\b"
    r")",
    re.IGNORECASE,
)

_KB_QUERY_HINT_RX = re.compile(
    r"\b("
    r"kb|"
    r"knowledge base|"
    r"cerca nella kb|"
    r"search the kb|"
    r"nel documento|"
    r"nel doc|"
    r"documento|"
    r"documentazione|"
    r"from the document"
    r")\b",
    re.IGNORECASE,
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


def _candidate_score(candidate: RouteCandidate | None) -> float:
    if candidate is None:
        return 0.0
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

    m = _TTS_QUOTED_RX.search(raw)
    if m:
        payload = m.group(1) or m.group(2) or ""
        payload = _normalize_tts_text(payload)
        if payload:
            return {"text": payload}

    m = _TTS_COLON_RX.search(raw)
    if m:
        payload = _normalize_tts_text(m.group(1))
        if payload:
            return {"text": payload}

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


def _looks_like_stt_request(text: str) -> bool:
    return bool(_STT_INTENT_RX.search(text or ""))


def _extract_stt_args(text: str) -> dict | None:
    raw = (text or "").strip()
    if not _looks_like_stt_request(raw):
        return None

    match = _AUDIO_PATH_RX.search(raw)
    if not match:
        return None

    path = str(match.group("path") or "").strip()
    if not path:
        return None

    return {"audio_path": path}


def _looks_like_text_generation_request(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_TEXT_GEN_RX.search(raw))


def _looks_like_kb_question(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    if "?" in raw:
        return True
    return bool(_QUESTION_LIKE_RX.search(raw))


def _looks_like_kb_query_request(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_KB_QUERY_HINT_RX.search(raw))


def _extract_python_slash_args(text: str) -> dict | None:
    match = _PY_COMMAND_RX.match((text or "").strip())
    if not match:
        return None
    code = _normalize_python_code(match.group("code") or "")
    return {"code": code} if code else None


def _extract_tts_slash_args(text: str) -> dict | None:
    match = _TTS_COMMAND_RX.match((text or "").strip())
    if not match:
        return None
    payload = _normalize_tts_text(match.group("text") or "")
    return {"text": payload} if payload else None


def _extract_stt_slash_args(text: str) -> dict | None:
    match = _STT_COMMAND_RX.match((text or "").strip())
    if not match:
        return None
    payload = str(match.group("audio_path") or "").strip()
    if not payload:
        return None
    return {"audio_path": payload}


def _extract_file_slash_args(text: str) -> dict | None:
    match = _FILE_COMMAND_RX.match((text or "").strip())
    if not match:
        return None
    payload = str(match.group("path") or "").strip()
    if not payload:
        return None
    return {"path": payload}


def _extract_fetch_slash_args(text: str) -> dict | None:
    match = _FETCH_COMMAND_RX.match((text or "").strip())
    if not match:
        return None
    payload = str(match.group("target") or "").strip()
    if not payload:
        return None

    parsed = urlparse(payload)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return {"operation": "fetch", "url": payload}

    return {"operation": "search", "query": payload}


def _best_candidate_by_name(candidates: list[RouteCandidate], name: str) -> RouteCandidate | None:
    best: RouteCandidate | None = None
    best_score = -1.0
    for candidate in candidates:
        if candidate.record.name != name:
            continue
        score = _candidate_score(candidate)
        if score > best_score:
            best = candidate
            best_score = score
    return best


class RouterPolicy:
    def __init__(self) -> None:
        self.accept_threshold = float(cfg_get("router.accept_threshold", 0.52))
        self.margin = float(cfg_get("router.margin", 0.08))
        self.kb_probe_threshold = float(cfg_get("router.kb_probe_threshold", 0.55))

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
            py_args = _extract_python_slash_args(stripped)
            if py_args is None:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="explicit /py command missing code payload",
                    args={},
                    score=1.0,
                    candidates=[],
                )
            return RouteDecision(
                action="tool",
                name="python",
                reason="explicit /py command",
                args=py_args,
                score=1.0,
                candidates=[],
            )

        if _FILE_COMMAND_RX.match(stripped):
            file_args = _extract_file_slash_args(stripped)
            if file_args is None:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="explicit /file command missing path payload",
                    args={},
                    score=1.0,
                    candidates=[],
                )
            return RouteDecision(
                action="tool",
                name="file",
                reason="explicit /file command",
                args=file_args,
                score=1.0,
                candidates=[],
            )

        if _FETCH_COMMAND_RX.match(stripped):
            fetch_args = _extract_fetch_slash_args(stripped)
            if fetch_args is None:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="explicit /fetch command missing target payload",
                    args={},
                    score=1.0,
                    candidates=[],
                )
            return RouteDecision(
                action="tool",
                name="web",
                reason="explicit /fetch command",
                args=fetch_args,
                score=1.0,
                candidates=[],
            )

        if _STT_COMMAND_RX.match(stripped):
            stt_args = _extract_stt_slash_args(stripped)
            if stt_args is None:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="explicit /stt command missing audio_path payload",
                    args={},
                    score=1.0,
                    candidates=[],
                )
            return RouteDecision(
                action="tool",
                name="stt",
                reason="explicit /stt command",
                args=stt_args,
                score=1.0,
                candidates=[],
            )

        if _TTS_COMMAND_RX.match(stripped):
            tts_args = _extract_tts_slash_args(stripped)
            if tts_args is None:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="explicit /tts command missing text payload",
                    args={},
                    score=1.0,
                    candidates=[],
                )
            return RouteDecision(
                action="tool",
                name="tts",
                reason="explicit /tts command",
                args=tts_args,
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
        text_generation_request = _looks_like_text_generation_request(user_text)

        for candidate in candidates:
            record = candidate.record

            if record.requires_kb and (not ctx.has_kb or not ctx.kb_enabled):
                continue

            if record.name == "kb_query" and not (
                _looks_like_kb_query_request(user_text)
                or (ctx.has_kb and ctx.kb_enabled and _looks_like_kb_question(user_text))
            ):
                continue

            if text_generation_request and record.kind == "tool":
                if record.name == "python" and _looks_like_python_request(user_text):
                    pass
                else:
                    continue

            if record.name == "tts" and not _looks_like_tts_request(user_text):
                continue

            if record.name == "python" and not _looks_like_python_request(user_text):
                continue

            if record.name == "youtube_summarizer" and not _YT_RX.search(user_text or ""):
                continue

            if record.name == "stt":
                if not _looks_like_stt_request(user_text):
                    continue
                if _extract_stt_args(user_text) is None:
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
        filtered = sorted(filtered, key=_candidate_score, reverse=True)

        if ctx.has_kb and ctx.kb_enabled and _looks_like_kb_question(user_text):
            kb_candidate = _best_candidate_by_name(filtered, "kb_query")
            kb_score = _candidate_score(kb_candidate)
            if kb_candidate is not None and kb_score >= self.kb_probe_threshold:
                return RouteDecision(
                    action="workflow",
                    name="kb_query",
                    reason=f"active kb question above kb threshold ({kb_score:.3f} >= {self.kb_probe_threshold:.3f})",
                    args={},
                    score=kb_score,
                    candidates=filtered,
                )

        if not filtered:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason="no eligible candidates",
                args={},
                score=0.0,
                candidates=[],
            )

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

        if record.name == "stt":
            stt_args = _extract_stt_args(user_text)
            if not stt_args:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="stt intent detected but missing audio_path payload",
                    args={},
                    score=top1_score,
                    candidates=filtered,
                )
            args = stt_args

        return RouteDecision(
            action=action,
            name=record.name,
            reason=f"selected top candidate: {record.id}",
            args=args,
            score=top1_score,
            candidates=filtered,
        )
