from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any


def _config_path() -> Path:
    raw = os.environ.get("PICOBOT_CONFIG", ".picobot/config.json")
    return Path(raw).expanduser().resolve()


@lru_cache(maxsize=1)
def load_runtime_config() -> dict[str, Any]:
    p = _config_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def cfg_get(path: str, default: Any = None) -> Any:
    cur: Any = load_runtime_config()
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur
