from __future__ import annotations

import json
from pathlib import Path

from picobot.config.schema import Config


def _candidate_paths() -> list[Path]:
    out: list[Path] = []
    # project-local first
    out.append(Path.cwd() / ".picobot" / "config.json")
    # user home fallback
    out.append(Path.home() / ".picobot" / "config.json")
    return out


def load_config() -> Config:
    for p in _candidate_paths():
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            return Config.model_validate(data)
    raise FileNotFoundError(
        "No config.json found. Create .picobot/config.json (project) or set PICOBOT_HOME."
    )
