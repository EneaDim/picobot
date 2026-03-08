from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from picobot.runtime_config import cfg_get
from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.terminal_tool import TerminalToolBase


class PythonToolArgs(BaseModel):
    cwd: str = Field(default=".", description="Working directory relativa dentro la run sandbox")
    code: str = Field(..., min_length=1, description="Python code to execute")
    timeout_s: float = Field(default=5.0, ge=0.5, le=60.0)
    max_output: int = Field(default=40_000, ge=1_000, le=200_000)


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


def make_python_tool(cfg=None):
    allowed_bins = list(_cfg_value(cfg, "sandbox.exec.allowed_bins", ["python", "bash"]) or ["python", "bash"])
    default_timeout = int(_cfg_value(cfg, "sandbox.python.timeout_s", 5) or 5)

    runner = TerminalToolBase(
        cfg=cfg,
        allowed_bins=allowed_bins,
        timeout_s=max(default_timeout, 1),
        max_output_bytes=int(_cfg_value(cfg, "sandbox.exec.max_output_bytes", 200_000) or 200_000),
    )

    async def _handler(args: PythonToolArgs) -> dict:
        try:
            timeout_s = int(args.timeout_s or default_timeout or 5)
            res = runner.run_cmd(
                ["python", "-I", "-c", args.code],
                prefix="[python]",
                timeout_s=timeout_s,
                relative_cwd=args.cwd,
            )
            out = (res.stdout or "")[: int(args.max_output)]
            err = (res.stderr or "")[: int(args.max_output)]
            return tool_ok(
                {
                    "backend": runner.backend,
                    "returncode": int(res.returncode),
                    "stdout": out,
                    "stderr": err,
                }
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="python",
        description="Run Python code inside the configured sandbox backend.",
        schema=PythonToolArgs,
        handler=_handler,
    )
