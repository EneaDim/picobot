import json
from pathlib import Path

from picobot.tools.init_tools import resolve_config_path


def test_resolve_config_path_prefers_local_file(tmp_path: Path, monkeypatch):
    cfg_dir = tmp_path / ".picobot"
    cfg_dir.mkdir(parents=True, exist_ok=True)

    cfg_path = cfg_dir / "config.json"
    cfg_path.write_text(json.dumps({"sandbox": {"runtime": {"docker": {"image": "picobot-sandbox:latest"}}}}), encoding="utf-8")

    monkeypatch.chdir(tmp_path)

    resolved = resolve_config_path(None)
    assert resolved == cfg_path.resolve()
