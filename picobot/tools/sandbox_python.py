from __future__ import annotations

import asyncio
import os
from pathlib import Path

from pydantic import BaseModel, Field

from picobot.tools.base import ToolSpec, tool_error, tool_ok


class SandboxPythonArgs(BaseModel):
    cwd: str = Field(..., min_length=1, description="Working directory (must exist)")
    code: str = Field(..., min_length=1, description="Python code to execute")
    timeout_s: float = Field(default=5.0, ge=0.5, le=30.0)
    max_output: int = Field(default=40_000, ge=1_000, le=200_000)


def make_sandbox_python_tool():
    async def _handler(args: SandboxPythonArgs) -> dict:
        try:
            cwd = Path(args.cwd).expanduser().resolve()
            if not cwd.exists() or not cwd.is_dir():
                return tool_error("cwd must exist and be a directory")

            env = {k: v for k, v in os.environ.items() if not k.lower().endswith("_proxy")}
            env.update({"PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1"})

            p = await asyncio.create_subprocess_exec(
                "python",
                "-I",
                "-c",
                args.code,
                cwd=str(cwd),
                env=env,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                out_b, err_b = await asyncio.wait_for(p.communicate(), timeout=float(args.timeout_s))
            except asyncio.TimeoutError:
                try:
                    p.kill()
                except Exception:
                    pass
                return tool_error("timeout")

            out = (out_b or b"").decode("utf-8", errors="replace")
            err = (err_b or b"").decode("utf-8", errors="replace")

            out = out[: int(args.max_output)]
            err = err[: int(args.max_output)]

            return tool_ok(
                {
                    "returncode": int(p.returncode or 0),
                    "stdout": out,
                    "stderr": err,
                }
            )
        except Exception as e:
            return tool_error(str(e))

    return ToolSpec(
        name="sandbox_python",
        description="Run Python code in a subprocess (timeout, capped output, best-effort isolation).",
        schema=SandboxPythonArgs,
        handler=_handler,
    )
