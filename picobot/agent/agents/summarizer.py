from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from picobot.agent.agents.base import AgentResult
from picobot.agent.prompts import (
    youtube_summarizer_system,
    youtube_summarizer_user_prompt,
    news_summarizer_system,
    news_summarizer_user_prompt,
    system_base_context,
)
from picobot.providers.ollama import OllamaProvider


Kind = Literal["generic", "youtube", "news"]


@dataclass
class SummarizerAgent:
    provider: OllamaProvider
    name: str = "summarizer"

    """
    Responsabilità:
    - trasformare input (testo/evidence) in output finale (LLM)
    - niente tool CLI direttamente (provider è locale, non CLI)
    """

    async def run(self, *, input_text: str, lang: str, memory_ctx: str, kind: Kind = "generic") -> AgentResult:
        base = system_base_context(lang) + "\n" + (memory_ctx or "")

        if kind == "youtube":
            sys = youtube_summarizer_system()
            usr = youtube_summarizer_user_prompt(transcript=input_text, url="", lang=lang, max_chars=12000)
        elif kind == "news":
            sys = news_summarizer_system()
            usr = news_summarizer_user_prompt(lang=lang, query="", items=input_text, max_bullets=7)
        else:
            sys = system_base_context(lang)
            usr = input_text

        resp = await self.provider.chat(
            messages=[
                {"role": "system", "content": base + "\n" + sys},
                {"role": "user", "content": usr},
            ],
            tools=None,
            max_tokens=650,
            temperature=0.0,
        )
        out = (resp.content or "").strip()
        return AgentResult(name=self.name, ok=True, text=out, data={})
