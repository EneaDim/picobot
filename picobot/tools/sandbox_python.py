from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok
from picobot.tools.terminal_tool import TerminalToolBase


class SandboxPythonArgs(BaseModel):
    cwd: str = Field(default=".", description="Working directory (relative inside sandbox workdir)")
    code: str = Field(..., min_length=1, description="Python code to execute")
    timeout_s: float = Field(default=5.0, ge=0.5, le=30.0)
    max_output: int = Field(default=40_000, ge=1_000, le=200_000)


def make_sandbox_python_tool():
    runner = TerminalToolBase(allowed_bins=["python"], timeout_s=30, max_output_bytes=200_000)

    async def _handler(args: SandboxPythonArgs) -> dict:
        try:
            # Eseguiamo python isolato (-I) nella workdir sandbox.
            # `cwd` è relativo nella sandbox workdir (non host).
            code = args.code
            res = runner.run_cmd(
                ["python", "-I", "-c", code],
                prefix="[sandbox_python]",
                timeout_s=int(args.timeout_s),
            )
            out = (res.stdout or "")[: int(args.max_output)]
            err = (res.stderr or "")[: int(args.max_output)]
            return tool_ok({"returncode": int(res.returncode), "stdout": out, "stderr": err})
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="sandbox_python",
        description="Run Python code inside sandbox runner (workdir per run, timeout, capped output).",
        schema=SandboxPythonArgs,
        handler=_handler,
    )
