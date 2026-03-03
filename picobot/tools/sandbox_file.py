from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from picobot.agent.prompts import detect_language
from picobot.tools.base import ToolSpec, tool_error, tool_ok


class SandboxFileArgs(BaseModel):
    root: str = Field(..., min_length=1, description="Allowed root directory")
    path: str = Field(..., min_length=1, description="Path relative to root or absolute within root")
    max_bytes: int = Field(default=120_000, ge=1_000, le=2_000_000)


def _safe_resolve(root: Path, p: Path) -> Path | None:
    try:
        r = root.expanduser().resolve()
        t = (p if p.is_absolute() else (r / p)).expanduser().resolve()
        if os.path.commonpath([str(r), str(t)]) != str(r):
            return None
        return t
    except Exception:
        return None


def make_sandbox_file_tool():
    async def _handler(args: SandboxFileArgs) -> dict:
        try:
            root = Path(args.root)
            target = _safe_resolve(root, Path(args.path))
            if target is None:
                return tool_error("path outside allowed root")
            if not target.exists():
                return tool_error("not found")
            if target.is_dir():
                items = []
                for p in sorted(target.iterdir())[:100]:
                    items.append({"name": p.name, "is_dir": p.is_dir(), "size": (p.stat().st_size if p.is_file() else None)})
                return tool_ok({"path": str(target), "is_dir": True, "items": items})

            sz = int(target.stat().st_size)
            if sz > int(args.max_bytes):
                return tool_error("file too large")
            raw = target.read_bytes()
            text = raw.decode("utf-8", errors="replace")
            lang = detect_language(text, default="it") if text else None
            return tool_ok(
                {
                    "path": str(target),
                    "is_dir": False,
                    "size": sz,
                    "preview": text,
                },
                language=lang,
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="sandbox_file",
        description="Read a file or list a directory within a configured root (size capped).",
        schema=SandboxFileArgs,
        handler=_handler,
    )
