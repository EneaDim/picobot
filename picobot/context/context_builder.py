from __future__ import annotations

from pathlib import Path

from picobot.agent.prompts import system_base_context
from picobot.config.schema import Config
from picobot.context.model_context import ModelContext
from picobot.memory.stores import MemoryRepository
from picobot.session.manager import Session


class ContextBuilder:
    """
    Costruisce in modo esplicito il contesto per il modello.

    Layer supportati:
    1. session state
    2. history
    3. summary
    4. memory facts
    5. retrieval context
    6. runtime context
    """

    def __init__(self, cfg: Config, workspace: Path) -> None:
        self.cfg = cfg
        self.workspace = Path(workspace).expanduser().resolve()

    def _repo(self, session: Session) -> MemoryRepository:
        return MemoryRepository(self.workspace, session)

    def build(
        self,
        *,
        session: Session,
        lang: str,
        retrieval_context: str = "",
        runtime_context: list[str] | None = None,
        history_turns: int = 8,
    ) -> ModelContext:
        repo = self._repo(session)
        history_messages = repo.history.read_recent_messages(limit=max(0, history_turns) * 2)
        summary = repo.summary.read_text()
        facts = repo.facts.read_items()
        session_state = repo.state.read()

        return ModelContext(
            system_prompt=system_base_context(lang),
            session_state=session_state,
            runtime_context=list(runtime_context or []),
            summary_text=summary,
            memory_facts=facts,
            retrieval_context=retrieval_context,
            history_messages=history_messages,
        )

    def render_legacy_memory_block(
        self,
        *,
        session: Session,
        lang: str,
        retrieval_context: str = "",
        runtime_context: list[str] | None = None,
        history_turns: int = 8,
    ) -> str:
        ctx = self.build(
            session=session,
            lang=lang,
            retrieval_context=retrieval_context,
            runtime_context=runtime_context,
            history_turns=history_turns,
        )
        return ctx.render_supporting_context()

    def build_messages(
        self,
        *,
        session: Session,
        lang: str,
        user_text: str,
        retrieval_context: str = "",
        runtime_context: list[str] | None = None,
        history_turns: int = 8,
    ) -> list[dict[str, str]]:
        ctx = self.build(
            session=session,
            lang=lang,
            retrieval_context=retrieval_context,
            runtime_context=runtime_context,
            history_turns=history_turns,
        )
        return ctx.to_messages(user_text=user_text)
