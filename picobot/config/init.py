from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def _repo_root() -> Path:
    return Path.cwd().resolve()


def init_project(*, force: bool = False) -> dict:
    root = _repo_root()
    picobot_dir = root / ".picobot"
    picobot_dir.mkdir(parents=True, exist_ok=True)

    template_path = root / "picobot" / "config" / "config.template.json"
    config_path = picobot_dir / "config.json"

    if not template_path.exists():
        raise FileNotFoundError(f"Config template non trovato: {template_path}")

    if config_path.exists() and not force:
        created = False
    else:
        shutil.copyfile(template_path, config_path)
        created = True

    workspace = picobot_dir / "workspace"
    tools_dir = picobot_dir / "tools"
    workspace.mkdir(parents=True, exist_ok=True)
    tools_dir.mkdir(parents=True, exist_ok=True)

    outputs = root / "outputs" / "podcasts"
    outputs.mkdir(parents=True, exist_ok=True)

    return {
        "ok": True,
        "config_path": str(config_path),
        "config_created": created,
        "workspace_dir": str(workspace),
        "tools_dir": str(tools_dir),
        "outputs_dir": str(outputs),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize local picobot project files")
    parser.add_argument("--force", action="store_true", help="Overwrite existing .picobot/config.json")
    args = parser.parse_args()

    result = init_project(force=args.force)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
