from __future__ import annotations

import json
from pathlib import Path

from picobot.agent.router import deterministic_route


def test_debug_router_dump(tmp_path: Path):
    state = tmp_path / "state.json"

    r1 = deterministic_route("kb question", state)
    r2 = deterministic_route("more detail", state)

    print("DEBUG route1:", r1.workflow, r1.reason)
    print("DEBUG route2:", r2.workflow, r2.reason)

    payload = {"workflow": r2.workflow, "reason": r2.reason}
    dumped = json.dumps(payload)
    assert "workflow" in dumped
