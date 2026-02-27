from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from picobot.agent.router import deterministic_route, RouteDecision
from picobot.agent.memory import make_memory_manager
from picobot.retrieval.store import KBStore
from picobot.config.schema import Config
from picobot.providers.ollama import OllamaProvider, OllamaTimeout, OllamaProviderError

from picobot.tools.registry import ToolRegistry
from picobot.tools.youtube import make_yt_transcript_tool, make_yt_summary_tool
from picobot.tools.retrieval import make_kb_ingest_pdf_tool


StatusCb = Callable[[str], Awaitable[None]]


@dataclass
class TurnResult:
    content: str
    action: str
    kb_mode: str
    reason: str
    retrieval_hits: int = 0


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


class Orchestrator:
    def __init__(self, cfg: Config, provider: OllamaProvider, workspace: Path) -> None:
        self.cfg = cfg
        self.provider = provider
        self.workspace = Path(workspace)
        self.docs_root = self.workspace / "docs"
        self.docs_root.mkdir(parents=True, exist_ok=True)

        self.tools = ToolRegistry()

    def _register_tools(self) -> None:
        # idempotent (tests may monkeypatch factories after Orchestrator init)
        ytdlp_bin = getattr(self.cfg.tools, "ytdlp_bin", "") if hasattr(self.cfg, "tools") else ""
        ytdlp_args = getattr(self.cfg.tools, "ytdlp_args", None) if hasattr(self.cfg, "tools") else None
        ytdlp_args = ytdlp_args or []

        async def llm_summarize(transcript: str, url: str, lang: str | None):
            prompt = (
                "Summarize this YouTube transcript.\n"
                "Return:\n"
                "- 5 bullet key points\n"
                "- 1 short paragraph summary\n"
                "Keep it concise.\n"
            )
            if lang:
                prompt += f"Write in language: {lang}\n"

            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": "You are a concise technical summarizer."},
                    {"role": "user", "content": f"URL: {url}\n\nTRANSCRIPT:\n{transcript}\n\n{prompt}"},
                ],
                tools=None,
                max_tokens=700,
            )
            return (resp.content or "").strip()

        for tool in [
            make_yt_transcript_tool(ytdlp_bin, ytdlp_args=ytdlp_args),
            make_yt_summary_tool(ytdlp_bin, llm_summarize, ytdlp_args=ytdlp_args),
            make_kb_ingest_pdf_tool(self.docs_root),
        ]:
            try:
                self.tools.register(tool)
            except Exception:
                pass

    def _ensure_tools(self) -> None:
        if self.tools.list():
            return
        self._register_tools()

    async def one_turn(self, session, user_text: str, status: StatusCb | None = None) -> TurnResult:
        mm = make_memory_manager(self.cfg, session, self.workspace)

        if status:
            await status("🧭 Routing…")

        # deterministic ping
        if (user_text or "").strip().lower() == "ping":
            mm.append_turn("user", user_text)
            content = "Pong! How can I assist you today?"
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

        # routing
        decision: RouteDecision = deterministic_route(user_text, session.state_file)
        mm.append_turn("user", user_text)

        # deterministic memory recall (general)
        mem_hit = mm.search_memory(user_text)
        if mem_hit:
            best_item, score, mode = mem_hit
            if mode == "key_rest":
                parts = best_item.split(None, 1)
                content = parts[1].strip() if len(parts) == 2 else best_item
            else:
                content = best_item
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="chat", kb_mode="keep", reason=f"memory match ({score:.2f})")

        # prompt context
        mem = mm.read_memory().strip()
        summ = mm.read_summary().strip()
        tail = mm.read_history_tail(self.cfg.memory_limits.tail_lines).strip()

        base_context = (
            "You are picobot (a small nanobot-style assistant).\n"
            "SESSION MEMORY is authoritative and must be used for continuity.\n"
            "Do not invent memories.\n"
        )
        memory_context = ""
        if mem and mem != "# Memory":
            memory_context += f"\nSESSION MEMORY:\n{mem}\n"
        if summ and summ != "# Session Summary":
            memory_context += f"\nSESSION SUMMARY:\n{summ}\n"
        if tail and tail != "# Session History":
            memory_context += f"\nRECENT HISTORY:\n{tail}\n"

        # TOOL path
        if decision.action == "tool":
            self._ensure_tools()
            if status:
                await status("🛠 Tool…")

            st = session.get_state() or {}
            tool_name = (st.get("last_tool") or "").strip()

            # fallback inference
            low = (user_text or "").lower()
            if not tool_name:
                if "youtube.com" in low or "youtu.be" in low:
                    tool_name = "yt_summary"
                elif ".pdf" in low and ("ingest" in low or "import" in low or "add" in low):
                    tool_name = "kb_ingest_pdf"

            try:
                tool = self.tools.get(tool_name)
            except Exception:
                content = "Unknown tool for this request."
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="tool", kb_mode="keep", reason="no tool")

            args = {}
            if tool_name in {"yt_transcript", "yt_summary"}:
                url = _extract_first_url(user_text)
                if not url:
                    content = "Missing YouTube URL."
                    mm.append_turn("assistant", content)
                    return TurnResult(content=content, action="tool", kb_mode="keep", reason="missing url")
                args = {"url": url}
            elif tool_name == "kb_ingest_pdf":
                pdfp = _extract_pdf_path(user_text)
                if not pdfp:
                    content = "Missing .pdf path. Example: ingest pdf ./docs/file.pdf"
                    mm.append_turn("assistant", content)
                    return TurnResult(content=content, action="tool", kb_mode="keep", reason="missing pdf")
                kb_name = (session.get_state() or {}).get("kb_name", getattr(self.cfg, "default_kb_name", "default"))
                args = {"kb_name": kb_name, "pdf_path": pdfp, "doc_name": Path(pdfp).stem}

            try:
                model = tool.validate(args)
                data = await tool.handler(model)
            except Exception as e:
                content = f"⚠️ Tool error ({tool.name}): {e}"
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="tool", kb_mode="keep", reason="tool error")

            if tool.name == "yt_transcript":
                t = data.get("transcript", "")
                content = t[:4000] + ("…" if len(t) > 4000 else "")
            elif tool.name == "yt_summary":
                content = (data.get("summary", "") or "").strip() or "(empty)"
            elif tool.name == "kb_ingest_pdf":
                content = f"✅ Ingested into KB '{data.get('kb_name')}': {data.get('doc',{})}"
            else:
                content = str(data)

            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="tool", kb_mode="keep", reason=decision.reason)

        # KB query path (strict, no fallback)
        if decision.action == "kb_query" and self.cfg.retrieval.enabled:
            if status:
                await status("🔎 Searching KB…")

            kb_name = (session.get_state() or {}).get("kb_name", getattr(self.cfg, "default_kb_name", "default"))
            kb_dir = self.docs_root / kb_name / "kb"
            kb = KBStore(kb_dir)
            idx = kb.load_index()

            if not idx:
                content = "No documents are indexed for this KB yet. Ingest PDFs first (tool: kb_ingest_pdf)."
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="kb_query", kb_mode=decision.kb_mode, reason="no index", retrieval_hits=0)

            scored = sorted(idx.score(user_text), key=lambda x: x[1], reverse=True)
            top = [(cid, s) for cid, s in scored if s > 0][: self.cfg.retrieval.top_k]
            if not top:
                content = "Not found in the indexed documents."
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="kb_query", kb_mode=decision.kb_mode, reason="no hits", retrieval_hits=0)

            context = "\n\n".join([kb.read_chunk(cid) for cid, _ in top])
            first_chunk = kb.read_chunk(top[0][0])
            quote = first_chunk.strip().replace("\n", " ")
            quote = (quote[:220] + "…") if len(quote) > 220 else quote

            if status:
                await status("💭 Thinking…")

            try:
                resp = await self.provider.chat(
                    messages=[
                        {"role": "system", "content": base_context + memory_context},
                        {"role": "user", "content": (
                            "Answer using ONLY DOCUMENT CONTEXT. If the answer is not in the context, say not found.\n\n"
                            f"QUESTION:\n{user_text}\n\n"
                            f"DOCUMENT CONTEXT:\n{context}\n"
                        )},
                    ],
                    tools=None,
                    max_tokens=650,
                )
            except OllamaTimeout:
                content = "⏱️ Local model timed out. Increase ollama.timeout_s."
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="kb_query", kb_mode=decision.kb_mode, reason="ollama timeout", retrieval_hits=len(top))
            except OllamaProviderError as e:
                content = f"⚠️ Ollama error: {e}"
                mm.append_turn("assistant", content)
                return TurnResult(content=content, action="kb_query", kb_mode=decision.kb_mode, reason="ollama error", retrieval_hits=len(top))

            content = (resp.content or "").strip()
            # sanitize prompt-echo (some models repeat the user prompt/context)
            for marker in ["DOCUMENT CONTEXT:", "QUESTION:"]:
                if marker in content:
                    content = content.split(marker, 1)[0].strip()

            if "\n> \"" not in content:
                content = f"{content}\n\n> \"{quote}\""

            mm.append_turn("assistant", content)
            return TurnResult(content=content, action="kb_query", kb_mode=decision.kb_mode, reason=decision.reason, retrieval_hits=len(top))

        # Chat path
        if status:
            await status("💭 Thinking…")

        try:
            resp = await self.provider.chat(
                messages=[
                    {"role": "system", "content": base_context + memory_context},
                    {"role": "user", "content": user_text},
                ],
                tools=None,
                max_tokens=700,
            )
        except OllamaTimeout:
            content = "⏱️ Local model timed out. Increase ollama.timeout_s."
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action=decision.action, kb_mode=decision.kb_mode, reason="ollama timeout", retrieval_hits=0)
        except OllamaProviderError as e:
            content = f"⚠️ Ollama error: {e}"
            mm.append_turn("assistant", content)
            return TurnResult(content=content, action=decision.action, kb_mode=decision.kb_mode, reason="ollama error", retrieval_hits=0)

        content = (resp.content or "").strip() or "(empty)"
        mm.append_turn("assistant", content)
        return TurnResult(content=content, action=decision.action, kb_mode=decision.kb_mode, reason=decision.reason, retrieval_hits=0)
