from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import pytest

from picobot.config.schema import Config
from picobot.session.manager import SessionManager
from picobot.agent.orchestrator import Orchestrator
from picobot.providers.types import ChatResponse


class DummyProvider:
    async def chat(self, messages, tools=None, max_tokens=0, temperature=0.0):
        return ChatResponse(content="SUMMARY_OK", tool_calls=[])


@pytest.mark.asyncio
async def test_tool_path_yt_summary_runs_without_network(tmp_path: Path):
    """
    Must not hit yt-dlp nor network.

    ToolSpec is frozen -> replace the registered ToolSpec with a new one having a fake handler.
    """
    cfg = Config(workspace=str(tmp_path))
    sm = SessionManager(tmp_path)
    s = sm.get("s1")

    orch = Orchestrator(cfg, DummyProvider(), tmp_path)
    orch._ensure_tools()

    orig = orch.tools.get("yt_transcript")
    assert orig is not None

    async def fake_transcript(args):
        return {
            "ok": True,
            "data": {"url": args.url, "transcript": "hello world transcript"},
            "error": None,
            "language": getattr(args, "lang", None),
        }

    patched = replace(orig, handler=fake_transcript)

    # ToolRegistry impl may not expose "replace", so we re-register by name.
    # Most registries overwrite by key; if it doesn't, we fallback to direct dict access.
    try:
        orch.tools.register(patched)
    except Exception:
        # fallback: best-effort overwrite
        try:
            orch.tools._tools[patched.name] = patched  # type: ignore[attr-defined]
        except Exception as e:
            raise AssertionError(f"Cannot patch yt_transcript tool in registry: {e}")

    r = await orch.one_turn(
        s,
        "summarize this youtube video: https://www.youtube.com/watch?v=abc",
        status=None,
    )

    assert r.action in ("workflow", "tool")
    assert "SUMMARY_OK" in r.content


@pytest.mark.asyncio
async def test_tool_path_kb_ingest_validates_pdf_path(tmp_path: Path):
    cfg = Config(workspace=str(tmp_path))
    sm = SessionManager(tmp_path)
    s = sm.get("s1")
    orch = Orchestrator(cfg, DummyProvider(), tmp_path)

    r = await orch.one_turn(s, "ingest pdf ./does-not-exist.pdf", status=None)
    assert r.action in ("tool", "workflow")
    assert "⚠️" in r.content or "error" in r.content.lower()
