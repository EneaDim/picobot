from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from picobot.agent.agents.base import AgentResult
from picobot.tools.registry import ToolRegistry

Mode = Literal["news", "search_only"]


@dataclass
class RetrieverAgent:
    tools: ToolRegistry
    name: str = "retriever"

    """
    Responsabilità:
    - recuperare evidence (deterministico)
    - NON riassumere
    Tooling:
    - news_digest (composite) oppure web_search
    """

    async def run(self, *, input_text: str, lang: str, memory_ctx: str, mode: Mode = "news") -> AgentResult:
        q = (input_text or "").strip()
        if not q:
            return AgentResult(name=self.name, ok=True, text="{}", data={"query": "", "items": []})

        if mode == "news":
            tool = self.tools.get("news_digest")
            if not tool:
                return AgentResult(name=self.name, ok=False, text="", data={"error": "news_digest tool missing"})
            model = tool.validate({"query": q, "count": 6, "fetch_chars": 12000})
            res = await tool.handler(model)
            if not res.get("ok"):
                return AgentResult(name=self.name, ok=False, text="", data={"error": res.get("error")})
            data = res.get("data") or {}
            return AgentResult(name=self.name, ok=True, text=json.dumps(data, ensure_ascii=False), data=data)

        tool = self.tools.get("web_search")
        if not tool:
            return AgentResult(name=self.name, ok=False, text="", data={"error": "web_search tool missing"})
        model = tool.validate({"query": q, "count": 6})
        res = await tool.handler(model)
        if not res.get("ok"):
            return AgentResult(name=self.name, ok=False, text="", data={"error": res.get("error")})
        data = res.get("data") or {}
        return AgentResult(name=self.name, ok=True, text=json.dumps(data, ensure_ascii=False), data=data)
