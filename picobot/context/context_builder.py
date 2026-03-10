from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from picobot.prompts import system_base_context
from picobot.config.schema import Config
from picobot.context.model_context import ModelContext
from picobot.memory.stores import MemoryRepository
from picobot.session.manager import Session


@dataclass(slots=True)
class ContextAssembly:
    model_context: ModelContext
    history_messages_count: int
    memory_facts_count: int
    summary_present: bool
    retrieval_present: bool
    runtime_context_count: int
    history_turns_requested: int


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

    def build_assembly(
        self,
        *,
        session: Session,
        lang: str,
        retrieval_context: str = "",
        runtime_context: list[str] | None = None,
        history_turns: int = 8,
    ) -> ContextAssembly:
        repo = self._repo(session)

        safe_history_turns = max(0, int(history_turns))
        history_messages = repo.history.read_recent_messages(limit=safe_history_turns * 2)
        summary = repo.summary.read_text()
        facts = repo.facts.read_items()
        session_state = repo.state.read()
        runtime_items = list(runtime_context or [])

        model_context = ModelContext(
            system_prompt=system_base_context(lang),
            session_state=session_state,
            runtime_context=runtime_items,
            summary_text=summary,
            memory_facts=facts,
            retrieval_context=retrieval_context,
            history_messages=history_messages,
        )

        return ContextAssembly(
            model_context=model_context,
            history_messages_count=len(history_messages),
            memory_facts_count=len(facts),
            summary_present=bool((summary or "").strip()),
            retrieval_present=bool((retrieval_context or "").strip()),
            runtime_context_count=len(runtime_items),
            history_turns_requested=safe_history_turns,
        )

    def build(
        self,
        *,
        session: Session,
        lang: str,
        retrieval_context: str = "",
        runtime_context: list[str] | None = None,
        history_turns: int = 8,
    ) -> ModelContext:
        return self.build_assembly(
            session=session,
            lang=lang,
            retrieval_context=retrieval_context,
            runtime_context=runtime_context,
            history_turns=history_turns,
        ).model_context

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
