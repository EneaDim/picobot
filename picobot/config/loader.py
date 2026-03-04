from __future__ import annotations

import json
from pathlib import Path

from picobot.config.schema import Config


def _normalize_config_dict(data: dict) -> dict:
    # Backward-compatible normalization:
    # - move old web.allowlist -> sandbox.web.whitelist_domains
    try:
        web = data.get("web") or {}
        if isinstance(web, dict) and "allowlist" in web:
            al = web.pop("allowlist") or []
            sb = data.setdefault("sandbox", {})
            sbw = sb.setdefault("web", {})
            if "whitelist_domains" not in sbw or not sbw["whitelist_domains"]:
                sbw["whitelist_domains"] = al
            data["web"] = web
    except Exception:
        pass
    return data

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
            data = _normalize_config_dict(data)
            return Config.model_validate(data)
    raise FileNotFoundError(
        "No config.json found. Create .picobot/config.json (project) or set PICOBOT_HOME."
    )
