from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from picobot.tools.sandbox_exec import ExecResult


@dataclass(frozen=True)
class SandboxRun:
    run_id: str
    workdir: Path
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timeout_s: int
    ok: bool

    def to_exec_result(self) -> ExecResult:
        return ExecResult(ok=self.ok, returncode=self.returncode, stdout=self.stdout, stderr=self.stderr, cmd=self.cmd)


class SandboxRunner:
    """
    Runner unico per tutti i tool CLI:
    - crea workdir dedicata per run: <sandbox_root>/<run_id>/
    - allowlist binari
    - timeout
    - cap output
    - manifest run.json + stdout/stderr su file
    """

    def __init__(
        self,
        *,
        allowed_bins: Iterable[str],
        sandbox_root: str | Path,
        timeout_s: int = 180,
        max_output_bytes: int = 200_000,
        extra_env: Optional[dict[str, str]] = None,
    ) -> None:
        self.allowed_bins = {str(x) for x in allowed_bins if str(x).strip()}
        self.sandbox_root = Path(sandbox_root).expanduser().resolve()
        self.timeout_s = int(timeout_s)
        self.max_output_bytes = int(max_output_bytes)
        self.extra_env = dict(extra_env or {})
        self.sandbox_root.mkdir(parents=True, exist_ok=True)

    def _is_allowed(self, argv: list[str]) -> bool:
        if not argv:
            return False
        exe = str(argv[0])
        base = os.path.basename(exe)
        allowed_bases = {os.path.basename(x) for x in self.allowed_bins}
        return exe in self.allowed_bins or base in allowed_bases

    def run(
        self,
        argv: list[str],
        *,
        timeout_s: int | None = None,
        env: dict[str, str] | None = None,
        input_bytes: bytes | None = None,
    ) -> SandboxRun:
        argv = [str(x) for x in (argv or [])]
        if not self._is_allowed(argv):
            return self._finish_disallowed(argv)

        run_id = uuid.uuid4().hex[:12]
        workdir = (self.sandbox_root / run_id)
        workdir.mkdir(parents=True, exist_ok=True)

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

        t0 = time.time()
        try:
            cp = subprocess.run(
                argv,
                cwd=str(workdir),
                env=clean_env,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=use_timeout,
                check=False,
            )
            dur = time.time() - t0
            out = (cp.stdout or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            err = (cp.stderr or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            run = SandboxRun(
                run_id=run_id,
                workdir=workdir,
                cmd=argv,
                returncode=int(cp.returncode),
                stdout=out,
                stderr=err,
                duration_s=dur,
                timeout_s=use_timeout,
                ok=(cp.returncode == 0),
            )
            self._persist(run)
            return run

        except subprocess.TimeoutExpired as e:
            dur = time.time() - t0
            out = (getattr(e, "stdout", None) or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            err = (getattr(e, "stderr", None) or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            if err:
                err += "\n"
            err += f"timeout after {use_timeout}s"
            run = SandboxRun(
                run_id=run_id,
                workdir=workdir,
                cmd=argv,
                returncode=124,
                stdout=out,
                stderr=err,
                duration_s=dur,
                timeout_s=use_timeout,
                ok=False,
            )
            self._persist(run)
            return run

    def _persist(self, run: SandboxRun) -> None:
        try:
            (run.workdir / "stdout.txt").write_text(run.stdout or "", encoding="utf-8")
            (run.workdir / "stderr.txt").write_text(run.stderr or "", encoding="utf-8")
            manifest = {
                "run_id": run.run_id,
                "cmd": run.cmd,
                "returncode": run.returncode,
                "ok": run.ok,
                "duration_s": round(run.duration_s, 3),
                "timeout_s": run.timeout_s,
            }
            (run.workdir / "run.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _finish_disallowed(self, argv: list[str]) -> SandboxRun:
        run_id = uuid.uuid4().hex[:12]
        workdir = (self.sandbox_root / run_id)
        workdir.mkdir(parents=True, exist_ok=True)
        run = SandboxRun(
            run_id=run_id,
            workdir=workdir,
            cmd=argv,
            returncode=126,
            stdout="",
            stderr=f"command not allowed: {' '.join(argv)}",
            duration_s=0.0,
            timeout_s=0,
            ok=False,
        )
        self._persist(run)
        return run
