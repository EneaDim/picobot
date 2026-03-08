from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, Field

from picobot.agent.prompts import detect_language
from picobot.runtime_config import cfg_get
from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.terminal_tool import TerminalToolBase


class FileToolArgs(BaseModel):
    root: str = Field(default=".", min_length=1, description="Root relativa o assoluta, sempre dentro il workspace")
    path: str = Field(..., min_length=1, description="Path relativa alla root")
    max_bytes: int = Field(default=120_000, ge=1_000, le=2_000_000)


def _cfg_value(cfg: Any | None, path: str, default: Any) -> Any:
    if cfg is not None:
        current = cfg
        for part in path.split("."):
            if hasattr(current, part):
                current = getattr(current, part)
            else:
                return cfg_get(path, default)
        return current
    return cfg_get(path, default)


def make_file_tool(cfg=None):
    allowed_bins = list(_cfg_value(cfg, "sandbox.exec.allowed_bins", ["python"]) or ["python"])
    default_root = str(_cfg_value(cfg, "sandbox.file.root", _cfg_value(cfg, "workspace", ".picobot/workspace")) or ".picobot/workspace").strip()
    default_max_bytes = int(_cfg_value(cfg, "sandbox.file.max_bytes", 200_000) or 200_000)

    runner = TerminalToolBase(
        cfg=cfg,
        allowed_bins=allowed_bins,
        timeout_s=int(_cfg_value(cfg, "sandbox.exec.timeout_s", 30) or 30),
        max_output_bytes=int(_cfg_value(cfg, "sandbox.exec.max_output_bytes", 200_000) or 200_000),
    )

    async def _handler(args: FileToolArgs) -> dict:
        try:
            root_value = (args.root or "").strip() or default_root
            root_host = runner.resolve_workspace_path(root_value)
            runtime_root = runner.map_host_path(root_host)

            payload = json.dumps(
                {
                    "runtime_root": runtime_root,
                    "display_root": str(root_host),
                    "path": str(args.path),
                    "max_bytes": int(args.max_bytes or default_max_bytes),
                },
                ensure_ascii=False,
            )

            res = runner.run_cmd(
                ["python", "-I", "-c", _PY_FILE_READ],
                prefix="[file]",
                timeout_s=10,
                input_bytes=payload.encode("utf-8"),
            )
            if res.returncode != 0:
                return tool_error((res.stderr or "error")[:500])

            data = json.loads(res.stdout or "{}")
            if not data.get("ok"):
                return tool_error(data.get("error") or "file error")

            out = data.get("data") or {}
            preview = (out.get("preview") or "").strip()
            lang = detect_language(preview, default="it") if preview else None

            out["backend"] = runner.backend
            out["workspace_root"] = str(runner.workspace_root)

            return tool_ok(out, language=lang)
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="file",
        description="Read or list files inside the configured workspace sandbox.",
        schema=FileToolArgs,
        handler=_handler,
    )


_PY_FILE_READ = r'''
import sys, os, json
from pathlib import Path

def safe_resolve(root: Path, p: Path):
    r = root.expanduser().resolve()
    t = (p if p.is_absolute() else (r / p)).expanduser().resolve()
    if os.path.commonpath([str(r), str(t)]) != str(r):
        return None
    return t

raw = sys.stdin.read()
args = json.loads(raw) if raw else {}
runtime_root = Path(args.get("runtime_root") or ".")
display_root = Path(args.get("display_root") or ".")
path = Path(args.get("path") or "")
max_bytes = int(args.get("max_bytes") or 120000)

runtime_target = safe_resolve(runtime_root, path)
display_target = safe_resolve(display_root, path)

if runtime_target is None or display_target is None:
    print(json.dumps({"ok": False, "error": "path outside allowed root"}))
    sys.exit(0)

if not runtime_target.exists():
    print(json.dumps({"ok": False, "error": "not found"}))
    sys.exit(0)

if runtime_target.is_dir():
    items = []
    for p in sorted(runtime_target.iterdir())[:100]:
        items.append({
            "name": p.name,
            "is_dir": p.is_dir(),
            "size": (p.stat().st_size if p.is_file() else None)
        })
    print(json.dumps({
        "ok": True,
        "data": {
            "path": str(display_target),
            "is_dir": True,
            "items": items
        }
    }))
    sys.exit(0)

sz = int(runtime_target.stat().st_size)
if sz > max_bytes:
    print(json.dumps({"ok": False, "error": "file too large"}))
    sys.exit(0)

rawb = runtime_target.read_bytes()
text = rawb.decode("utf-8", errors="replace")
print(json.dumps({
    "ok": True,
    "data": {
        "path": str(display_target),
        "is_dir": False,
        "size": sz,
        "preview": text
    }
}))
'''
