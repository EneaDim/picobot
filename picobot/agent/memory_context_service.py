from __future__ import annotations

from picobot.agent.memory import make_memory_manager
from picobot.context import ContextAssembly
from picobot.session.manager import Session


class MemoryContextService:
    """
    Boundary dedicato per:
    - append della history turn-based
    - state update di runtime (es. ultimo audio)
    - context assembly per il modello

    Questo sposta fuori da TurnProcessor / WorkflowDispatcher
    la conoscenza diretta della persistenza memoria e del context builder.
    """

    def __init__(self, orchestrator) -> None:
        self.orchestrator = orchestrator

    def append_turn_memory(self, session: Session, user_text: str, assistant_text: str) -> None:
        mm = make_memory_manager(self.orchestrator.cfg, session, self.orchestrator.workspace)
        mm.init_files()
        mm.append_turn("user", user_text)
        mm.append_turn("assistant", assistant_text)

    def store_audio_state(self, session: Session, audio_path: str | None) -> None:
        if audio_path and str(audio_path).strip():
            session.set_state({"last_audio_path": str(audio_path).strip()})

    def build_context_assembly(
        self,
        *,
        session: Session,
        lang: str,
        retrieval_context: str = "",
        runtime_context: list[str] | None = None,
        history_turns: int = 8,
    ) -> ContextAssembly:
        return self.orchestrator.context_builder.build_assembly(
            session=session,
            lang=lang,
            retrieval_context=retrieval_context,
            runtime_context=runtime_context,
            history_turns=history_turns,
        )
