from __future__ import annotations

import os
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional


@dataclass(frozen=True)
class DockerExecResult:
    ok: bool
    returncode: int
    stdout: str
    stderr: str
    cmd: list[str]
    duration_s: float
    workdir: Path


class DockerRunner:
    """
    Runner per comandi docker/docker compose.
    Non esegue tool applicativi generici: solo docker.
    """

    def __init__(
        self,
        *,
        sandbox_root: str | Path,
        timeout_s: int = 120,
        max_output_bytes: int = 300_000,
        allowed_bins: Iterable[str] = ("docker",),
        extra_env: Optional[dict[str, str]] = None,
    ) -> None:
        self.sandbox_root = Path(sandbox_root).expanduser().resolve()
        self.sandbox_root.mkdir(parents=True, exist_ok=True)
        self.timeout_s = int(timeout_s)
        self.max_output_bytes = int(max_output_bytes)
        self.allowed_bins = {str(x) for x in allowed_bins}
        self.extra_env = dict(extra_env or {})

    def _allowed(self, argv: list[str]) -> bool:
        if not argv:
            return False
        exe = os.path.basename(str(argv[0]))
        return exe in {os.path.basename(x) for x in self.allowed_bins}

    def run(
        self,
        argv: list[str],
        *,
        timeout_s: int | None = None,
        cwd: str | Path | None = None,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
    ) -> DockerExecResult:
        argv = [str(x) for x in (argv or [])]
        if not self._allowed(argv):
            return DockerExecResult(
                ok=False,
                returncode=126,
                stdout="",
                stderr=f"command not allowed: {' '.join(argv)}",
                cmd=argv,
                duration_s=0.0,
                workdir=self.sandbox_root,
            )

        run_id = uuid.uuid4().hex[:12]
        workdir = self.sandbox_root / f"docker-{run_id}"
        workdir.mkdir(parents=True, exist_ok=True)

        base_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "C"),
            "LC_ALL": os.environ.get("LC_ALL", "C"),
        }
        base_env.update(self.extra_env)
        if env:
            base_env.update({str(k): str(v) for k, v in env.items()})

        t0 = time.time()
        try:
            cp = subprocess.run(
                argv,
                cwd=str(Path(cwd).resolve()) if cwd else str(workdir),
                env=base_env,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(timeout_s or self.timeout_s),
                check=False,
            )
            dt = time.time() - t0
            out = (cp.stdout or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            err = (cp.stderr or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            return DockerExecResult(
                ok=(cp.returncode == 0),
                returncode=int(cp.returncode),
                stdout=out,
                stderr=err,
                cmd=argv,
                duration_s=dt,
                workdir=workdir,
            )
        except subprocess.TimeoutExpired as e:
            dt = time.time() - t0
            out = (getattr(e, "stdout", None) or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            err = (getattr(e, "stderr", None) or b"")[: self.max_output_bytes].decode("utf-8", errors="ignore")
            if err:
                err += "\n"
            err += f"timeout after {int(timeout_s or self.timeout_s)}s"
            return DockerExecResult(
                ok=False,
                returncode=124,
                stdout=out,
                stderr=err,
                cmd=argv,
                duration_s=dt,
                workdir=workdir,
            )
