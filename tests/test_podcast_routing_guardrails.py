from picobot.routing.router_policy import RouterPolicy
from picobot.routing.schemas import RouteCandidate, RouteRecord, SessionRouteContext


def _candidate(*, name: str, kind: str = "workflow", score: float = 0.8) -> RouteCandidate:
    return RouteCandidate(
        record=RouteRecord(
            id=f"{kind}:{name}",
            kind=kind,
            name=name,
            title=name,
            description=name,
        ),
        vector_score=score,
        lexical_score=score,
        rerank_score=0.0,
        final_score=score,
        reason="test",
    )


def test_normal_question_does_not_route_to_podcast():
    policy = RouterPolicy()
    ctx = SessionRouteContext(kb_name="default", kb_enabled=True, has_kb=True, input_lang="it")

    decision = policy.decide(
        user_text="Delta-Red è un sensore ottico?",
        candidates=[
            _candidate(name="podcast", score=0.95),
            _candidate(name="kb_query", score=0.90),
            _candidate(name="chat", score=0.60),
        ],
        ctx=ctx,
    )

    assert decision.name != "podcast"


def test_explicit_podcast_command_routes_to_podcast():
    policy = RouterPolicy()
    ctx = SessionRouteContext(kb_name="default", kb_enabled=True, has_kb=True, input_lang="it")

    decision = policy.decide(
        user_text="/podcast differenza tra event-driven systems e job schedulers",
        candidates=[
            _candidate(name="podcast", score=0.20),
            _candidate(name="chat", score=0.80),
        ],
        ctx=ctx,
    )

    assert decision.name == "podcast"
