from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from picobot.agent.models import RuntimeHooks, StatusCb, TurnResult
from picobot.prompts import kb_user_prompt
from picobot.providers.ollama import OllamaProviderError, OllamaTimeout
from picobot.session.manager import Session
from picobot.tools.base import ToolError
from picobot.tools.news_digest import NewsDigestArgs
from picobot.tools.podcast import detect_podcast_request, generate_podcast
from picobot.tools.youtube import YTSummaryArgs

if TYPE_CHECKING:
    from picobot.agent.application import Orchestrator

_YT_RX = re.compile(r"(https?://\S*(youtube\.com|youtu\.be)\S*)", re.IGNORECASE)


def _first_youtube_url(text: str) -> str | None:
    match = _YT_RX.search(text or "")
    if not match:
        return None
    return match.group(1).strip()


def _provider_name(provider: Any) -> str | None:
    name = getattr(provider, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    cls_name = provider.__class__.__name__
    if cls_name.endswith("Provider"):
        cls_name = cls_name[:-8]
    return cls_name.lower() if cls_name else None


class WorkflowDispatcher:
    def __init__(self, orchestrator: "Orchestrator") -> None:
        self.orchestrator = orchestrator

    async def _emit_hook(self, hook, payload: dict[str, Any]) -> None:
        await self.orchestrator._emit_hook(hook, payload)

    async def _execute_tool(
        self,
        tool_name: str,
        args: dict[str, Any],
        *,
        hooks: RuntimeHooks | None = None,
        workflow_name: str | None = None,
    ) -> dict:
        return await self.orchestrator._call_tool(
            tool_name,
            args,
            hooks=hooks,
            workflow_name=workflow_name,
        )

    async def explicit_tool(
        self,
        *,
        session: Session,
        lang: str,
        tool_name: str,
        args: dict[str, Any],
        status: StatusCb | None = None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        if status:
            labels = {
                "tts": "🔊 Sto generando l'audio…",
                "stt": "🎙️ Sto trascrivendo l'audio…",
                "web": "🌐 Sto interrogando il backend web…",
                "python": "🐍 Sto eseguendo il codice Python…",
                "file": "📄 Sto leggendo il file…",
            }
            await status(labels.get(tool_name, f"🧰 Eseguo il tool {tool_name}…"))

        try:
            result = await self._execute_tool(
                tool_name,
                args,
                hooks=hooks,
                workflow_name="explicit_tool",
            )
        except KeyError:
            return TurnResult(
                content=(f"Tool sconosciuto: {tool_name}" if lang == "it" else f"Unknown tool: {tool_name}"),
                action="tool",
                reason="unknown tool",
                audit={"tool_name": tool_name},
            )
        except ToolError as e:
            return TurnResult(
                content=(f"Errore tool: {e}" if lang == "it" else f"Tool error: {e}"),
                action="tool",
                reason="tool validation error",
                audit={"tool_name": tool_name},
            )
        except Exception as e:
            return TurnResult(
                content=(f"Errore durante l'esecuzione del tool: {e}" if lang == "it" else f"Tool execution error: {e}"),
                action="tool",
                reason="tool execution error",
                audit={"tool_name": tool_name},
            )

        if not isinstance(result, dict):
            return TurnResult(
                content=(f"Risposta tool non valida da {tool_name}" if lang == "it" else f"Invalid tool response from {tool_name}"),
                action="tool",
                reason="invalid tool response",
                audit={"tool_name": tool_name},
            )

        if not result.get("ok"):
            err = str(result.get("error") or "tool failed")
            return TurnResult(
                content=(f"Tool fallito: {err}" if lang == "it" else f"Tool failed: {err}"),
                action="tool",
                reason="tool returned error",
                audit={"tool_name": tool_name},
            )

        data = result.get("data") or {}
        audio_path = str(data.get("audio_path") or "").strip() or None
        if audio_path:
            self.orchestrator.memory_context_service.store_audio_state(session, audio_path)

        if tool_name == "tts" and audio_path:
            message = (
                f"Audio TTS generato.\nPath: {audio_path}"
                if lang == "it"
                else f"TTS audio generated.\nPath: {audio_path}"
            )
            return TurnResult(
                content=message,
                action="tool",
                reason="tool:tts",
                audio_path=audio_path,
                audit={
                    "tool_name": "tts",
                    "tool_ok": True,
                    "suppress_text_when_audio": True,
                    "audio_caption": "🔊 Audio TTS generato",
                },
            )

        if tool_name == "stt":
            transcript = str(data.get("text") or data.get("transcript") or "").strip()
            if transcript:
                return TurnResult(
                    content=transcript,
                    action="tool",
                    reason="tool:stt",
                    audit={"tool_name": "stt", "tool_ok": True},
                )

        pretty = json.dumps(data, ensure_ascii=False, indent=2)

        return TurnResult(
            content=pretty,
            action="tool",
            reason=f"tool:{tool_name}",
            audio_path=audio_path,
            audit={"tool_name": tool_name, "tool_ok": True},
        )

    async def chat(
        self,
        *,
        session: Session,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        if status:
            await status("💭 Sto pensando…")

        assembly = self.orchestrator.memory_context_service.build_context_assembly(
            session=session,
            lang=lang,
            retrieval_context="",
            runtime_context=["workflow=chat"],
            history_turns=8,
        )

        await self._emit_hook(
            getattr(hooks, "on_context_built", None),
            {
                "workflow_name": "chat",
                "history_messages_count": assembly.history_messages_count,
                "memory_facts_count": assembly.memory_facts_count,
                "summary_present": assembly.summary_present,
                "retrieval_present": assembly.retrieval_present,
                "runtime_context_count": assembly.runtime_context_count,
                "history_turns_requested": assembly.history_turns_requested,
            },
        )

        messages = assembly.model_context.to_messages(user_text=user_text)
        task_provider = self.orchestrator.resolve_provider("chat")
        provider_name = _provider_name(task_provider)

        try:
            resp = await task_provider.chat(
                messages=messages,
                tools=None,
                max_tokens=int(getattr(self.orchestrator.cfg.ollama, "max_tokens", 1200) or 1200),
                temperature=0.2,
            )
        except OllamaTimeout:
            return TurnResult(
                content=("⏱️ Il modello locale non ha risposto in tempo." if lang == "it" else "⏱️ The local model timed out."),
                action="chat",
                reason="ollama timeout",
                provider_name=provider_name,
                audit={"workflow_name": "chat", "provider_name": provider_name},
            )
        except OllamaProviderError as e:
            return TurnResult(
                content=(f"⚠️ Errore Ollama: {e}" if lang == "it" else f"⚠️ Ollama error: {e}"),
                action="chat",
                reason="ollama error",
                provider_name=provider_name,
                audit={"workflow_name": "chat", "provider_name": provider_name},
            )

        content = (resp.content or "").strip() or ("Nessuna risposta." if lang == "it" else "No response.")
        return TurnResult(
            content=content,
            action="chat",
            reason="chat",
            provider_name=provider_name,
            audit={"workflow_name": "chat", "provider_name": provider_name},
        )

    async def kb_query(
        self,
        *,
        session: Session,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        raw_user_text = (user_text or "").strip()
        lowered = raw_user_text.lower()
        if lowered.startswith("/kb query"):
            raw_user_text = raw_user_text[len("/kb query"):].strip()
        elif lowered.startswith("/kb ask"):
            raw_user_text = raw_user_text[len("/kb ask"):].strip()

        kb_name = str(session.get_state().get("kb_name") or self.orchestrator.cfg.default_kb_name or "default").strip()
        top_k = int(getattr(self.orchestrator.cfg.retrieval, "top_k", 4) or 4)

        if status:
            await status("🔎 Cerco nella knowledge base…")

        await self._emit_hook(
            getattr(hooks, "on_retrieval_started", None),
            {
                "workflow_name": "kb_query",
                "kb_name": kb_name,
                "top_k": top_k,
            },
        )

        try:
            tool_res = await self._execute_tool(
                "kb_query",
                {"kb_name": kb_name, "query": raw_user_text, "top_k": top_k},
                hooks=hooks,
                workflow_name="kb_query",
            )
        except Exception as e:
            await self._emit_hook(
                getattr(hooks, "on_retrieval_completed", None),
                {
                    "workflow_name": "kb_query",
                    "kb_name": kb_name,
                    "top_k": top_k,
                    "ok": False,
                    "error": str(e),
                    "hits": 0,
                },
            )
            return TurnResult(
                content=(f"Errore retrieval: {e}" if lang == "it" else f"Retrieval error: {e}"),
                action="workflow",
                reason="kb tool execution error",
                kb_name=kb_name,
                audit={"workflow_name": "kb_query", "kb_name": kb_name},
            )

        if not tool_res.get("ok"):
            err = str(tool_res.get("error") or "kb_query failed")
            await self._emit_hook(
                getattr(hooks, "on_retrieval_completed", None),
                {
                    "workflow_name": "kb_query",
                    "kb_name": kb_name,
                    "top_k": top_k,
                    "ok": False,
                    "error": err,
                    "hits": 0,
                },
            )
            return TurnResult(
                content=(f"KB query fallita: {err}" if lang == "it" else f"KB query failed: {err}"),
                action="workflow",
                reason="kb query failed",
                kb_name=kb_name,
                audit={"workflow_name": "kb_query", "kb_name": kb_name},
            )

        data = tool_res.get("data") or {}
        context = str(data.get("context") or "").strip()
        hits = int(data.get("hits") or 0)

        await self._emit_hook(
            getattr(hooks, "on_retrieval_completed", None),
            {
                "workflow_name": "kb_query",
                "kb_name": kb_name,
                "top_k": top_k,
                "ok": True,
                "hits": hits,
                "context_chars": len(context),
            },
        )

        if not context or hits <= 0:
            return TurnResult(
                content=("Non trovo abbastanza materiale rilevante nella KB attiva." if lang == "it" else "I could not find enough relevant material in the active KB."),
                action="workflow",
                reason="kb no hits",
                retrieval_hits=0,
                kb_name=kb_name,
                audit={"workflow_name": "kb_query", "kb_name": kb_name, "retrieval_hits": 0},
            )

        if status:
            await status("🧠 Sto preparando una risposta grounded…")

        assembly = self.orchestrator.memory_context_service.build_context_assembly(
            session=session,
            lang=lang,
            retrieval_context=context,
            runtime_context=[f"workflow=kb_query", f"retrieval_hits={hits}", f"kb_name={kb_name}"],
            history_turns=6,
        )

        await self._emit_hook(
            getattr(hooks, "on_context_built", None),
            {
                "workflow_name": "kb_query",
                "history_messages_count": assembly.history_messages_count,
                "memory_facts_count": assembly.memory_facts_count,
                "summary_present": assembly.summary_present,
                "retrieval_present": assembly.retrieval_present,
                "runtime_context_count": assembly.runtime_context_count,
                "history_turns_requested": assembly.history_turns_requested,
                "retrieval_hits": hits,
                "kb_name": kb_name,
            },
        )

        messages = assembly.model_context.to_messages(
            user_text=kb_user_prompt(lang=lang, question=raw_user_text, context=context)
        )

        task_provider = self.orchestrator.resolve_provider("qa")
        provider_name = _provider_name(task_provider)

        try:
            resp = await task_provider.chat(
                messages=messages,
                tools=None,
                max_tokens=int(getattr(self.orchestrator.cfg.ollama, "max_tokens", 1200) or 1200),
                temperature=0.0,
            )
        except OllamaTimeout:
            return TurnResult(
                content=("⏱️ Timeout del modello locale durante la risposta grounded." if lang == "it" else "⏱️ Local model timed out during grounded response."),
                action="workflow",
                reason="kb ollama timeout",
                retrieval_hits=hits,
                provider_name=provider_name,
                kb_name=kb_name,
                audit={"workflow_name": "kb_query", "provider_name": provider_name, "kb_name": kb_name, "retrieval_hits": hits},
            )
        except OllamaProviderError as e:
            return TurnResult(
                content=(f"⚠️ Errore Ollama: {e}" if lang == "it" else f"⚠️ Ollama error: {e}"),
                action="workflow",
                reason="kb ollama error",
                retrieval_hits=hits,
                provider_name=provider_name,
                kb_name=kb_name,
                audit={"workflow_name": "kb_query", "provider_name": provider_name, "kb_name": kb_name, "retrieval_hits": hits},
            )

        content = (resp.content or "").strip()
        if not content:
            content = (
                "Ho trovato contesto nella KB ma il modello non ha prodotto una risposta utile."
                if lang == "it"
                else "I found KB context but the model did not produce a useful answer."
            )

        return TurnResult(
            content=content,
            action="workflow",
            reason="kb_query",
            retrieval_hits=hits,
            provider_name=provider_name,
            kb_name=kb_name,
            audit={"workflow_name": "kb_query", "provider_name": provider_name, "kb_name": kb_name, "retrieval_hits": hits},
        )

    async def news_digest(
        self,
        *,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        query = (user_text or "").strip()
        if query.lower().startswith("/news"):
            query = query[5:].strip()
        if not query:
            query = "notizie del giorno" if lang == "it" else "latest news"

        if status:
            await status("📰 Raccolgo le fonti news…")

        try:
            result = await self._execute_tool(
                "news_digest",
                NewsDigestArgs(query=query, count=6, fetch_chars=12000).model_dump(),
                hooks=hooks,
                workflow_name="news_digest",
            )
        except Exception as e:
            return TurnResult(
                content=(f"Errore news digest: {e}" if lang == "it" else f"News digest error: {e}"),
                action="workflow",
                reason="news tool exception",
                audit={"workflow_name": "news_digest", "query": query},
            )

        if not result.get("ok"):
            err = str(result.get("error") or "news_digest failed")
            return TurnResult(
                content=(f"News digest fallito: {err}" if lang == "it" else f"News digest failed: {err}"),
                action="workflow",
                reason="news tool failed",
                audit={"workflow_name": "news_digest", "query": query},
            )

        data = result.get("data") or {}
        items = list(data.get("items") or [])
        if not items:
            return TurnResult(
                content=("Non ho trovato fonti abbastanza buone per costruire una rassegna." if lang == "it" else "I could not find enough good sources to build a digest."),
                action="workflow",
                reason="news no items",
                audit={"workflow_name": "news_digest", "query": query},
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

        return TurnResult(
            content="\n".join(lines).strip(),
            action="workflow",
            reason="news_digest",
            audit={"workflow_name": "news_digest", "query": query, "items": len(items)},
        )

    async def youtube_summarizer(
        self,
        *,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        url = _first_youtube_url(user_text)
        if not url:
            return TurnResult(
                content=("Non trovo un URL YouTube valido." if lang == "it" else "I cannot find a valid YouTube URL."),
                action="workflow",
                reason="youtube url missing",
                audit={"workflow_name": "youtube_summarizer"},
            )

        if status:
            await status("🎬 Recupero transcript e preparo il riassunto…")

        try:
            youtube_cfg = getattr(self.orchestrator.cfg.tools, "youtube", None)
            prefer_sub_langs = list(getattr(youtube_cfg, "prefer_sub_langs", []) or [])

            result = await self._execute_tool(
                "yt_summary",
                YTSummaryArgs(
                    url=url,
                    lang=lang,
                    prefer_sub_langs=prefer_sub_langs,
                ).model_dump(),
                hooks=hooks,
                workflow_name="youtube_summarizer",
            )
        except Exception as e:
            return TurnResult(
                content=(f"Errore YouTube summary: {e}" if lang == "it" else f"YouTube summary error: {e}"),
                action="workflow",
                reason="youtube tool exception",
                audit={"workflow_name": "youtube_summarizer", "url": url},
            )

        if not result.get("ok"):
            err = str(result.get("error") or "yt_summary failed")
            return TurnResult(
                content=(f"Riassunto YouTube fallito: {err}" if lang == "it" else f"YouTube summary failed: {err}"),
                action="workflow",
                reason="youtube tool failed",
                audit={"workflow_name": "youtube_summarizer", "url": url},
            )

        data = result.get("data") or {}
        summary = str(data.get("summary") or "").strip()

        return TurnResult(
            content=summary or ("Nessun riassunto disponibile." if lang == "it" else "No summary available."),
            action="workflow",
            reason="youtube_summarizer",
            audit={"workflow_name": "youtube_summarizer", "url": url},
        )

    async def podcast(
        self,
        *,
        session: Session,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        topic = user_text.strip()
        if topic.lower().startswith("/podcast"):
            topic = topic[8:].strip()

        detected = detect_podcast_request(user_text, self.orchestrator.cfg)
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

        task_provider = self.orchestrator.resolve_provider("podcast_writer")
        provider_name = _provider_name(task_provider)

        try:
            result = await generate_podcast(
                self.orchestrator.cfg,
                task_provider,
                topic=topic,
                lang=lang,
                status=status,
            )
        except Exception as e:
            return TurnResult(
                content=(f"Errore podcast: {e}" if lang == "it" else f"Podcast error: {e}"),
                action="workflow",
                reason="podcast generation error",
                provider_name=provider_name,
                audit={"workflow_name": "podcast", "provider_name": provider_name, "topic": topic},
            )

        self.orchestrator.memory_context_service.store_audio_state(session, result.audio_path)

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
            provider_name=provider_name,
            audit={
                "workflow_name": "podcast",
                "provider_name": provider_name,
                "topic": topic,
                "suppress_text_when_audio": False,
                "audio_caption": "🎧 Podcast pronto",
            },
        )

    async def dispatch(
        self,
        *,
        session: Session,
        workflow_name: str,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        name = (workflow_name or "").strip()
        if name == "chat":
            return await self.chat(session=session, user_text=user_text, lang=lang, status=status, hooks=hooks)
        if name == "kb_query":
            return await self.kb_query(session=session, user_text=user_text, lang=lang, status=status, hooks=hooks)
        if name == "news_digest":
            return await self.news_digest(user_text=user_text, lang=lang, status=status, hooks=hooks)
        if name == "youtube_summarizer":
            return await self.youtube_summarizer(user_text=user_text, lang=lang, status=status, hooks=hooks)
        if name == "podcast":
            return await self.podcast(session=session, user_text=user_text, lang=lang, status=status, hooks=hooks)
        if name == "kb_ingest_pdf":
            return TurnResult(
                content=("L’ingest PDF va avviato da comando esplicito (/kb ingest ... oppure caricando un PDF su Telegram)." if lang == "it" else "PDF ingest must be started via an explicit command (/kb ingest ...) or by uploading a PDF on Telegram."),
                action="workflow",
                reason="kb ingest is command-managed",
                audit={"workflow_name": "kb_ingest_pdf"},
            )
        return TurnResult(
            content=(f"Workflow non supportato: {name}" if lang == "it" else f"Unsupported workflow: {name}"),
            action="workflow",
            reason="unknown workflow",
            audit={"workflow_name": name or "unknown"},
        )
