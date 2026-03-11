from pathlib import Path
import json

from picobot.routing.deterministic import route_json_one_line


def test_route_json_uses_default_kb_when_state_has_no_kb(tmp_path: Path):
    state_file = tmp_path / "state.json"
    state_file.write_text(json.dumps({}), encoding="utf-8")

    payload = route_json_one_line(
        user_text="Quali sono i rischi operativi principali di Glass Orchard?",
        state_file=state_file,
        default_language="it",
    )

    assert '"context"' in payload
    assert '"kb_enabled":true' in payload
