from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

from picobot.tools.sandbox_exec import SandboxExec, ExecResult


class TerminalToolBase:
    """
    Mixin/base for tools that execute terminal commands.
    - Provides a sandboxed runner (allowlist)
    - Provides terminal-only logging helpers
    - Does NOT print to Telegram/CLI directly (caller/UI decides)
    """

    def __init__(
        self,
        *,
        allowed_bins: list[str],
        cwd: str | Path | None = None,
        timeout_s: int = 120,
        max_output_bytes: int = 200_000,
    ) -> None:
        self._runner = SandboxExec(
            allowed_bins=allowed_bins,
            default_cwd=str(cwd) if cwd is not None else None,
            timeout_s=int(timeout_s),
            max_output_bytes=int(max_output_bytes),
        )

    @property
    def runner(self) -> SandboxExec:
        return self._runner

    def _log_cmd(self, prefix: str, argv: list[str]) -> None:
        try:
            print(f"{prefix} CMD: {shlex.join(argv)}", file=sys.stderr)
        except Exception:
            pass

    def _log_result(self, prefix: str, res: ExecResult) -> None:
        try:
            print(f"{prefix} RC={res.returncode}", file=sys.stderr)
            if res.stderr:
                print(f"{prefix} STDERR:\n{res.stderr}", file=sys.stderr)
        except Exception:
            pass

    def run_cmd(self, argv: list[str], *, prefix: str, cwd: str | Path | None = None, timeout_s: int | None = None) -> ExecResult:
        self._log_cmd(prefix, argv)
        res = self.runner.run(argv, cwd=cwd, timeout_s=timeout_s)
        self._log_result(prefix, res)
        return res

    @staticmethod
    def ok(data: dict[str, Any], *, language: str | None = None) -> dict:
        return {"ok": True, "data": data, "error": None, "language": language}

    @staticmethod
    def fail(msg: str, *, language: str | None = None, data: dict[str, Any] | None = None) -> dict:
        return {"ok": False, "data": data or {}, "error": msg, "language": language}
