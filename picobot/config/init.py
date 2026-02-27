from __future__ import annotations

import json
from pathlib import Path
import importlib.resources as ir


def _read_template_text() -> str:
    # packaged template: picobot/config/config.template.json
    with ir.files("picobot").joinpath("config/config.template.json").open("r", encoding="utf-8") as f:
        return f.read()


def init_project(force: bool = False) -> dict:
    """
    Create project-local .picobot/ structure and copy config template to .picobot/config.json.
    Returns a dict with created paths.
    """
    root = Path.cwd() / ".picobot"
    root.mkdir(parents=True, exist_ok=True)

    cfg_path = root / "config.json"
    if cfg_path.exists() and not force:
        return {"status": "exists", "config": str(cfg_path), "root": str(root)}

    tmpl = _read_template_text()

    # validate JSON (fail early if template is broken)
    data = json.loads(tmpl)

    cfg_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # create workspace structure (minimal, coherent)
    ws = root / "workspace"
    (ws / "docs").mkdir(parents=True, exist_ok=True)
    mem_dir = ws / "memory"
    (mem_dir / "sessions").mkdir(parents=True, exist_ok=True)

    mem_file = mem_dir / "MEMORY.md"
    if not mem_file.exists():
        mem_file.write_text("# Memory\n\n", encoding="utf-8")

    return {
        "status": "created",
        "root": str(root),
        "config": str(cfg_path),
        "workspace": str(ws),
        "memory": str(mem_file),
    }
