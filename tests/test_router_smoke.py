from types import SimpleNamespace

from picobot.routing.router_policy import RouterPolicy


def _candidate(
    *,
    name: str,
    kind: str,
    score: float,
    requires_kb: bool = False,
    record_id: str | None = None,
):
    record = SimpleNamespace(
        id=record_id or f"{kind}:{name}",
        name=name,
        kind=kind,
        requires_kb=requires_kb,
    )
    return SimpleNamespace(
        record=record,
        score=score,
        final_score=score,
        combined_score=score,
    )


def _ctx(*, kb_enabled: bool = True, has_kb: bool = True):
    return SimpleNamespace(
        session_id="default",
        kb_name="default",
        kb_enabled=kb_enabled,
        has_kb=has_kb,
        default_language="it",
    )


def test_router_policy_smoke():
    policy = RouterPolicy()

    cases = [
        {
            "text": "cerca nella kb come funziona il router",
            "candidates": [
                _candidate(name="kb_query", kind="workflow", score=0.95, requires_kb=True),
                _candidate(name="chat", kind="workflow", score=0.20),
            ],
            "expected": "kb_query",
        },
        {
            "text": "nel documento, perché heartbeat non dovrebbe fare lavoro pesante direttamente?",
            "candidates": [
                _candidate(name="kb_query", kind="workflow", score=0.91, requires_kb=True),
                _candidate(name="chat", kind="workflow", score=0.25),
            ],
            "expected": "kb_query",
        },
        {
            "text": "/news intelligenza artificiale europa",
            "candidates": [],
            "expected": "news_digest",
        },
        {
            "text": 'tool python {"code":"print(2+2)"}',
            "candidates": [],
            "expected": "python",
        },
        {
            "text": "riassumi questo video https://youtu.be/ssYt09bCgUY",
            "candidates": [],
            "expected": "youtube_summarizer",
        },
        {
            "text": "ciao",
            "candidates": [],
            "expected": "chat",
        },
        {
            "text": "write me a cat terminal command to write what you actually wrote about os library in a markdown file",
            "candidates": [
                _candidate(name="stt", kind="tool", score=0.98),
                _candidate(name="kb_query", kind="workflow", score=0.93, requires_kb=True),
                _candidate(name="chat", kind="workflow", score=0.30),
            ],
            "expected": "chat",
        },
        {
            "text": "trascrivi questo audio per favore",
            "candidates": [
                _candidate(name="stt", kind="tool", score=0.99),
                _candidate(name="chat", kind="workflow", score=0.20),
            ],
            "expected": "chat",
        },
    ]

    for case in cases:
        decision = policy.decide(
            user_text=case["text"],
            candidates=case["candidates"],
            ctx=_ctx(),
        )
        assert decision.name == case["expected"], case["text"]
