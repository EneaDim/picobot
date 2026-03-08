from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ModelContext:
    system_prompt: str
    session_state: dict[str, Any] = field(default_factory=dict)
    runtime_context: list[str] = field(default_factory=list)
    summary_text: str = ""
    memory_facts: list[str] = field(default_factory=list)
    retrieval_context: str = ""
    history_messages: list[dict[str, str]] = field(default_factory=list)

    def render_supporting_context(self) -> str:
        parts: list[str] = []

        if self.runtime_context:
            parts.append(
                "RUNTIME CONTEXT:\n"
                + "\n".join(f"- {item}" for item in self.runtime_context if str(item).strip())
            )

        if self.session_state:
            visible_state = {
                key: value
                for key, value in self.session_state.items()
                if key not in {"last_audio_path"}
            }
            if visible_state:
                lines = [f"- {key}: {value}" for key, value in visible_state.items()]
                parts.append("SESSION STATE:\n" + "\n".join(lines))

        summary = (self.summary_text or "").strip()
        if summary:
            parts.append("SESSION SUMMARY:\n" + summary)

        facts = [str(item).strip() for item in self.memory_facts if str(item).strip()]
        if facts:
            parts.append("MEMORY FACTS:\n" + "\n".join(f"- {item}" for item in facts))

        retrieval = (self.retrieval_context or "").strip()
        if retrieval:
            parts.append("RETRIEVAL CONTEXT:\n" + retrieval)

        return "\n\n".join(parts).strip()

    def system_message(self) -> dict[str, str]:
        support = self.render_supporting_context()
        content = self.system_prompt.strip()
        if support:
            content = f"{content}\n\n{support}".strip()
        return {"role": "system", "content": content}

    def to_messages(self, *, user_text: str) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = [self.system_message()]
        messages.extend(self.history_messages)
        messages.append({"role": "user", "content": (user_text or "").strip()})
        return messages
