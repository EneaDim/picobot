from __future__ import annotations

import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class ExecResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]


class SandboxExec:
    """
    Deterministic subprocess runner:
    - allowlist binaries
    - timeout
    - stdout/stderr caps
    - controlled cwd/env
    """

    def __init__(
        self,
        allowed_bins: Iterable[str],
        *,
        default_cwd: str | Path | None = None,
        timeout_s: int = 60,
        max_output_bytes: int = 200_000,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.allowed_bins = {str(x) for x in allowed_bins if str(x).strip()}
        self.default_cwd = Path(default_cwd).resolve() if default_cwd is not None else None
        self.timeout_s = int(timeout_s)
        self.max_output_bytes = int(max_output_bytes)
        self.extra_env = dict(extra_env or {})

    def _is_allowed(self, argv: list[str]) -> bool:
        if not argv:
            return False
        exe = argv[0]
        base = os.path.basename(exe)
        allowed_bases = {os.path.basename(x) for x in self.allowed_bins}
        return exe in self.allowed_bins or base in allowed_bases

    def run(
        self,
        argv: list[str],
        *,
        cwd: str | Path | None = None,
        timeout_s: int | None = None,
        env: dict[str, str] | None = None,
    ) -> ExecResult:
        argv = [str(x) for x in (argv or [])]
        if not self._is_allowed(argv):
            return ExecResult(
                ok=False,
                returncode=126,
                stdout="",
                stderr=f"command not allowed: {shlex.join(argv)}",
                cmd=argv,
            )

        use_cwd = Path(cwd).resolve() if cwd is not None else self.default_cwd
        use_timeout = int(timeout_s) if timeout_s is not None else self.timeout_s

        clean_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C"),
            "LC_ALL": os.environ.get("LC_ALL", "C"),
        }
        clean_env.update(self.extra_env)
        if env:
            clean_env.update({str(k): str(v) for k, v in env.items()})

        try:
            cp = subprocess.run(
                argv,
                cwd=str(use_cwd) if use_cwd else None,
                env=clean_env,
                text=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=use_timeout,
                check=False,
            )
            out = (cp.stdout or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            err = (cp.stderr or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            return ExecResult(ok=(cp.returncode == 0), returncode=int(cp.returncode), stdout=out, stderr=err, cmd=argv)
        except subprocess.TimeoutExpired as e:
            out = (getattr(e, "stdout", None) or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            err = (getattr(e, "stderr", None) or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            if err:
                err = err + "\n"
            err = err + f"timeout after {use_timeout}s"
            return ExecResult(ok=False, returncode=124, stdout=out, stderr=err, cmd=argv)
