from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from picobot.config.schema import Config
from picobot.runtime_config import set_runtime_config


def _candidate_paths(explicit_path: str | Path | None = None) -> list[Path]:
    out: list[Path] = []

    if explicit_path is not None:
        out.append(Path(explicit_path).expanduser())

    env_path = os.environ.get("PICOBOT_CONFIG", "").strip()
    if env_path:
        out.append(Path(env_path).expanduser())

    out.extend([
        Path(".picobot/config.json"),
        Path("picobot.config.json"),
        Path("config.json"),
        Path.home() / ".picobot" / "config.json",
    ])

    seen: set[str] = set()
    unique: list[Path] = []

    for p in out:
        rp = str(p.expanduser())
        if rp not in seen:
            seen.add(rp)
            unique.append(p)

    return unique


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config file is not a JSON object: {path}")
    return data


def _normalize_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)

    # web.allowlist -> sandbox.web.whitelist_domains
    try:
        web = data.get("web") or {}
        if isinstance(web, dict) and "allowlist" in web:
            allowlist = list(web.get("allowlist") or [])
            sandbox = dict(data.get("sandbox") or {})
            sb_web = dict(sandbox.get("web") or {})
            if not sb_web.get("whitelist_domains"):
                sb_web["whitelist_domains"] = allowlist
            sandbox["web"] = sb_web
            data["sandbox"] = sandbox
    except Exception:
        pass

    # legacy top-level web -> web_search
    if "web_search" not in data:
        legacy_web = data.get("web")
        if isinstance(legacy_web, dict):
            data["web_search"] = {
                "enabled": legacy_web.get("enabled", True),
                "backend": "searxng",
                "searxng_url": legacy_web.get("searxng_url", "http://localhost:8080"),
                "timeout_s": legacy_web.get("timeout_s", 10.0),
                "max_results": legacy_web.get("max_results", 5),
                "managed_backend": legacy_web.get("managed_searxng", True),
                "health_timeout_s": legacy_web.get("health_timeout_s", 2.5),
                "startup_timeout_s": legacy_web.get("startup_timeout_s", 45),
                "docker_compose_dir": legacy_web.get("docker_compose_dir", "searxng"),
                "docker_service_name": legacy_web.get("docker_service_name", "searxng"),
                "auto_restart_on_failure": legacy_web.get("auto_restart_on_failure", True),
            }

    language = data.get("language") or {}
    if isinstance(language, dict):
        default_lang = str(language.get("default") or "").strip()
        if default_lang and not data.get("default_language"):
            data["default_language"] = default_lang

    kb = data.get("kb") or {}
    if isinstance(kb, dict):
        default_kb = str(kb.get("default_name") or "").strip()
        if default_kb and not data.get("default_kb_name"):
            data["default_kb_name"] = default_kb

    vector = data.get("vector") or {}
    if isinstance(vector, dict):
        embeddings = dict(data.get("embeddings") or {})
        if vector.get("provider") and not embeddings.get("provider"):
            embeddings["provider"] = vector["provider"]
        if vector.get("embed_model") and not embeddings.get("model"):
            embeddings["model"] = vector["embed_model"]
        if embeddings:
            data["embeddings"] = embeddings

    return data


def _merge_env_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    data = dict(raw)

    workspace = os.environ.get("PICOBOT_WORKSPACE", "").strip()
    if workspace:
        data["workspace"] = workspace

    ollama_base = os.environ.get("PICOBOT_OLLAMA_BASE_URL", "").strip()
    ollama_model = os.environ.get("PICOBOT_OLLAMA_MODEL", "").strip()
    tg_token = os.environ.get("PICOBOT_TELEGRAM_BOT_TOKEN", "").strip()
    web_search_url = os.environ.get("PICOBOT_WEB_SEARCH_URL", "").strip()

    if ollama_base or ollama_model:
        ollama = dict(data.get("ollama") or {})
        if ollama_base:
            ollama["base_url"] = ollama_base
        if ollama_model:
            ollama["model"] = ollama_model
        data["ollama"] = ollama

    if tg_token:
        telegram = dict(data.get("telegram") or {})
        telegram["bot_token"] = tg_token
        data["telegram"] = telegram

    if web_search_url:
        web_search = dict(data.get("web_search") or {})
        web_search["searxng_url"] = web_search_url
        data["web_search"] = web_search

    return data


def load_config(explicit_path: str | Path | None = None) -> Config:
    raw: dict[str, Any] = {}
    chosen: Path | None = None

    for candidate in _candidate_paths(explicit_path):
        if candidate.exists() and candidate.is_file():
            chosen = candidate
            raw = _load_json(candidate)
            break

    if chosen is None:
        raise FileNotFoundError(
            "No config file found. Create .picobot/config.json or set PICOBOT_CONFIG."
        )

    raw = _normalize_legacy(raw)
    raw = _merge_env_overrides(raw)

    cfg = Config.model_validate(raw)
    set_runtime_config(cfg)
    return cfg
