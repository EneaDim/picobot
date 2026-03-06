import pytest

from picobot.agent.agents.summarizer import SummarizerAgent
from picobot.providers.types import ChatResponse


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(
            content="""
{
  "items": [
    {
      "title": "Strategia europea sull'IA",
      "bullets": [
        "L'UE punta a sviluppare sistemi di IA affidabili.",
        "La strategia combina innovazione, ricerca e diritti fondamentali.",
        "Il quadro normativo europeo vuole favorire un'adozione responsabile."
      ],
      "source_url": "https://example.com/ai-eu"
    }
  ]
}
""",
            tool_calls=[],
        )


@pytest.mark.asyncio
async def test_news_summarizer_renders_structured_digest():
    agent = SummarizerAgent(DummyProvider())

    input_payload = {
        "query": "intelligenza artificiale europa",
        "items": [
            {
                "ok": True,
                "title": "Titolo sorgente",
                "url": "https://example.com/ai-eu",
                "snippet": "Snippet",
                "description": "Descrizione",
                "text": "Testo pulito della sorgente.",
            }
        ],
    }

    res = await agent.run(
        input_text=input_payload,
        lang="it",
        memory_ctx="",
        kind="news",
    )

    assert res.ok is True
    assert "### News Digest: intelligenza artificiale europa" in res.text
    assert "1. Strategia europea sull'IA" in res.text
    assert "   - L'UE punta a sviluppare sistemi di IA affidabili." in res.text
    assert "   Fonte: https://example.com/ai-eu" in res.text
