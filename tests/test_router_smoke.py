import json
from pathlib import Path

from picobot.agent.router import deterministic_route


def test_router_smoke(tmp_path: Path):
    state = tmp_path / "state.json"
    state.write_text(
        json.dumps({"kb_name": "default", "kb_enabled": True}),
        encoding="utf-8",
    )

    cases = [
        ("cerca nella kb come funziona il router", "kb_query"),
        ("nel documento, perché heartbeat non dovrebbe fare lavoro pesante direttamente?", "kb_query"),
        ("/news intelligenza artificiale europa", "news_digest"),
        ('tool python {"code":"print(2+2)"}', "python"),
        ("riassumi questo video https://youtu.be/ssYt09bCgUY", "youtube_summarizer"),
        ("ciao come stai?", "chat"),
    ]

    for text, expected_name in cases:
        decision = deterministic_route(text, state, default_language="it")
        assert decision.name == expected_name
