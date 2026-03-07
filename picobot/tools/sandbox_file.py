from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from picobot.agent.prompts import detect_language
from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.terminal_tool import TerminalToolBase


class SandboxFileArgs(BaseModel):
    root: str = Field(..., min_length=1, description="Allowed root directory (host path)")
    path: str = Field(..., min_length=1, description="Path relative to root or absolute within root")
    max_bytes: int = Field(default=120_000, ge=1_000, le=2_000_000)


def make_sandbox_file_tool():
    runner = TerminalToolBase(allowed_bins=["python"], timeout_s=30, max_output_bytes=200_000)

    async def _handler(args: SandboxFileArgs) -> dict:
        try:
            root = str(Path(args.root).expanduser().resolve())
            path = str(args.path)
            max_bytes = int(args.max_bytes)

            payload = json.dumps({"root": root, "path": path, "max_bytes": max_bytes})
            res = runner.run_cmd(
                ["python", "-I", "-c", _PY_FILE_READ],
                prefix="[sandbox_file]",
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
            return tool_ok(out, language=lang)
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="sandbox_file",
        description="Read/list host files within a configured root via sandbox runner.",
        schema=SandboxFileArgs,
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
root = Path(args.get("root") or ".")
path = Path(args.get("path") or "")
max_bytes = int(args.get("max_bytes") or 120000)

t = safe_resolve(root, path)
if t is None:
    print(json.dumps({"ok": False, "error": "path outside allowed root"}))
    sys.exit(0)
if not t.exists():
    print(json.dumps({"ok": False, "error": "not found"}))
    sys.exit(0)

if t.is_dir():
    items = []
    for p in sorted(t.iterdir())[:100]:
        items.append({"name": p.name, "is_dir": p.is_dir(), "size": (p.stat().st_size if p.is_file() else None)})
    print(json.dumps({"ok": True, "data": {"path": str(t), "is_dir": True, "items": items}}))
    sys.exit(0)

sz = int(t.stat().st_size)
if sz > max_bytes:
    print(json.dumps({"ok": False, "error": "file too large"}))
    sys.exit(0)

rawb = t.read_bytes()
text = rawb.decode("utf-8", errors="replace")
print(json.dumps({"ok": True, "data": {"path": str(t), "is_dir": False, "size": sz, "preview": text}}))
'''
