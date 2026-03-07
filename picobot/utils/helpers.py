from __future__ import annotations

# Helpers comuni piccoli e riusabili.
#
# Scopo:
# - evitare utility duplicate sparse
# - offrire path helpers coerenti
# - leggere/scrivere JSON in modo uniforme
#
# Non vogliamo una "misc.py" enorme.
# Solo helper essenziali, chiari e utili.
import json
import re
from pathlib import Path
from typing import Any

from picobot.config.schema import Config

_SAFE_SEGMENT_RX = re.compile(r"[^a-zA-Z0-9._-]+")


def workspace_path(cfg: Config) -> Path:
    """
    Restituisce il workspace assoluto e garantisce che esista.
    """
    ws = Path(cfg.workspace).expanduser()
    if not ws.is_absolute():
        ws = (Path.cwd() / ws).resolve()

    ws.mkdir(parents=True, exist_ok=True)
    return ws


def docs_root(cfg: Config) -> Path:
    """
    Root docs del workspace.
    """
    path = workspace_path(cfg) / "docs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def memory_root(cfg: Config) -> Path:
    """
    Root memory del workspace.
    """
    path = workspace_path(cfg) / "memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def qdrant_path(cfg: Config) -> Path:
    """
    Path locale embedded di Qdrant.
    """
    path = Path(cfg.qdrant.path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()

    path.mkdir(parents=True, exist_ok=True)
    return path


def ensure_parent(path: Path) -> Path:
    """
    Garantisce che il parent di un file esista.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def safe_slug(text: str, fallback: str = "item", max_len: int = 80) -> str:
    """
    Slug semplice e stabile.
    """
    value = (text or "").strip().lower()
    value = _SAFE_SEGMENT_RX.sub("-", value)
    value = value.strip("-.")
    if not value:
        value = fallback
    return value[: max(8, int(max_len))]


def read_json(path: Path, default: Any = None) -> Any:
    """
    Legge un JSON da disco con fallback.
    """
    file_path = Path(path)
    if not file_path.exists():
        return default

    try:
        return json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path: Path, data: Any) -> Path:
    """
    Scrive un JSON in UTF-8 in modo consistente.
    """
    file_path = ensure_parent(Path(path))
    file_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return file_path
