from __future__ import annotations

# Router policy minima e pulita.
#
# Questa è la parte "decisionale" finale.
# Deve fare poche cose, chiaramente:
#
# 1. riconoscere comandi/tool espliciti
# 2. applicare vincoli di capability (KB, rete)
# 3. applicare threshold + margin
# 4. fallback a chat se ambiguo o debole
#
# NON deve fare retrieval paralleli.
# NON deve correggere il router con logiche opache.
# NON deve diventare un secondo orchestrator.

import json
import re

from picobot.router.schemas import RouteCandidate, RouteDecision, SessionRouteContext
from picobot.runtime_config import cfg_get


# Regex per tool esplicito:
#   tool sandbox_python {"code":"print(2+2)"}
_EXPLICIT_TOOL_RX = re.compile(
    r"^\s*tool\s+([a-zA-Z0-9_:-]+)\s+(\{.*\})\s*$",
    re.DOTALL,
)

# Slash commands principali da preservare.
_NEWS_COMMAND_RX = re.compile(r"^\s*/news(?:\s+.*)?$", re.IGNORECASE)
_PY_COMMAND_RX = re.compile(r"^\s*/py(?:thon)?\b", re.IGNORECASE)
_FILE_COMMAND_RX = re.compile(r"^\s*/file\b", re.IGNORECASE)
_FETCH_COMMAND_RX = re.compile(r"^\s*/fetch\b", re.IGNORECASE)
_KB_INGEST_COMMAND_RX = re.compile(r"^\s*/kb\s+ingest\b", re.IGNORECASE)
_PODCAST_COMMAND_RX = re.compile(r"^\s*/podcast\b", re.IGNORECASE)

# URL YouTube.
_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)


def _extract_explicit_tool(text: str) -> tuple[str, dict] | None:
    """
    Estrae tool esplicito con args JSON, se presente.
    """
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


class RouterPolicy:
    """
    Policy finale del router.
    """

    def __init__(self) -> None:
        # Soglia minima sotto cui preferiamo chat.
        self.accept_threshold = float(cfg_get("router.accept_threshold", 0.52))

        # Margine minimo tra top1 e top2 per evitare false decisioni.
        self.margin = float(cfg_get("router.margin", 0.08))

    def _explicit_decision(self, text: str) -> RouteDecision | None:
        """
        Gestisce i comandi espliciti e i casi che NON devono passare
        dalla competizione semantica normale.
        """
        raw = text or ""
        stripped = raw.strip()

        # Tool esplicito "tool ... {...}".
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

        # Slash command /news ...
        if _NEWS_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="news_digest",
                reason="explicit /news command",
                args={},
                score=1.0,
                candidates=[],
            )

        # Slash command /py ...
        if _PY_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="sandbox_python",
                reason="explicit /py command",
                args={},
                score=1.0,
                candidates=[],
            )

        # Slash command /file ...
        if _FILE_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="sandbox_file",
                reason="explicit /file command",
                args={},
                score=1.0,
                candidates=[],
            )

        # Slash command /fetch ...
        if _FETCH_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="tool",
                name="sandbox_web",
                reason="explicit /fetch command",
                args={},
                score=1.0,
                candidates=[],
            )

        # Slash command /kb ingest ...
        if _KB_INGEST_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="kb_ingest_pdf",
                reason="explicit /kb ingest command",
                args={},
                score=1.0,
                candidates=[],
            )

        # Slash command /podcast ...
        if _PODCAST_COMMAND_RX.match(stripped):
            return RouteDecision(
                action="workflow",
                name="podcast",
                reason="explicit /podcast command",
                args={},
                score=1.0,
                candidates=[],
            )

        # URL YouTube => workflow diretto.
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
        candidates: list[RouteCandidate],
        ctx: SessionRouteContext,
    ) -> list[RouteCandidate]:
        """
        Applica i vincoli hard di capability.

        Regole:
        - una route che richiede KB non è eligibile se KB non c'è o è disabilitata
        - una route che richiede rete per ora resta eligibile;
          la disabilitazione rete verrà gestita più avanti dal config/orchestrator
        """
        out: list[RouteCandidate] = []

        for candidate in candidates:
            record = candidate.record

            if record.requires_kb and (not ctx.has_kb or not ctx.kb_enabled):
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
        """
        Decisione finale del router.
        """
        # 1. prima i comandi espliciti
        explicit = self._explicit_decision(user_text)
        if explicit is not None:
            return explicit

        # 2. poi i candidati filtrati per capability
        filtered = self._apply_constraints(candidates, ctx)

        if not filtered:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason="no eligible route candidates",
                args={},
                score=0.0,
                candidates=[],
            )

        top = filtered[0]
        second = filtered[1] if len(filtered) > 1 else None

        # 3. ambiguità top1 vs top2
        if second is not None:
            gap = float(top.final_score) - float(second.final_score)
            if gap < self.margin:
                return RouteDecision(
                    action="workflow",
                    name="chat",
                    reason="ambiguous top candidates",
                    args={},
                    score=float(top.final_score),
                    candidates=filtered,
                )

        # 4. confidenza insufficiente
        if float(top.final_score) < self.accept_threshold:
            return RouteDecision(
                action="workflow",
                name="chat",
                reason="low confidence",
                args={},
                score=float(top.final_score),
                candidates=filtered,
            )

        # 5. dispatch coerente col tipo
        if top.record.kind == "tool":
            return RouteDecision(
                action="tool",
                name=top.record.name,
                reason=f"semantic route: {top.record.name}",
                args={},
                score=float(top.final_score),
                candidates=filtered,
            )

        return RouteDecision(
            action="workflow",
            name=top.record.name,
            reason=f"semantic route: {top.record.name}",
            args={},
            score=float(top.final_score),
            candidates=filtered,
        )
