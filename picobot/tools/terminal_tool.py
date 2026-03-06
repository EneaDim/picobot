from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from picobot.sandbox.runner import SandboxRunner
from picobot.tools.sandbox_exec import ExecResult


class TerminalToolBase:
    def __init__(
        self,
        *,
        allowed_bins: Iterable[str],
        sandbox_root: str | Path | None = None,
        timeout_s: int = 180,
        max_output_bytes: int = 200_000,
        extra_env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
    ) -> None:
        _ = cwd
        root = sandbox_root or os.environ.get("PICOBOT_SANDBOX_ROOT", ".picobot/sandbox_runs")
        self._runner = SandboxRunner(
            allowed_bins=list(allowed_bins),
            sandbox_root=root,
            timeout_s=int(timeout_s),
            max_output_bytes=int(max_output_bytes),
            extra_env=extra_env,
        )
        self._debug = str(os.environ.get("PICOBOT_TOOL_DEBUG", "")).strip().lower() in {"1", "true", "yes", "on"}

    @property
    def runner(self) -> SandboxRunner:
        return self._runner

    def _log_cmd(self, prefix: str, argv: list[str]) -> None:
        if not self._debug:
            return

    def _log_result(self, prefix: str, res: ExecResult) -> None:
        if not self._debug:
            return

    def run_cmd(
        self,
        argv: list[str],
        *,
        prefix: str,
        timeout_s: int | None = None,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        run = self.runner.run(argv, timeout_s=timeout_s, env=env, input_bytes=input_bytes)
        return run.to_exec_result()

    @staticmethod
    def ok(data: dict[str, Any], *, language: str | None = None) -> dict:
        return {"ok": True, "data": data, "error": None, "language": language}

    @staticmethod
    def fail(msg: str, *, language: str | None = None, data: dict[str, Any] | None = None) -> dict:
        return {"ok": False, "data": data or {}, "error": msg, "language": language}
