from __future__ import annotations

from pathlib import Path
import json

from picobot.agent.router import deterministic_route


def test_debug_router_dump(tmp_path: Path, capsys):
    state = tmp_path / "state.json"

    r1 = deterministic_route("verilator --trace in the doc", state)
    print("DEBUG route1:", r1.action, r1.kb_mode, r1.reason)

    r2 = deterministic_route("which formats?", state)
    print("DEBUG route2:", r2.action, r2.kb_mode, r2.reason)

    out = capsys.readouterr().out
    assert "DEBUG route1:" in out and "DEBUG route2:" in out
    # show a json-like snippet for humans too
    payload = {"action": r2.action, "kb_mode": r2.kb_mode, "reason": r2.reason}
    print("DEBUG route2 json:", json.dumps(payload))
