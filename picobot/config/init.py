from __future__ import annotations

# Inizializzazione struttura locale .picobot/
#
# Obiettivi:
# - copiare il template config in .picobot/config.json
# - creare workspace coerente
# - preparare le directory minime usate dal progetto
import importlib.resources as ir
import json
from pathlib import Path


def _read_template_text() -> str:
    """
    Legge il template config pacchettizzato.
    """
    with ir.files("picobot").joinpath("config/config.template.json").open("r", encoding="utf-8") as f:
        return f.read()


def init_project(force: bool = False) -> dict:
    """
    Inizializza la struttura locale .picobot/.

    Crea:
    - .picobot/config.json
    - .picobot/workspace/docs
    - .picobot/workspace/memory
    - .picobot/qdrant
    """
    root = Path.cwd() / ".picobot"
    root.mkdir(parents=True, exist_ok=True)

    cfg_path = root / "config.json"

    if cfg_path.exists() and not force:
        return {
            "status": "exists",
            "root": str(root),
            "config": str(cfg_path),
        }

    tmpl = _read_template_text()

    # Validiamo il JSON del template prima di scriverlo.
    data = json.loads(tmpl)
    cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    workspace = root / "workspace"
    docs_dir = workspace / "docs"
    memory_dir = workspace / "memory"
    sessions_dir = memory_dir / "sessions"
    qdrant_dir = root / "qdrant"

    docs_dir.mkdir(parents=True, exist_ok=True)
    sessions_dir.mkdir(parents=True, exist_ok=True)
    qdrant_dir.mkdir(parents=True, exist_ok=True)

    global_memory = memory_dir / "MEMORY.md"
    if not global_memory.exists():
        global_memory.write_text("# Memory\n\n", encoding="utf-8")

    return {
        "status": "created",
        "root": str(root),
        "config": str(cfg_path),
        "workspace": str(workspace),
        "docs": str(docs_dir),
        "memory": str(global_memory),
        "qdrant": str(qdrant_dir),
    }
