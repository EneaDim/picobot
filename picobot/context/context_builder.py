from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

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

    Priorità applicata:
    1. recent dialogue priority block
    2. runtime context
    3. session state
    4. recent memory facts
    5. summary
    6. retrieval context
    7. history messages
    """

    def __init__(self, cfg: Config, workspace: Path) -> None:
        self.cfg = cfg
        self.workspace = Path(workspace).expanduser().resolve()

    def _repo(self, session: Session) -> MemoryRepository:
        return MemoryRepository(self.workspace, session)

    def _recent_priority_block(self, history_messages: list[dict[str, str]], *, max_items: int = 4) -> str:
        tail = history_messages[-max(0, max_items):]
        if not tail:
            return ""

        lines = ["PRIORITY RECENT DIALOGUE (prefer this over older memory when conflicting):"]
        for item in tail:
            role = str(item.get("role") or "").strip() or "unknown"
            content = str(item.get("content") or "").strip()
            if not content:
                continue
            lines.append(f"- {role}: {content}")
        return "\n".join(lines).strip()

    def _recent_facts(self, repo: MemoryRepository, *, limit: int = 8) -> list[str]:
        facts_store = repo.facts

        if hasattr(facts_store, "read_recent_items"):
            items = list(facts_store.read_recent_items(limit=limit))
            return [str(x).strip() for x in items if str(x).strip()]

        rows = []
        if hasattr(facts_store, "read_rows"):
            try:
                rows = list(facts_store.read_rows())
            except Exception:
                rows = []

        if rows:
            rows = sorted(
                rows,
                key=lambda row: str(row.get("updated_at") or ""),
                reverse=True,
            )
            items = [str(row.get("content") or "").strip() for row in rows]
            return [x for x in items if x][:limit]

        return [str(x).strip() for x in facts_store.read_items() if str(x).strip()][:limit]

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
        facts = self._recent_facts(repo, limit=8)
        session_state = repo.state.read()

        runtime_items = list(runtime_context or [])
        priority_block = self._recent_priority_block(history_messages, max_items=4)
        if priority_block:
            runtime_items = [priority_block, *runtime_items]

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
