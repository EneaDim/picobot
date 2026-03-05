from __future__ import annotations

import json
import re
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from picobot.agent.memory import make_memory_manager
from picobot.agent.prompts import (
    PromptPack,
    detect_language,
    kb_user_prompt,
    ping_reply,
    system_base_context,
)
from picobot.agent.router import route_json_one_line
from picobot.config.schema import Config
from picobot.providers.ollama import OllamaProvider, OllamaTimeout, OllamaProviderError
from picobot.tools.registry import ToolRegistry
from picobot.services.searxng import ensure_searxng_running
from picobot.sandbox.runner import SandboxRunner
from picobot.tools.podcast import detect_podcast_request, generate_podcast

from picobot.tools.retrieval import make_kb_ingest_pdf_tool, make_kb_query_tool
from picobot.tools.sandbox_file import make_sandbox_file_tool
from picobot.tools.sandbox_python import make_sandbox_python_tool
from picobot.tools.sandbox_web import make_sandbox_web_tool
from picobot.tools.youtube import make_yt_transcript_tool
from picobot.tools.web_search import make_web_search_tool
from picobot.tools.news_digest import make_news_digest_tool

from picobot.agent.agents import RetrieverAgent, SummarizerAgent

StatusCb = Callable[[str], Awaitable[None]]

_URL_RX = re.compile(r"(https?://\S+)")

def _extract_first_url(text: str) -> str | None:
    m = _URL_RX.search(text or "")
    if not m:
        return None
    return m.group(1).strip().strip(").,]}>\"'")


def _print_terminal_error(prefix: str, e: Exception) -> None:
    try:
        print(f"{prefix} {e!r}", file=sys.stderr)
        traceback.print_exc()
    except Exception:
        pass


@dataclass
class TurnResult:
    content: str
    action: str
    kb_mode: str
    reason: str
    retrieval_hits: int = 0
    audio_path: str | None = None
    script: str | None = None


class Orchestrator:
    """
    Orchestrator pulito e testabile:
    - routing via router (BM25+vector)
    - workflow per feature
    - tools sempre via ToolRegistry
    - memory compat via make_memory_manager
    """

    def __init__(self, cfg: Config, provider: OllamaProvider, workspace: Path) -> None:
        self.cfg = cfg
        self.provider = provider
        self.workspace = Path(workspace)
        self.docs_root = self.workspace / "docs"
        self.docs_root.mkdir(parents=True, exist_ok=True)
        self.tools = ToolRegistry()

        import os
        os.environ.setdefault("PICOBOT_SANDBOX_ROOT", str(self.workspace / "sandbox_runs"))
        self._bootstrap_on_start()

    def _ensure_tools(self) -> None:
        if self.tools.list():
            return

        ytdlp_bin = getattr(self.cfg.tools, "ytdlp_bin", "") if hasattr(self.cfg, "tools") else ""
        ytdlp_args = getattr(self.cfg.tools, "ytdlp_args", None) if hasattr(self.cfg, "tools") else None
        ytdlp_args = ytdlp_args or []

        for tool in [
            make_yt_transcript_tool(ytdlp_bin, ytdlp_args=ytdlp_args),
            make_kb_ingest_pdf_tool(self.docs_root),
            make_kb_query_tool(self.docs_root),
            make_sandbox_web_tool(self.cfg),
            make_sandbox_file_tool(),
            make_sandbox_python_tool(),
            make_web_search_tool(self.cfg),
            make_news_digest_tool(self.cfg),
        ]:
            try:
                self.tools.register(tool)
            except Exception:
                pass

    # --------- memory helpers ---------
    def _memory_context(self, mm) -> str:
        mem = mm.read_memory().strip()
        summ = mm.read_summary().strip()
        tail = mm.read_history_tail(self.cfg.memory_limits.tail_lines).strip()

        ctx = ""
        if mem and mem != "# Memory":
            ctx += f"\nSESSION MEMORY:\n{mem}\n"
        if summ and summ != "# Session Summary":
            ctx += f"\nSESSION SUMMARY:\n{summ}\n"
        if tail and tail != "# Session History":
            ctx += f"\nRECENT HISTORY:\n{tail}\n"
        return ctx


    def _bootstrap_on_start(self) -> None:

        """Initialize sandbox + tools early so failures are visible immediately."""

        # Ensure sandbox root exists

        sandbox_root = self.workspace / "sandbox_runs"

        sandbox_root.mkdir(parents=True, exist_ok=True)

    

        # Register tools early

        self._ensure_tools()

    

        # Sandbox self-test: run a harmless python command via SandboxRunner

        try:

            r = SandboxRunner(

                allowed_bins=["python"],

                sandbox_root=str(sandbox_root),

                timeout_s=10,

                max_output_bytes=50_000,

            ).run(["python", "-c", "print('sandbox_ok')"])

            res = r.to_exec_result()

            if res.returncode != 0 or "sandbox_ok" not in (res.stdout or ""):

                print("[bootstrap] sandbox self-test failed:", file=sys.stderr)

                print(res.stderr or "", file=sys.stderr)

        except Exception as e:

            print(f"[bootstrap] sandbox self-test error: {e}", file=sys.stderr)


    def _make_quote_from_context(self, context: str) -> str | None:
        for ln in (context or "").splitlines():
            ln = (ln or "").strip()
            if not ln:
                continue
            if len(ln) > 220:
                ln = ln[:220].rstrip() + "…"
            ln = ln.replace('"', '\\"')
            return f'\n\n> "{ln}"'
        return None

    # --------- KB pipeline ---------
    async def _kb_query(self, session, question: str, lang: str, status: StatusCb | None) -> TurnResult:
        retr = getattr(self.cfg, "retrieval", None)
        if retr and getattr(retr, "enabled", True) is False:
            return TurnResult(
                content=("Retrieval disabilitata." if lang == "it" else "Retrieval disabled."),
                action="kb_query",
                kb_mode="keep",
                reason="retrieval disabled",
                retrieval_hits=0,
            )

        if status:
            await status("🔎 Searching KB…")

        self._ensure_tools()
        tool = self.tools.get("kb_query")
        if not tool:
            return TurnResult(
                content=("Tool KB mancante." if lang == "it" else "KB tool missing."),
                action="kb_query",
                kb_mode="keep",
                reason="kb tool missing",
                retrieval_hits=0,
            )

        kb_name = getattr(session, "kb_name", None) or getattr(getattr(self.cfg, "retrieval", None), "default_kb", None) or "default"
        top_k = int(getattr(getattr(self.cfg, "retrieval", None), "top_k", 4) or 4)

        try:
            model = tool.validate({"kb_name": kb_name, "query": question, "top_k": top_k})
            res = await tool.handler(model)
        except Exception as e:
            _print_terminal_error("[kb_query] ERROR:", e)
            return TurnResult(
                content=("⚠️ Errore retrieval." if lang == "it" else "⚠️ Retrieval error."),
                action="kb_query",
                kb_mode="keep",
                reason="kb error",
                retrieval_hits=0,
            )

        if not isinstance(res, dict) or not res.get("ok"):
            err = ""
            try:
                err = (res.get("error") or "").strip() if isinstance(res, dict) else ""
            except Exception:
                err = ""
            msg = ("Non trovato nei documenti indicizzati." if lang == "it" else "Not found in indexed documents.")
            if err:
                msg += ("\nMotivo: " if lang == "it" else "\nReason: ") + err
            return TurnResult(content=msg, action="kb_query", kb_mode="keep", reason="no hits", retrieval_hits=0)

        data = res.get("data") or {}
        context = (data.get("context") or "").strip()
        hits = int(data.get("hits") or 0)

        if hits <= 0 or not context:
            return TurnResult(
                content=("Non trovato nei documenti indicizzati." if lang == "it" else "Not found in indexed documents."),
                action="kb_query",
                kb_mode="keep",
                reason="no hits",
                retrieval_hits=0,
            )

        if status:
            await status("💭 Thinking…")

        mm = make_memory_manager(self.cfg, session, self.workspace)
        memory_context = self._memory_context(mm)
        base_context = system_base_context(lang) + "\n"

        try:
            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": base_context + memory_context},
                    {"role": "user", "content": kb_user_prompt(lang=lang, question=question, context=context)},
                ],
                tools=None,
                max_tokens=650,
                temperature=0.0,
            )
        except OllamaTimeout:
            return TurnResult(
                content="⏱️ Local model timed out. Increase ollama.timeout_s.",
                action="kb_query",
                kb_mode="keep",
                reason="ollama timeout",
                retrieval_hits=hits,
            )
        except OllamaProviderError as e:
            return TurnResult(
                content=f"⚠️ Ollama error: {e}",
                action="kb_query",
                kb_mode="keep",
                reason="ollama error",
                retrieval_hits=hits,
            )

        answer = (resp.content or "").strip()
        if '\n> "' not in answer:
            q = self._make_quote_from_context(context)
            if q:
                answer += q

        return TurnResult(content=answer, action="kb_query", kb_mode="keep", reason="kb_query", retrieval_hits=hits)

    # --------- Tool runner (ToolSpec) ---------
    async def _run_tool(self, mm, lang: str, tool_name: str, args: dict[str, Any]) -> TurnResult:
        self._ensure_tools()
        tool = self.tools.get(tool_name)
        if not tool:
            msg = ("Tool sconosciuto." if lang == "it" else "Unknown tool.")
            mm.append_turn("assistant", msg)
            return TurnResult(content=msg, action="tool", kb_mode="keep", reason="no tool")

        try:
            model = tool.validate(args or {})
            res = await tool.handler(model)
        except Exception as e:
            _print_terminal_error(f"[tool:{tool_name}] ERROR:", e)
            msg = ("⚠️ Errore tool." if lang == "it" else "⚠️ Tool error.")
            mm.append_turn("assistant", msg)
            return TurnResult(content=msg, action="tool", kb_mode="keep", reason="tool error")

        if not isinstance(res, dict) or not res.get("ok"):
            err = ""
            try:
                err = (res.get("error") or "").strip() if isinstance(res, dict) else ""
            except Exception:
                err = ""
            msg = ("⚠️ Operazione non riuscita." if lang == "it" else "⚠️ Operation failed.")
            if err:
                msg += ("\nMotivo: " if lang == "it" else "\nReason: ") + err
            mm.append_turn("assistant", msg)
            return TurnResult(content=msg, action="tool", kb_mode="keep", reason="tool fail")

        data = res.get("data") or {}
        text = ""
        if isinstance(data, dict) and "text" in data:
            text = str(data.get("text") or "")
        if not text:
            text = json.dumps(data, ensure_ascii=False)[:2500]
        mm.append_turn("assistant", text)
        return TurnResult(content=text, action="tool", kb_mode="keep", reason="tool ok")

    # --------- Main entry ---------
    async def one_turn(self, session, user_text: str, status: StatusCb | None = None, input_lang: str | None = None) -> TurnResult:
        mm = make_memory_manager(self.cfg, session, self.workspace)

        lang = (input_lang or "").strip() or detect_language(user_text, default=getattr(self.cfg, "default_language", "it"))

        # deterministic ping
        if (user_text or "").strip().lower() == "ping":
            mm.append_turn("user", user_text)
            content = ping_reply(lang)
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="chat", kb_mode="keep", reason="ping")

        # deterministic remember (keeps old behavior)
        # (memory manager already handles remember patterns internally in existing codebase)
        mm.append_turn("user", user_text)

        # podcast trigger (keep existing)
        pc = detect_podcast_request(user_text, self.cfg)
        if pc:
            topic, plang = pc
            use_lang = (plang or "").strip() or lang
            if status:
                await status("🎙 Podcast…")
            try:
                pr = await generate_podcast(self.cfg, self.provider, topic=topic, lang=use_lang, status=status)
            except Exception as e:
                _print_terminal_error("[podcast] ERROR:", e)
                content = ("⚠️ Errore podcast." if use_lang == "it" else "⚠️ Podcast error.")
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="podcast", kb_mode="keep", reason="podcast error")
            content = "✅ Podcast pronto." if use_lang == "it" else "✅ Podcast ready."
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="podcast", kb_mode="keep", reason="podcast", audio_path=pr.audio_path, script=pr.script)

        if status:
            await status("🧭 Routing…")

        state_file = getattr(session, "state_file", self.workspace / "state" / "router.json")
        try:
            r = json.loads(route_json_one_line(user_text, state_file, default_language=getattr(self.cfg, "default_language", "it")))
        except Exception:
            r = {"route": "workflow", "workflow": "chat", "lang": lang, "score": 0.0}

        lang = (r.get("lang") or lang).strip() or lang

        # Tool route (explicit tool ...)
        if (r.get("route") or "") == "tool":
            tool_name = (r.get("tool_name") or "").strip()
            args = r.get("args") if isinstance(r.get("args"), dict) else {}
            return await self._run_tool(mm, lang, tool_name, args)

        wf = (r.get("workflow") or "chat").strip()
        memory_context = self._memory_context(mm)

        # Workflows
        if wf == "kb_query":
            return await self._kb_query(session, user_text, lang, status)

        if wf == "kb_ingest_pdf":
            # delegate to tool
            return await self._run_tool(mm, lang, "kb_ingest_pdf", {"text": user_text, "lang": lang})

        if wf == "youtube_summarizer":
            if status:
                await status("🎬 YouTube…")
            self._ensure_tools()
            yt = self.tools.get("yt_transcript")
            if not yt:
                msg = "yt_transcript tool missing"
                mm.append_turn("assistant", msg)
                return TurnResult(content=msg, action="workflow", kb_mode="keep", reason="missing yt tool")

            url = _extract_first_url(user_text) or user_text.strip()
            model = yt.validate({"url": url, "lang": lang})
            tr = await yt.handler(model)
            if not tr.get("ok"):
                err = tr.get("error") or "yt transcript failed"
                mm.append_turn("assistant", err)
                return TurnResult(content=str(err), action="workflow", kb_mode="keep", reason="yt failed")

            transcript = ((tr.get("data") or {}).get("transcript") or "").strip()
            summarizer = SummarizerAgent(self.provider)
            sres = await summarizer.run(input_text=transcript, lang=lang, memory_ctx=memory_context, kind="youtube")
            mm.append_turn("assistant", sres.text)
            return TurnResult(content=sres.text, action="workflow", kb_mode="keep", reason="youtube_summarizer")

        if wf == "news_digest":
            if status:
                await status("🗞 News…")
            q = user_text
            low = q.lower().strip()
            if low.startswith("news:"):
                q = q.split(":", 1)[1].strip()
            if low.startswith("/news"):
                q = q.split(None, 1)[1].strip() if " " in q else ""

            self._ensure_tools()
            retriever = RetrieverAgent(self.tools)
            rres = await retriever.run(input_text=q, lang=lang, memory_ctx=memory_context, mode="news")
            if not rres.ok:
                msg = rres.data.get("error") or "news retrieval failed"
                mm.append_turn("assistant", str(msg))
                return TurnResult(content=str(msg), action="workflow", kb_mode="keep", reason="news retrieval failed")

            summarizer = SummarizerAgent(self.provider)
            sres = await summarizer.run(input_text=rres.text, lang=lang, memory_ctx=memory_context, kind="news")
            mm.append_turn("assistant", sres.text)
            return TurnResult(content=sres.text, action="workflow", kb_mode="keep", reason="news_digest")

        # Default chat
        if status:
            await status("💭 Thinking…")

        base_context = system_base_context(lang) + "\n"
        try:
            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": base_context + memory_context},
                    {"role": "user", "content": PromptPack(lang=lang).orchestrator(user_text)},
                ],
                tools=None,
                max_tokens=650,
                temperature=0.0,
            )
        except OllamaTimeout:
            content = "⏱️ Local model timed out. Increase ollama.timeout_s."
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="chat", kb_mode="keep", reason="ollama timeout")
        except OllamaProviderError as e:
            content = f"⚠️ Ollama error: {e}"
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="chat", kb_mode="keep", reason="ollama error")

        content = (resp.content or "").strip() or "(empty)"
        mm.append_turn("assistant", content)
        return TurnResult(content=content, action="chat", kb_mode="keep", reason="chat")
