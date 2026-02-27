from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pytest

from picobot.config.schema import Config
from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse


class FixedProvider:
    def __init__(self, content: str):
        self.content = content
        self.calls = 0

    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        self.calls += 1
        return ChatResponse(content=self.content, tool_calls=[])


@dataclass
class FakeIndex:
    mapping: dict[str, list[tuple[str, float]]]

    def score(self, query: str):
        q = (query or "").lower()
        for k, v in self.mapping.items():
            if k in q:
                return v
        return []


class FakeKBStore:
    def __init__(self, root: Path, index: FakeIndex | None, chunks: dict[str, str]):
        self.root = root
        self._index = index
        self._chunks = chunks

    def load_index(self):
        return self._index

    def read_chunk(self, cid: str) -> str:
        return self._chunks.get(cid, "")


@pytest.mark.asyncio
async def test_e2e_kb_query_appends_quote_when_hits(tmp_path: Path, monkeypatch):
    import picobot.agent.orchestrator as orch_mod

    cfg = Config(workspace=str(tmp_path))
    cfg.retrieval.enabled = True
    cfg.retrieval.top_k = 2

    sm = SessionManager(tmp_path)
    s = sm.get("s1")

    chunks = {
        "c1": "--trace: Generate a waveform dump during simulation.\nOutput is VCD.\n",
        "c2": "More details about tracing formats.\n",
    }
    index = FakeIndex(mapping={"verilator": [("c1", 10.0), ("c2", 7.0)]})

    monkeypatch.setattr(orch_mod, "KBStore", lambda root: FakeKBStore(root, index=index, chunks=chunks))

    provider = FixedProvider("Verilator --trace enables waveform dumps.")
    orch = Orchestrator(cfg, provider, tmp_path)

    # ensure kb_name is set so kb_dir resolves
    s.set_state({"kb_name": "verilator"})

    r = await orch.one_turn(s, "Nel doc verilator dove si parla di --trace? Riporta anche una breve citazione.", status=None)
    assert r.action == "kb_query"
    assert r.retrieval_hits > 0
    assert "\n> \"" in r.content
    assert "--trace" in r.content


@pytest.mark.asyncio
async def test_e2e_kb_followup_sticks_to_kb_query(tmp_path: Path, monkeypatch):
    import picobot.agent.orchestrator as orch_mod

    cfg = Config(workspace=str(tmp_path))
    cfg.retrieval.enabled = True
    cfg.retrieval.top_k = 1

    sm = SessionManager(tmp_path)
    s = sm.get("s1")
    s.set_state({"kb_name": "default"})

    chunks = {"c1": "Trace formats: VCD is supported.\n"}
    index = FakeIndex(mapping={"trace": [("c1", 10.0)], "formats": [("c1", 9.0)]})
    monkeypatch.setattr(orch_mod, "KBStore", lambda root: FakeKBStore(root, index=index, chunks=chunks))

    provider = FixedProvider("Answer from docs.")
    orch = Orchestrator(cfg, provider, tmp_path)

    r1 = await orch.one_turn(s, "Nel doc verilator dove si parla di --trace?", status=None)
    assert r1.action == "kb_query"

    r2 = await orch.one_turn(s, "which formats?", status=None)
    assert r2.action == "kb_query"
    assert r2.retrieval_hits > 0


@pytest.mark.asyncio
async def test_e2e_kb_no_index_never_quotes(tmp_path: Path, monkeypatch):
    import picobot.agent.orchestrator as orch_mod

    cfg = Config(workspace=str(tmp_path))
    cfg.retrieval.enabled = True

    sm = SessionManager(tmp_path)
    s = sm.get("s1")
    s.set_state({"kb_name": "default"})

    monkeypatch.setattr(orch_mod, "KBStore", lambda root: FakeKBStore(root, index=None, chunks={}))

    provider = FixedProvider("SHOULD NOT MATTER")
    orch = Orchestrator(cfg, provider, tmp_path)

    r = await orch.one_turn(s, "Nel doc verilator dove si parla di --trace?", status=None)
    assert r.action == "kb_query"
    assert r.retrieval_hits == 0
    assert "\n> \"" not in r.content
