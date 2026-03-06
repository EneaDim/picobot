from __future__ import annotations

# Loader config robusto e coerente.
#
# Obiettivi:
# - supportare PICOBOT_CONFIG
# - supportare .picobot/config.json come default naturale
# - supportare fallback tipo picobot.config.json
# - applicare qualche normalizzazione legacy
# - inizializzare runtime_config una volta sola

import json
import os
from pathlib import Path
from typing import Any

from picobot.config.schema import Config
from picobot.runtime_config import set_runtime_config


def _candidate_paths(explicit_path: str | Path | None = None) -> list[Path]:
    """
    Ordine di ricerca della config.

    Priorità:
    1. path esplicito
    2. env PICOBOT_CONFIG
    3. ./.picobot/config.json
    4. ./picobot.config.json
    5. ./config.json
    6. ~/.picobot/config.json
    """
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

    # Dedup mantenendo l'ordine
    seen: set[str] = set()
    unique: list[Path] = []

    for p in out:
        rp = str(p.expanduser())
        if rp not in seen:
            seen.add(rp)
            unique.append(p)

    return unique


def _load_json(path: Path) -> dict[str, Any]:
    """
    Carica un file JSON e garantisce che sia un oggetto.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Config file is not a JSON object: {path}")
    return data


def _normalize_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """
    Normalizza alcune forme legacy senza introdurre magia eccessiva.
    """
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

    # language.default -> default_language
    language = data.get("language") or {}
    if isinstance(language, dict):
        default_lang = str(language.get("default") or "").strip()
        if default_lang and not data.get("default_language"):
            data["default_language"] = default_lang

    # kb.default_name -> default_kb_name
    kb = data.get("kb") or {}
    if isinstance(kb, dict):
        default_kb = str(kb.get("default_name") or "").strip()
        if default_kb and not data.get("default_kb_name"):
            data["default_kb_name"] = default_kb

    # vector.embed_model -> embeddings.model
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
    """
    Override pratici da environment.
    """
    data = dict(raw)

    workspace = os.environ.get("PICOBOT_WORKSPACE", "").strip()
    if workspace:
        data["workspace"] = workspace

    ollama_base = os.environ.get("PICOBOT_OLLAMA_BASE_URL", "").strip()
    ollama_model = os.environ.get("PICOBOT_OLLAMA_MODEL", "").strip()
    tg_token = os.environ.get("PICOBOT_TELEGRAM_BOT_TOKEN", "").strip()

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

    return data


def load_config(explicit_path: str | Path | None = None) -> Config:
    """
    Carica la configurazione, la valida e inizializza runtime_config.
    """
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

    # Allinea il runtime lookup globale alla config validata.
    set_runtime_config(cfg)

    return cfg
