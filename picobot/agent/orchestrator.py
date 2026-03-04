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
    youtube_summarizer_system,
    youtube_summarizer_user_prompt,
)
from picobot.agent.router import route_json_one_line
from picobot.config.schema import Config
from picobot.providers.ollama import OllamaProvider, OllamaTimeout, OllamaProviderError
from picobot.tools.registry import ToolRegistry
from picobot.tools.podcast import detect_podcast_request, generate_podcast
from picobot.tools.retrieval import make_kb_ingest_pdf_tool, make_kb_query_tool
from picobot.tools.sandbox_file import make_sandbox_file_tool
from picobot.tools.sandbox_python import make_sandbox_python_tool
from picobot.tools.sandbox_web import make_sandbox_web_tool
from picobot.tools.youtube import make_yt_summary_tool, make_yt_transcript_tool
from picobot.tools.web_search import make_web_search_tool

StatusCb = Callable[[str], Awaitable[None]]


@dataclass
class TurnResult:
    content: str
    action: str
    kb_mode: str
    reason: str
    retrieval_hits: int = 0
    audio_path: str | None = None
    script: str | None = None


_REMEMBER_PATTERNS = [
    re.compile(r"\bremember\b\s+(.*)$", re.IGNORECASE),
    re.compile(r"\bricorda\b\s+(.*)$", re.IGNORECASE),
]


def _extract_remember_item(text: str) -> str | None:
    t = (text or "").strip()
    for rx in _REMEMBER_PATTERNS:
        m = rx.search(t)
        if not m:
            continue
        val = (m.group(1) or "").strip()
        val = re.sub(r"\b(reply only with ok|rispondi solo con ok)\b.*$", "", val, flags=re.IGNORECASE).strip()
        val = val.strip(" .,:;")
        return val or None
    return None


def _wants_reply_only_ok(text: str) -> bool:
    t = (text or "").lower()
    return "reply only with ok" in t or "rispondi solo con ok" in t


def _extract_first_url(text: str) -> str | None:
    s = text or ""
    m = re.search(r"(https?://\S+)", s)
    if not m:
        return None
    return m.group(1).strip().rstrip(").,;]})")


def _extract_pdf_path(text: str) -> str | None:
    m = re.search(r"(\S+\.pdf)\b", text or "", flags=re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip()


def _looks_like_question(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    low = t.lower()
    if "?" in low:
        return True
    starters = (
        "what", "where", "who", "when", "why", "how",
        "cosa", "dove", "chi", "quando", "perché", "perche", "come",
        "che cosa", "cos'è", "cos e", "mi ricordi", "ti ricordi",
    )
    return any(low.startswith(x + " ") or low == x for x in starters)


def _session_state(session) -> dict:
    try:
        st = session.get_state() or {}
        return st if isinstance(st, dict) else {}
    except Exception:
        return {}


def _session_get(session, key: str, default: Any) -> Any:
    st = _session_state(session)
    return st.get(key, default)


def _session_kb_name(session, cfg: Config) -> str:
    kb = _session_get(session, "kb_name", None)
    if kb:
        return str(kb)
    if hasattr(cfg, "default_kb_name") and getattr(cfg, "default_kb_name"):
        return str(getattr(cfg, "default_kb_name"))
    retr = getattr(cfg, "retrieval", None)
    if retr and getattr(retr, "default_kb", None):
        return str(getattr(retr, "default_kb"))
    return "default"


def _print_terminal_error(prefix: str, e: Exception) -> None:
    try:
        print(f"{prefix} {e!r}", file=sys.stderr)
        traceback.print_exc()
    except Exception:
        pass


def _render_tool_result(tool_name: str, tool_res: dict, lang: str) -> str:
    data = tool_res.get("data") if isinstance(tool_res, dict) else None
    payload = data if data is not None else tool_res

    if tool_name == "sandbox_python" and isinstance(payload, dict):
        out = (payload.get("stdout") or "").strip()
        err = (payload.get("stderr") or "").strip()
        if out and not err:
            return out
        if out and err:
            return f"{out}\n{err}".strip()
        if err:
            return err
        return "ok"

    if tool_name == "sandbox_file" and isinstance(payload, dict):
        path = payload.get("path") or ""
        size = payload.get("size")
        preview = (payload.get("preview") or "").strip()
        head = f"{path} ({size} bytes)" if size is not None else str(path)
        return f"{head}\n{preview}".strip()

    if tool_name == "yt_summary" and isinstance(payload, dict):
        return (payload.get("summary") or "").strip() or ("(empty)" if lang == "en" else "(vuoto)")

    if tool_name == "yt_transcript" and isinstance(payload, dict):
        t = (payload.get("transcript") or "").strip()
        if len(t) > 4000:
            return t[:4000] + "…"
        return t or ("(empty)" if lang == "en" else "(vuoto)")

    if tool_name == "kb_ingest_pdf" and isinstance(payload, dict):
        kb_name = payload.get("kb_name") or ""
        doc = payload.get("doc") or {}
        return f"✅ Ingested into KB '{kb_name}': {doc}"

    if isinstance(payload, dict) and isinstance(payload.get("text"), str):
        return payload["text"].strip()

    try:
        return json.dumps(payload, ensure_ascii=False)[:1200]
    except Exception:
        return str(payload)[:1200]


class Orchestrator:
    def __init__(self, cfg: Config, provider: OllamaProvider, workspace: Path) -> None:
        self.cfg = cfg
        self.provider = provider
        self.workspace = Path(workspace)
        self.docs_root = self.workspace / "docs"
        self.docs_root.mkdir(parents=True, exist_ok=True)
        self.tools = ToolRegistry()

    def _register_tools(self) -> None:
        def _call_factory_compat(factory, *args, **kwargs):
            try:
                return factory(*args, **kwargs)
            except TypeError:
                return factory(*args)

        ytdlp_bin = getattr(self.cfg.tools, "ytdlp_bin", "") if hasattr(self.cfg, "tools") else ""
        ytdlp_args = getattr(self.cfg.tools, "ytdlp_args", None) if hasattr(self.cfg, "tools") else None
        ytdlp_args = ytdlp_args or []

        async def llm_summarize(transcript: str, url: str, lang: str | None):
            use_lang = (lang or "").strip() or getattr(self.cfg, "default_language", "it")
            max_chars = int(getattr(getattr(self.cfg, "summary", None), "max_chars", 12000) or 12000)
            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": youtube_summarizer_system()},
                    {"role": "user", "content": youtube_summarizer_user_prompt(transcript=transcript, url=url, lang=use_lang, max_chars=max_chars)},
                ],
                tools=None,
                max_tokens=650,
                temperature=0.0,
            )
            return (resp.content or "").strip()

        for tool in [
            _call_factory_compat(make_yt_transcript_tool, ytdlp_bin, ytdlp_args=ytdlp_args),
            _call_factory_compat(make_yt_summary_tool, ytdlp_bin, llm_summarize, ytdlp_args=ytdlp_args),
            make_kb_ingest_pdf_tool(self.docs_root),
            make_kb_query_tool(self.docs_root),
            make_sandbox_web_tool(),
            make_sandbox_file_tool(),
            make_sandbox_python_tool(),
                    make_web_search_tool(self.cfg),
        ]:
            try:
                self.tools.register(tool)
            except Exception:
                pass

    def _ensure_tools(self) -> None:
        if self.tools.list():
            return
        self._register_tools()

    async def _run_tool(self, tool_name: str, args: dict, lang: str, status: StatusCb | None) -> TurnResult:
        self._ensure_tools()
        if status:
            await status("🛠 Tool…")

        tool = self.tools.get(tool_name)
        if not tool:
            content = ("Tool sconosciuto per questa richiesta." if lang == "it" else "Unknown tool for this request.")
            return TurnResult(content=content, action="tool", kb_mode="keep", reason="no tool")

        try:
            model = tool.validate(args or {})
            res = await tool.handler(model)
        except Exception as e:
            _print_terminal_error(f"[tool:{tool_name}] ERROR:", e)
            content = ("⚠️ Errore tool. Controlla il terminale." if lang == "it" else "⚠️ Tool error. Check terminal.")
            return TurnResult(content=content, action="tool", kb_mode="keep", reason="tool error")

        if not isinstance(res, dict):
            res = {"ok": True, "data": {"text": str(res)}, "error": None, "language": None}

        if not res.get("ok"):
            try:
                print(f"[tool:{tool_name}] FAIL: {res.get('error')}", file=sys.stderr)
            except Exception:
                pass
            content = ("⚠️ Operazione non riuscita." if lang == "it" else "⚠️ Operation failed.")
            return TurnResult(content=content, action="tool", kb_mode="keep", reason="tool fail")

        content = _render_tool_result(tool_name, res, lang)
        return TurnResult(content=content, action="tool", kb_mode="keep", reason="tool")

    async def _kb_query_answer(self, session, question: str, lang: str, status: StatusCb | None) -> TurnResult:
        retr = getattr(self.cfg, "retrieval", None)
        if retr and getattr(retr, "enabled", True) is False:
            return TurnResult(content="", action="chat", kb_mode="keep", reason="retrieval disabled")

        if not bool(_session_get(session, "kb_enabled", True)):
            return TurnResult(content="", action="chat", kb_mode="keep", reason="kb disabled")

        if status:
            await status("🔎 Searching KB…")

        self._ensure_tools()
        tool = self.tools.get("kb_query")
        if not tool:
            content = ("Tool KB mancante. Controlla il terminale." if lang == "it" else "KB tool missing. Check terminal.")
            return TurnResult(content=content, action="kb_query", kb_mode="keep", reason="kb tool missing")

        kb_name = _session_kb_name(session, self.cfg)
        top_k = int(getattr(getattr(self.cfg, "retrieval", None), "top_k", 4) or 4)

        try:
            model = tool.validate({"kb_name": kb_name, "query": question, "top_k": top_k})
            res = await tool.handler(model)
        except Exception as e:
            _print_terminal_error("[kb_query] ERROR:", e)
            content = ("⚠️ Errore retrieval. Controlla il terminale." if lang == "it" else "⚠️ Retrieval error. Check terminal.")
            return TurnResult(content=content, action="kb_query", kb_mode="keep", reason="kb error")

        if not isinstance(res, dict) or not res.get("ok"):
            content = ("Non trovato nei documenti indicizzati." if lang == "it" else "Not found in the indexed documents.")
            return TurnResult(content=content, action="kb_query", kb_mode="keep", reason="no hits", retrieval_hits=0)

        data = res.get("data") or {}
        context = (data.get("context") or "").strip()
        hits = int(data.get("hits") or 0)
        if not context:
            content = ("Non trovato nei documenti indicizzati." if lang == "it" else "Not found in the indexed documents.")
            return TurnResult(content=content, action="kb_query", kb_mode="keep", reason="no hits", retrieval_hits=0)

        quote = context.strip().replace("\n", " ")
        quote = (quote[:220] + "…") if len(quote) > 220 else quote

        if status:
            await status("💭 Thinking…")

        mm = make_memory_manager(self.cfg, session, self.workspace)
        mem = mm.read_memory().strip()
        summ = mm.read_summary().strip()
        tail = mm.read_history_tail(self.cfg.memory_limits.tail_lines).strip()

        memory_context = ""
        if mem and mem != "# Memory":
            memory_context += f"\nSESSION MEMORY:\n{mem}\n"
        if summ and summ != "# Session Summary":
            memory_context += f"\nSESSION SUMMARY:\n{summ}\n"
        if tail and tail != "# Session History":
            memory_context += f"\nRECENT HISTORY:\n{tail}\n"

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
            content = "⏱️ Local model timed out. Increase ollama.timeout_s."
            return TurnResult(content=content, action="kb_query", kb_mode="keep", reason="ollama timeout", retrieval_hits=hits)
        except OllamaProviderError as e:
            content = f"⚠️ Ollama error: {e}"
            return TurnResult(content=content, action="kb_query", kb_mode="keep", reason="ollama error", retrieval_hits=hits)

        answer = (resp.content or "").strip()
        if "\n> \"" not in answer:
            answer = f"{answer}\n\n> \"{quote}\""
        return TurnResult(content=answer, action="kb_query", kb_mode="keep", reason="kb_query", retrieval_hits=hits)

    async def one_turn(
        self,
        session,
        user_text: str,
        status: StatusCb | None = None,
        input_lang: str | None = None,
    ) -> TurnResult:
        mm = make_memory_manager(self.cfg, session, self.workspace)

        if status:
            await status("🧭 Routing…")

        lang = (input_lang or "").strip() or detect_language(user_text, default=getattr(self.cfg, "default_language", "it"))

        # deterministic ping
        if (user_text or "").strip().lower() == "ping":
            mm.append_turn("user", user_text)
            content = ping_reply(lang)
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="chat", kb_mode="keep", reason="very short")

        # deterministic remember
        item = _extract_remember_item(user_text)
        if item:
            mm.append_turn("user", user_text)
            mm.remember(item)
            content = "ok" if _wants_reply_only_ok(user_text) else f"✅ Saved: {item}"
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="chat", kb_mode="keep", reason="remember")

        # podcast trigger
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
                content = ("⚠️ Errore podcast. Controlla il terminale." if use_lang == "it" else "⚠️ Podcast error. Check terminal.")
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="podcast", kb_mode="keep", reason="podcast error")
            content = "✅ Podcast pronto." if use_lang == "it" else "✅ Podcast ready."
            if getattr(getattr(self.cfg, "podcast", None), "send_script_text", False):
                content += "\n\n" + (pr.script or "")
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="podcast", kb_mode="keep", reason="podcast", audio_path=pr.audio_path, script=pr.script)

        # record user turn
        mm.append_turn("user", user_text)

        # deterministic memory recall only for NON-questions
        mem_hit = mm.search_memory(user_text)
        if mem_hit and not _looks_like_question(user_text) and len((user_text or '').split()) <= 4:
            best_item, score, mode = mem_hit
            if mode == "key_rest":
                parts = best_item.split(None, 1)
                content = parts[1].strip() if len(parts) == 2 else best_item
            else:
                content = best_item
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="chat", kb_mode="keep", reason=f"memory match ({score:.2f})")

        # router source-of-truth
        state_file = getattr(session, "state_file", self.workspace / "state" / "router.json")
        try:
            r = json.loads(route_json_one_line(user_text, state_file, default_language=getattr(self.cfg, "default_language", "it")))
        except Exception:
            r = {"route": "chat"}

        route = (r.get("route") or "chat").strip()
        tool_name = (r.get("tool_name") or "").strip()
        args = r.get("args") if isinstance(r.get("args"), dict) else {}

        # build context (memory injected for LLM calls)
        mem = mm.read_memory().strip()
        summ = mm.read_summary().strip()
        tail = mm.read_history_tail(self.cfg.memory_limits.tail_lines).strip()

        memory_context = ""
        if mem and mem != "# Memory":
            memory_context += f"\nSESSION MEMORY:\n{mem}\n"
        if summ and summ != "# Session Summary":
            memory_context += f"\nSESSION SUMMARY:\n{summ}\n"
        if tail and tail != "# Session History":
            memory_context += f"\nRECENT HISTORY:\n{tail}\n"

        base_context = system_base_context(lang) + "\n"

        # tool route
        if route == "tool":
            # kb_query tool special-case -> uses _kb_query_answer (LLM with context)
            if tool_name == "kb_query":
                kb_res = await self._kb_query_answer(session, user_text, lang, status)
                if kb_res.content:
                    mm.append_turn("assistant", kb_res.content)
                    return kb_res
                route = "chat"  # kb disabled -> chat fallback

            # normalize youtube url
            if tool_name in {"yt_summary", "yt_transcript"}:
                url = args.get("url") or _extract_first_url(user_text) or user_text
                args = dict(args)
                args["url"] = url

            # normalize pdf ingest
            if tool_name == "kb_ingest_pdf":
                args = dict(args)
                if "pdf_path" not in args:
                    pdfp = _extract_pdf_path(user_text)
                    if pdfp:
                        args["pdf_path"] = pdfp
                        args.setdefault("doc_name", Path(pdfp).stem)
                args.setdefault("kb_name", _session_kb_name(session, self.cfg))

            res = await self._run_tool(tool_name, args, lang, status)
            mm.append_turn("assistant", res.content)
            return res

        # chat route
        if status:
            await status("💭 Thinking…")

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
