from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

from picobot.sandbox.runner import SandboxRunner
from picobot.tools.sandbox_exec import ExecResult


class TerminalToolBase:
    """
    Base per tool CLI: SEMPRE via SandboxRunner unico.

    Compat:
      - accetta `cwd` (storico). Ora è ignorato perché ogni run ha una workdir dedicata.
      - accetta `sandbox_root` per scegliere dove scrivere .sandbox_runs.
    """

    def __init__(
        self,
        *,
        allowed_bins: Iterable[str],
        sandbox_root: str | Path | None = None,
        timeout_s: int = 180,
        max_output_bytes: int = 200_000,
        extra_env: dict[str, str] | None = None,
        cwd: str | Path | None = None,  # <-- COMPAT: alcuni test/codice lo passano
    ) -> None:
        # NOTE: `cwd` è mantenuto solo per compatibilità; ogni run avviene in workdir isolata.
        _ = cwd

        root = sandbox_root or os.environ.get("PICOBOT_SANDBOX_ROOT", ".picobot/sandbox_runs")
        self._runner = SandboxRunner(
            allowed_bins=list(allowed_bins),
            sandbox_root=root,
            timeout_s=int(timeout_s),
            max_output_bytes=int(max_output_bytes),
            extra_env=extra_env,
        )

    @property
    def runner(self) -> SandboxRunner:
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

    def run_cmd(
        self,
        argv: list[str],
        *,
        prefix: str,
        timeout_s: int | None = None,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        self._log_cmd(prefix, argv)
        run = self.runner.run(argv, timeout_s=timeout_s, env=env, input_bytes=input_bytes)
        res = run.to_exec_result()
        self._log_result(prefix, res)
        return res

    @staticmethod
    def ok(data: dict[str, Any], *, language: str | None = None) -> dict:
        return {"ok": True, "data": data, "error": None, "language": language}

    @staticmethod
    def fail(msg: str, *, language: str | None = None, data: dict[str, Any] | None = None) -> dict:
        return {"ok": False, "data": data or {}, "error": msg, "language": language}
