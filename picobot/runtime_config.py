from __future__ import annotations

# Runtime config centrale.
#
# Regola importante:
# - NON leggiamo più il JSON grezzo qui
# - usiamo solo la config validata passata da loader.py
#
# Così cfg_get(...) è coerente con lo schema Pydantic.
from typing import Any

_RUNTIME_CONFIG: dict[str, Any] = {}


def _to_plain_dict(cfg: Any) -> dict[str, Any]:
    """
    Converte un oggetto config in un dict semplice.
    """
    if cfg is None:
        return {}

    if isinstance(cfg, dict):
        return dict(cfg)

    if hasattr(cfg, "model_dump"):
        dumped = cfg.model_dump(mode="python")
        if isinstance(dumped, dict):
            return dumped

    return {}


def set_runtime_config(cfg: Any) -> None:
    """
    Imposta la config runtime globale.
    """
    global _RUNTIME_CONFIG
    _RUNTIME_CONFIG = _to_plain_dict(cfg)


def get_runtime_config() -> dict[str, Any]:
    """
    Restituisce una copia superficiale della config runtime.
    """
    return dict(_RUNTIME_CONFIG)


def cfg_get(path: str, default: Any = None) -> Any:
    """
    Lookup dotted-path semplice.

    Esempi:
    - cfg_get("router.top_k", 5)
    - cfg_get("qdrant.path", ".picobot/qdrant")
    """
    if not path:
        return default

    current: Any = _RUNTIME_CONFIG

    for part in str(path).split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return default

    return current
