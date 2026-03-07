from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from picobot.agent.memory import make_memory_manager
from picobot.agent.prompts import detect_language, kb_user_prompt, system_base_context
from picobot.agent.router import deterministic_route
from picobot.config.schema import Config
from picobot.providers.ollama import OllamaProvider, OllamaProviderError, OllamaTimeout
from picobot.session.manager import Session
from picobot.tools.base import ToolError
from picobot.tools.news_digest import NewsDigestArgs, make_news_digest_tool
from picobot.tools.podcast import detect_podcast_request, generate_podcast
from picobot.tools.registry import ToolRegistry
from picobot.tools.retrieval import make_kb_ingest_pdf_tool, make_kb_query_tool
from picobot.tools.sandbox_file import make_sandbox_file_tool
from picobot.tools.sandbox_python import make_sandbox_python_tool
from picobot.tools.sandbox_web import make_sandbox_web_tool
from picobot.tools.stt import make_stt_tool
from picobot.tools.tts import make_tts_tool
from picobot.tools.web_search import make_web_search_tool
from picobot.tools.youtube import YTSummaryArgs, make_yt_summary_tool, make_yt_transcript_tool

StatusCb = Callable[[str], Awaitable[None]]
_YT_RX = re.compile(r"(https?://\S*(youtube\.com|youtu\.be)\S*)", re.IGNORECASE)


def _first_youtube_url(text: str) -> str | None:
    match = _YT_RX.search(text or "")
    if not match:
        return None
    return match.group(1).strip()


@dataclass(slots=True)
class TurnResult:
    content: str
    action: str
    reason: str
    score: float = 0.0
    retrieval_hits: int = 0
    audio_path: str | None = None
    script: str | None = None


class Orchestrator:
    def __init__(self, cfg: Config, provider: OllamaProvider, workspace: Path) -> None:
        self.cfg = cfg
        self.provider = provider
        self.workspace = Path(workspace).expanduser().resolve()
        self.docs_root = self.workspace / "docs"
        self.docs_root.mkdir(parents=True, exist_ok=True)
        self.tools = ToolRegistry()
        self._register_tools()

    def _register_tools(self) -> None:
        if self.tools.list():
            return

        ytdlp_bin = str(getattr(self.cfg.tools, "ytdlp_bin", "") or "")
        ytdlp_args = list(getattr(self.cfg.tools, "ytdlp_args", []) or [])

        async def _llm_summarize(transcript: str, url: str, lang: str | None) -> str:
            lan = detect_language(transcript or url, default=self.cfg.default_language)
            sys_prompt = system_base_context(lan)
            user_prompt = (
                f"URL: {url}\n\n"
                f"Please summarize the YouTube video transcript below in a structured way.\n\n"
                f"Transcript:\n{transcript[:120000]}"
            )
            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                tools=None,
                max_tokens=900,
                temperature=0.1,
            )
            return (resp.content or "").strip()

        tool_specs = [
            make_kb_ingest_pdf_tool(self.docs_root),
            make_kb_query_tool(self.docs_root),
            make_sandbox_python_tool(),
            make_sandbox_file_tool(),
            make_sandbox_web_tool(self.cfg),
            make_web_search_tool(self.cfg, self.workspace),
            make_news_digest_tool(self.cfg, self.workspace),
            make_yt_transcript_tool(ytdlp_bin, ytdlp_args=ytdlp_args),
            make_yt_summary_tool(ytdlp_bin, _llm_summarize, ytdlp_args=ytdlp_args),
            make_stt_tool(self.cfg),
            make_tts_tool(self.cfg),
        ]

        for spec in tool_specs:
            self.tools.register(spec)

    def _memory_context(self, session: Session) -> str:
        mm = make_memory_manager(self.cfg, session, self.workspace)
        mem = mm.read_memory().strip()
        summ = mm.read_summary().strip()
        hist = mm.read_history_tail(self.cfg.memory_limits.tail_lines).strip()

        parts: list[str] = []
        if mem and mem != "# Memory":
            parts.append("SESSION MEMORY:\n" + mem)
        if summ and summ != "# Session Summary":
            parts.append("SESSION SUMMARY:\n" + summ)
        if hist and hist != "# Session History":
            parts.append("RECENT HISTORY:\n" + hist)

        return "\n\n".join(parts).strip()

    def _append_turn_memory(self, session: Session, user_text: str, assistant_text: str) -> None:
        mm = make_memory_manager(self.cfg, session, self.workspace)
        mm.init_files()
        mm.append_turn("user", user_text)
        mm.append_turn("assistant", assistant_text)

    def _store_audio_state(self, session: Session, audio_path: str | None) -> None:
        """
        Salva l'ultimo audio prodotto, se presente.
        """
        if audio_path and str(audio_path).strip():
            session.set_state({"last_audio_path": str(audio_path).strip()})

    async def _run_tool(self, tool_name: str, args: dict[str, Any]) -> dict:
        resolved = self.tools.resolve_name(tool_name)
        tool = self.tools.get(resolved)
        model = tool.validate(args or {})
        return await tool.handler(model)

    async def _run_explicit_tool(
        self,
        *,
        session: Session,
        lang: str,
        tool_name: str,
        args: dict[str, Any],
    ) -> TurnResult:
        try:
            result = await self._run_tool(tool_name, args)
        except KeyError:
            return TurnResult(
                content=(f"Tool sconosciuto: {tool_name}" if lang == "it" else f"Unknown tool: {tool_name}"),
                action="tool",
                reason="unknown tool",
            )
        except ToolError as e:
            return TurnResult(
                content=(f"Errore tool: {e}" if lang == "it" else f"Tool error: {e}"),
                action="tool",
                reason="tool validation error",
            )
        except Exception as e:
            return TurnResult(
                content=(f"Errore durante l'esecuzione del tool: {e}" if lang == "it" else f"Tool execution error: {e}"),
                action="tool",
                reason="tool execution error",
            )

        if not isinstance(result, dict):
            return TurnResult(
                content=(f"Risposta tool non valida da {tool_name}" if lang == "it" else f"Invalid tool response from {tool_name}"),
                action="tool",
                reason="invalid tool response",
            )

        if not result.get("ok"):
            err = str(result.get("error") or "tool failed")
            return TurnResult(
                content=(f"Tool fallito: {err}" if lang == "it" else f"Tool failed: {err}"),
                action="tool",
                reason="tool returned error",
            )

        data = result.get("data") or {}
        audio_path = str(data.get("audio_path") or "").strip() or None
        self._store_audio_state(session, audio_path)

        pretty = json.dumps(data, ensure_ascii=False, indent=2)

        return TurnResult(
            content=pretty,
            action="tool",
            reason=f"tool:{tool_name}",
            audio_path=audio_path,
        )

    async def _chat(self, *, session: Session, user_text: str, lang: str, status: StatusCb | None) -> TurnResult:
        if status:
            await status("💭 Sto pensando…")

        sys_prompt = system_base_context(lang)
        mem_ctx = self._memory_context(session)

        messages = [
            {"role": "system", "content": sys_prompt + ("\n\n" + mem_ctx if mem_ctx else "")},
            {"role": "user", "content": user_text},
        ]

        try:
            resp = await self.provider.chat(
                messages=messages,
                tools=None,
                max_tokens=900,
                temperature=0.2,
            )
        except OllamaTimeout:
            return TurnResult(
                content=("⏱️ Il modello locale non ha risposto in tempo." if lang == "it" else "⏱️ The local model timed out."),
                action="chat",
                reason="ollama timeout",
            )
        except OllamaProviderError as e:
            return TurnResult(
                content=(f"⚠️ Errore Ollama: {e}" if lang == "it" else f"⚠️ Ollama error: {e}"),
                action="chat",
                reason="ollama error",
            )

        content = (resp.content or "").strip() or ("Nessuna risposta." if lang == "it" else "No response.")
        return TurnResult(content=content, action="chat", reason="chat")

    async def _workflow_kb_query(self, *, session: Session, user_text: str, lang: str, status: StatusCb | None) -> TurnResult:
        kb_name = str(session.get_state().get("kb_name") or self.cfg.default_kb_name or "default").strip()
        top_k = int(getattr(self.cfg.retrieval, "top_k", 4) or 4)

        if status:
            await status("🔎 Cerco nella knowledge base…")

        try:
            tool_res = await self._run_tool(
                "kb_query",
                {"kb_name": kb_name, "query": user_text, "top_k": top_k},
            )
        except Exception as e:
            return TurnResult(
                content=(f"Errore retrieval: {e}" if lang == "it" else f"Retrieval error: {e}"),
                action="workflow",
                reason="kb tool execution error",
            )

        if not tool_res.get("ok"):
            err = str(tool_res.get("error") or "kb_query failed")
            return TurnResult(
                content=(f"KB query fallita: {err}" if lang == "it" else f"KB query failed: {err}"),
                action="workflow",
                reason="kb query failed",
            )

        data = tool_res.get("data") or {}
        context = str(data.get("context") or "").strip()
        hits = int(data.get("hits") or 0)

        if not context or hits <= 0:
            return TurnResult(
                content=("Non trovo abbastanza materiale rilevante nella KB attiva." if lang == "it" else "I could not find enough relevant material in the active KB."),
                action="workflow",
                reason="kb no hits",
                retrieval_hits=0,
            )

        if status:
            await status("🧠 Sto preparando una risposta grounded…")

        mem_ctx = self._memory_context(session)
        sys_prompt = system_base_context(lang)

        try:
            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": sys_prompt + ("\n\n" + mem_ctx if mem_ctx else "")},
                    {"role": "user", "content": kb_user_prompt(lang=lang, question=user_text, context=context)},
                ],
                tools=None,
                max_tokens=900,
                temperature=0.0,
            )
        except OllamaTimeout:
            return TurnResult(
                content=("⏱️ Timeout del modello locale durante la risposta grounded." if lang == "it" else "⏱️ Local model timed out during grounded response."),
                action="workflow",
                reason="kb ollama timeout",
                retrieval_hits=hits,
            )
        except OllamaProviderError as e:
            return TurnResult(
                content=(f"⚠️ Errore Ollama: {e}" if lang == "it" else f"⚠️ Ollama error: {e}"),
                action="workflow",
                reason="kb ollama error",
                retrieval_hits=hits,
            )

        return TurnResult(
            content=(resp.content or "").strip(),
            action="workflow",
            reason="kb_query",
            retrieval_hits=hits,
        )

    async def _workflow_news_digest(self, *, user_text: str, lang: str, status: StatusCb | None) -> TurnResult:
        query = (user_text or "").strip()
        if query.lower().startswith("/news"):
            query = query[5:].strip()
        if not query:
            query = "notizie del giorno" if lang == "it" else "latest news"

        if status:
            await status("📰 Raccolgo le fonti news…")

        try:
            result = await self._run_tool(
                "news_digest",
                NewsDigestArgs(query=query, count=6, fetch_chars=12000).model_dump(),
            )
        except Exception as e:
            return TurnResult(
                content=(f"Errore news digest: {e}" if lang == "it" else f"News digest error: {e}"),
                action="workflow",
                reason="news tool exception",
            )

        if not result.get("ok"):
            err = str(result.get("error") or "news_digest failed")
            return TurnResult(
                content=(f"News digest fallito: {err}" if lang == "it" else f"News digest failed: {err}"),
                action="workflow",
                reason="news tool failed",
            )

        data = result.get("data") or {}
        items = list(data.get("items") or [])
        if not items:
            return TurnResult(
                content=("Non ho trovato fonti abbastanza buone per costruire una rassegna." if lang == "it" else "I could not find enough good sources to build a digest."),
                action="workflow",
                reason="news no items",
            )

        lines: list[str] = [f"📰 News digest — {query}", ""]
        for idx, item in enumerate(items, start=1):
            headline = str(item.get("title") or "Untitled").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("description") or item.get("snippet") or item.get("text") or "").strip()
            lines.append(f"{idx}. {headline}")
            if snippet:
                lines.append(f"   {snippet[:350].strip()}")
            if url:
                lines.append(f"   {url}")
            lines.append("")

        return TurnResult(content="\n".join(lines).strip(), action="workflow", reason="news_digest")

    async def _workflow_youtube(self, *, user_text: str, lang: str, status: StatusCb | None) -> TurnResult:
        url = _first_youtube_url(user_text)
        if not url:
            return TurnResult(
                content=("Non trovo un URL YouTube valido." if lang == "it" else "I cannot find a valid YouTube URL."),
                action="workflow",
                reason="youtube url missing",
            )

        if status:
            await status("🎬 Recupero transcript e preparo il riassunto…")

        try:
            result = await self._run_tool("yt_summary", YTSummaryArgs(url=url, lang=lang).model_dump())
        except Exception as e:
            return TurnResult(
                content=(f"Errore YouTube summary: {e}" if lang == "it" else f"YouTube summary error: {e}"),
                action="workflow",
                reason="youtube tool exception",
            )

        if not result.get("ok"):
            err = str(result.get("error") or "yt_summary failed")
            return TurnResult(
                content=(f"Riassunto YouTube fallito: {err}" if lang == "it" else f"YouTube summary failed: {err}"),
                action="workflow",
                reason="youtube tool failed",
            )

        data = result.get("data") or {}
        summary = str(data.get("summary") or "").strip()

        return TurnResult(
            content=summary or ("Nessun riassunto disponibile." if lang == "it" else "No summary available."),
            action="workflow",
            reason="youtube_summarizer",
        )

    async def _workflow_podcast(self, *, session: Session, user_text: str, lang: str, status: StatusCb | None) -> TurnResult:
        topic = user_text.strip()
        if topic.lower().startswith("/podcast"):
            topic = topic[8:].strip()

        detected = detect_podcast_request(user_text, self.cfg)
        if detected is not None:
            maybe_topic, maybe_lang = detected
            if maybe_topic:
                topic = maybe_topic
            if maybe_lang:
                lang = maybe_lang

        if not topic:
            topic = "podcast"

        if status:
            await status("🎙️ Sto generando il podcast…")

        try:
            result = await generate_podcast(self.cfg, self.provider, topic=topic, lang=lang, status=status)
        except Exception as e:
            return TurnResult(
                content=(f"Errore podcast: {e}" if lang == "it" else f"Podcast error: {e}"),
                action="workflow",
                reason="podcast generation error",
            )

        self._store_audio_state(session, result.audio_path)

        msg = (
            f"🎧 Podcast pronto.\nAudio: {result.audio_path}"
            if lang == "it"
            else f"🎧 Podcast ready.\nAudio: {result.audio_path}"
        )

        return TurnResult(
            content=msg,
            action="workflow",
            reason="podcast",
            audio_path=result.audio_path,
            script=result.script,
        )

    async def _dispatch_workflow(self, *, session: Session, workflow_name: str, user_text: str, lang: str, status: StatusCb | None) -> TurnResult:
        name = (workflow_name or "").strip()
        if name == "chat":
            return await self._chat(session=session, user_text=user_text, lang=lang, status=status)
        if name == "kb_query":
            return await self._workflow_kb_query(session=session, user_text=user_text, lang=lang, status=status)
        if name == "news_digest":
            return await self._workflow_news_digest(user_text=user_text, lang=lang, status=status)
        if name == "youtube_summarizer":
            return await self._workflow_youtube(user_text=user_text, lang=lang, status=status)
        if name == "podcast":
            return await self._workflow_podcast(session=session, user_text=user_text, lang=lang, status=status)
        if name == "kb_ingest_pdf":
            return TurnResult(
                content=("L’ingest PDF va avviato da comando esplicito (/kb ingest ... oppure caricando un PDF su Telegram)." if lang == "it" else "PDF ingest must be started via an explicit command (/kb ingest ...) or by uploading a PDF on Telegram."),
                action="workflow",
                reason="kb ingest is command-managed",
            )
        return TurnResult(
            content=(f"Workflow non supportato: {name}" if lang == "it" else f"Unsupported workflow: {name}"),
            action="workflow",
            reason="unknown workflow",
        )

    async def one_turn(self, *, session: Session, user_text: str, status: StatusCb | None = None) -> TurnResult:
        text = (user_text or "").strip()
        if not text:
            return TurnResult(content="", action="noop", reason="empty input")

        lang = detect_language(text, default=self.cfg.default_language)

        if status:
            await status("🧭 Decido il percorso migliore…")

        decision = deterministic_route(
            user_text=text,
            state_file=session.state_file,
            default_language=lang,
        )

        if decision.action == "tool":
            result = await self._run_explicit_tool(
                session=session,
                lang=lang,
                tool_name=decision.name,
                args=dict(decision.args or {}),
            )
        else:
            result = await self._dispatch_workflow(
                session=session,
                workflow_name=decision.name,
                user_text=text,
                lang=lang,
                status=status,
            )

        if result.content.strip():
            self._append_turn_memory(session, text, result.content)

        if result.audio_path:
            self._store_audio_state(session, result.audio_path)

        return TurnResult(
            content=result.content,
            action=result.action,
            reason=decision.reason or result.reason,
            score=float(decision.score or 0.0),
            retrieval_hits=result.retrieval_hits,
            audio_path=result.audio_path,
            script=result.script,
        )
