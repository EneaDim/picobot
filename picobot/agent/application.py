from __future__ import annotations

from pathlib import Path

from picobot.agent.memory_context_service import MemoryContextService
from picobot.prompts import detect_language, system_base_context
from picobot.agent.route_selection import RouteSelectionService
from picobot.agent.models import HookCb, RuntimeHooks, StatusCb, TurnResult
from picobot.agent.tool_executor import ToolExecutor
from picobot.agent.turn_processor import TurnProcessor
from picobot.agent.workflow_dispatcher import WorkflowDispatcher
from picobot.config.schema import Config
from picobot.context import ContextBuilder
from picobot.providers.ollama import OllamaProvider
from picobot.session.manager import Session
from picobot.tools.file import make_file_tool
from picobot.tools.news_digest import make_news_digest_tool
from picobot.tools.paths import get_runtime_tool_bin
from picobot.tools.python import make_python_tool
from picobot.tools.registry import ToolRegistry
from picobot.tools.retrieval import make_kb_ingest_pdf_tool, make_kb_query_tool
from picobot.tools.stt import make_stt_tool
from picobot.tools.tts import make_tts_tool
from picobot.tools.web import make_web_tool
from picobot.tools.web_search import make_web_search_tool
from picobot.tools.youtube import make_yt_summary_tool, make_yt_transcript_tool


class Orchestrator:
    """
    Facade compatibile sopra servizi separati.

    Ownership reale spostata verso:
    - RouteSelectionService
    - ToolExecutor
    - MemoryContextService
    - TurnProcessor
    - WorkflowDispatcher

    Questo riduce il coupling senza rompere l'API corrente del repo.
    """

    def __init__(self, cfg: Config, provider: OllamaProvider, workspace: Path) -> None:
        self.cfg = cfg
        self.provider = provider
        self.workspace = Path(workspace).expanduser().resolve()
        self.docs_root = self.workspace / "docs"
        self.docs_root.mkdir(parents=True, exist_ok=True)

        self.tools = ToolRegistry()
        self.context_builder = ContextBuilder(cfg, self.workspace)

        self._register_tools()

        self.route_selector = RouteSelectionService(
            default_language=self.cfg.default_language
        )
        self.tool_executor = ToolExecutor(self)
        self.memory_context_service = MemoryContextService(self)
        self.workflow_dispatcher = WorkflowDispatcher(self)
        self.turn_processor = TurnProcessor(self)

    async def _emit_hook(self, hook: HookCb | None, payload: dict) -> None:
        if hook is None:
            return
        await hook(payload)

    def _register_tools(self) -> None:
        if self.tools.list():
            return

        ytdlp_bin = get_runtime_tool_bin(self.cfg, "ytdlp", "yt-dlp")
        youtube_cfg = getattr(self.cfg.tools, "youtube", None)
        ytdlp_args = list(getattr(youtube_cfg, "ytdlp_args", []) or [])

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
            make_python_tool(self.cfg),
            make_file_tool(self.cfg),
            make_web_tool(self.cfg),
            make_web_search_tool(self.cfg, self.workspace),
            make_news_digest_tool(self.cfg, self.workspace),
            make_yt_transcript_tool(ytdlp_bin, ytdlp_args=ytdlp_args),
            make_yt_summary_tool(ytdlp_bin, _llm_summarize, ytdlp_args=ytdlp_args),
            make_stt_tool(self.cfg),
            make_tts_tool(self.cfg),
        ]

        for spec in tool_specs:
            self.tools.register(spec)

    def _append_turn_memory(self, session: Session, user_text: str, assistant_text: str) -> None:
        self.memory_context_service.append_turn_memory(session, user_text, assistant_text)

    def _store_audio_state(self, session: Session, audio_path: str | None) -> None:
        self.memory_context_service.store_audio_state(session, audio_path)

    async def _run_tool(
        self,
        tool_name: str,
        args: dict,
        *,
        hooks: RuntimeHooks | None = None,
        workflow_name: str | None = None,
    ) -> dict:
        return await self.tool_executor.execute(
            tool_name,
            args,
            hooks=hooks,
            workflow_name=workflow_name,
        )

    async def _call_tool(
        self,
        tool_name: str,
        args: dict,
        *,
        hooks: RuntimeHooks | None = None,
        workflow_name: str | None = None,
    ) -> dict:
        """
        Backward-compatible seam.

        Alcuni test monkeypatchano ancora _run_tool(tool_name, args).
        """
        try:
            return await self._run_tool(
                tool_name,
                args,
                hooks=hooks,
                workflow_name=workflow_name,
            )
        except TypeError:
            return await self._run_tool(tool_name, args)  # type: ignore[misc]

    async def _run_explicit_tool(
        self,
        *,
        session: Session,
        lang: str,
        tool_name: str,
        args: dict,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.workflow_dispatcher.explicit_tool(
            session=session,
            lang=lang,
            tool_name=tool_name,
            args=args,
            hooks=hooks,
        )

    async def _chat(
        self,
        *,
        session: Session,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.workflow_dispatcher.chat(
            session=session,
            user_text=user_text,
            lang=lang,
            status=status,
            hooks=hooks,
        )

    async def _workflow_kb_query(
        self,
        *,
        session: Session,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.workflow_dispatcher.kb_query(
            session=session,
            user_text=user_text,
            lang=lang,
            status=status,
            hooks=hooks,
        )

    async def _workflow_news_digest(
        self,
        *,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.workflow_dispatcher.news_digest(
            user_text=user_text,
            lang=lang,
            status=status,
            hooks=hooks,
        )

    async def _workflow_youtube(
        self,
        *,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.workflow_dispatcher.youtube_summarizer(
            user_text=user_text,
            lang=lang,
            status=status,
            hooks=hooks,
        )

    async def _workflow_podcast(
        self,
        *,
        session: Session,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.workflow_dispatcher.podcast(
            session=session,
            user_text=user_text,
            lang=lang,
            status=status,
            hooks=hooks,
        )

    async def _dispatch_workflow(
        self,
        *,
        session: Session,
        workflow_name: str,
        user_text: str,
        lang: str,
        status: StatusCb | None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.workflow_dispatcher.dispatch(
            session=session,
            workflow_name=workflow_name,
            user_text=user_text,
            lang=lang,
            status=status,
            hooks=hooks,
        )

    async def one_turn(
        self,
        *,
        session: Session,
        user_text: str,
        status: StatusCb | None = None,
        hooks: RuntimeHooks | None = None,
    ) -> TurnResult:
        return await self.turn_processor.process(
            session=session,
            user_text=user_text,
            status=status,
            hooks=hooks,
        )
