from __future__ import annotations

from pathlib import Path
from picobot.config.schema import Config


def workspace_path(cfg: Config) -> Path:
    ws = Path(cfg.workspace)
    if not ws.is_absolute():
        ws = (Path.cwd() / ws).resolve()
    ws.mkdir(parents=True, exist_ok=True)
    return ws
