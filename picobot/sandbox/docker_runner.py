from __future__ import annotations


import json
import os
import shlex
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from picobot.tools.sandbox_exec import ExecResult

DEBUG_DOCKER = os.getenv("PICOBOT_TRACE_INTERNAL", "0").strip().lower() in {"1", "true", "yes", "on"}


def _debug_docker(msg: str) -> None:
    if DEBUG_DOCKER:
        print(f"[trace][docker] {msg}")

@dataclass(frozen=True)
class DockerSandboxRun:
    run_id: str
    backend: str
    host_workdir: Path
    container_workdir: str
    cmd: list[str]
    returncode: int
    stdout: str
    stderr: str
    duration_s: float
    timeout_s: int
    ok: bool

    def to_exec_result(self) -> ExecResult:
        return ExecResult(
            ok=self.ok,
            returncode=self.returncode,
            stdout=self.stdout,
            stderr=self.stderr,
            cmd=self.cmd,
        )


class PersistentDockerSandboxManager:
    """
    Container Docker persistente per i tool sandbox.
    """

    def __init__(
        self,
        *,
        image: str,
        container_name: str,
        host_workspace_root: str | Path,
        container_workspace_root: str = "/workspace",
        docker_bin: str = "docker",
        auto_create: bool = True,
        extra_run_args: Optional[list[str]] = None,
    ) -> None:
        self.image = str(image).strip()
        self.container_name = str(container_name).strip()
        self.host_workspace_root = Path(host_workspace_root).expanduser().resolve()
        self.container_workspace_root = str(container_workspace_root).strip() or "/workspace"
        self.docker_bin = str(docker_bin).strip() or "docker"
        self.auto_create = bool(auto_create)
        self.extra_run_args = list(extra_run_args or [])

        self.host_workspace_root.mkdir(parents=True, exist_ok=True)

    def ensure_container(self) -> None:
        running, exists = self.inspect_state()

        if running:
            return

        if exists:
            cp = self._docker(
                [self.docker_bin, "start", self.container_name],
                timeout_s=30,
                check=False,
            )
            if cp.returncode != 0:
                detail = (cp.stderr or cp.stdout or "").strip()
                raise RuntimeError(f"failed to start existing sandbox container '{self.container_name}': {detail}")

            running, exists = self.inspect_state()
            if running:
                return

        if not self.auto_create:
            raise RuntimeError(
                f"sandbox container not running and auto_create is disabled: {self.container_name}"
            )

        if not self.image:
            raise RuntimeError("sandbox docker image is empty")

        # cleanup eventuale residuo col nome uguale ma stato incoerente
        cp_rm = self._docker(
            [self.docker_bin, "rm", "-f", self.container_name],
            timeout_s=20,
            check=False,
        )
        _ = cp_rm

        cp_run = self._docker(
            [
                self.docker_bin,
                "run",
                "-d",
                "--name",
                self.container_name,
                "-v",
                f"{self.host_workspace_root}:{self.container_workspace_root}",
                "-w",
                self.container_workspace_root,
                *self.extra_run_args,
                self.image,
                "sleep",
                "infinity",
            ],
            timeout_s=60,
            check=False,
        )
        if cp_run.returncode != 0:
            detail = (cp_run.stderr or cp_run.stdout or "").strip()
            raise RuntimeError(
                f"failed to create sandbox container '{self.container_name}' from image '{self.image}': {detail}"
            )

        running, exists = self.inspect_state()
        if not running:
            raise RuntimeError(f"failed to start sandbox container: {self.container_name}")

    def inspect_state(self) -> tuple[bool, bool]:
        cp = self._docker(
            [
                self.docker_bin,
                "inspect",
                "-f",
                "{{.State.Running}}",
                self.container_name,
            ],
            timeout_s=15,
            check=False,
        )

        if cp.returncode != 0:
            return False, False

        value = (cp.stdout or "").strip().lower()
        return value == "true", True

    def map_host_path(self, path: str | Path) -> str:
        target = Path(path).expanduser().resolve()
        if os.path.commonpath([str(self.host_workspace_root), str(target)]) != str(self.host_workspace_root):
            raise ValueError(f"path outside mounted workspace: {target}")
        rel = target.relative_to(self.host_workspace_root)
        return str(Path(self.container_workspace_root) / rel)

    def prepare_run_dirs(self, run_id: str, relative_cwd: str | Path | None = None) -> tuple[Path, str]:
        host_workdir = self.host_workspace_root / "sandbox_runs" / run_id
        host_workdir.mkdir(parents=True, exist_ok=True)

        container_workdir = f"{self.container_workspace_root.rstrip('/')}/sandbox_runs/{run_id}"

        if relative_cwd is not None:
            rel = str(relative_cwd).strip()
            if rel and rel not in {".", "./"}:
                host_workdir = (host_workdir / rel).resolve()
                runs_root = (self.host_workspace_root / "sandbox_runs").resolve()
                if os.path.commonpath([str(runs_root), str(host_workdir)]) != str(runs_root):
                    raise ValueError("invalid relative_cwd outside sandbox_runs")
                host_workdir.mkdir(parents=True, exist_ok=True)
                container_workdir = f"{container_workdir.rstrip('/')}/{rel}"

        return host_workdir, container_workdir

    def exec(
        self,
        argv: list[str],
        *,
        env: dict[str, str] | None = None,
        input_bytes: bytes | None = None,
        timeout_s: int = 180,
        relative_cwd: str | Path | None = None,
    ) -> DockerSandboxRun:
        self.ensure_container()

        run_id = uuid.uuid4().hex[:12]
        host_workdir, container_workdir = self.prepare_run_dirs(run_id, relative_cwd=relative_cwd)

        self._docker(
            [self.docker_bin, "exec", self.container_name, "mkdir", "-p", container_workdir],
            timeout_s=15,
        )

        exec_cmd = [self.docker_bin, "exec", "-i", "-w", container_workdir]
        for key, value in (env or {}).items():
            exec_cmd.extend(["-e", f"{str(key)}={str(value)}"])
        exec_cmd.append(self.container_name)
        exec_cmd.extend([str(x) for x in argv])

        t0 = time.time()
        try:
            cp = subprocess.run(
                exec_cmd,
                input=input_bytes,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=int(timeout_s),
                check=False,
            )
            dur = time.time() - t0
            stdout = (cp.stdout or b"").decode("utf-8", errors="ignore")
            stderr = (cp.stderr or b"").decode("utf-8", errors="ignore")

            run = DockerSandboxRun(
                run_id=run_id,
                backend="docker",
                host_workdir=host_workdir,
                container_workdir=container_workdir,
                cmd=argv,
                returncode=int(cp.returncode),
                stdout=stdout,
                stderr=stderr,
                duration_s=dur,
                timeout_s=int(timeout_s),
                ok=(cp.returncode == 0),
            )
            self._persist(run)
            return run

        except subprocess.TimeoutExpired as e:
            dur = time.time() - t0
            stdout = (getattr(e, "stdout", None) or b"").decode("utf-8", errors="ignore")
            stderr = (getattr(e, "stderr", None) or b"").decode("utf-8", errors="ignore")
            if stderr:
                stderr += "\n"
            stderr += f"timeout after {int(timeout_s)}s"

            run = DockerSandboxRun(
                run_id=run_id,
                backend="docker",
                host_workdir=host_workdir,
                container_workdir=container_workdir,
                cmd=argv,
                returncode=124,
                stdout=stdout,
                stderr=stderr,
                duration_s=dur,
                timeout_s=int(timeout_s),
                ok=False,
            )
            self._persist(run)
            return run

    def _persist(self, run: DockerSandboxRun) -> None:
        try:
            run.host_workdir.mkdir(parents=True, exist_ok=True)
            (run.host_workdir / "stdout.txt").write_text(run.stdout or "", encoding="utf-8")
            (run.host_workdir / "stderr.txt").write_text(run.stderr or "", encoding="utf-8")
            manifest = {
                "run_id": run.run_id,
                "backend": run.backend,
                "cmd": run.cmd,
                "returncode": run.returncode,
                "ok": run.ok,
                "duration_s": round(run.duration_s, 3),
                "timeout_s": run.timeout_s,
                "host_workdir": str(run.host_workdir),
                "container_workdir": run.container_workdir,
            }
            (run.host_workdir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _docker(
        self,
        argv: list[str],
        *,
        timeout_s: int,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        cp = subprocess.run(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout_s,
            check=False,
        )
        if check and cp.returncode != 0:
            raise RuntimeError(
                f"docker command failed ({cp.returncode}): {shlex.join(argv)}\n{(cp.stderr or '').strip()}"
            )
        return cp


class DockerRunner:
    """
    Runner compatibile con TerminalToolBase.
    """

    def __init__(
        self,
        *,
        allowed_bins: Iterable[str],
        workspace_root: str | Path,
        image: str,
        container_name: str,
        container_workspace_root: str = "/workspace",
        docker_bin: str = "docker",
        timeout_s: int = 180,
        max_output_bytes: int = 200_000,
        extra_env: Optional[dict[str, str]] = None,
        auto_create: bool = True,
        extra_run_args: Optional[list[str]] = None,
    ) -> None:
        self.allowed_bins = {str(x) for x in allowed_bins if str(x).strip()}
        self.timeout_s = int(timeout_s)
        self.max_output_bytes = int(max_output_bytes)
        self.extra_env = dict(extra_env or {})
        self.manager = PersistentDockerSandboxManager(
            image=image,
            container_name=container_name,
            host_workspace_root=workspace_root,
            container_workspace_root=container_workspace_root,
            docker_bin=docker_bin,
            auto_create=auto_create,
            extra_run_args=extra_run_args,
        )

    def _is_allowed(self, argv: list[str]) -> bool:
        if not argv:
            return False
        exe = os.path.basename(str(argv[0]))
        return exe in {os.path.basename(x) for x in self.allowed_bins}

    def map_host_path(self, path: str | Path) -> str:
        return self.manager.map_host_path(path)

    def run(
        self,
        argv: list[str],
        *,
        timeout_s: int | None = None,
        env: dict[str, str] | None = None,
        input_bytes: bytes | None = None,
        relative_cwd: str | Path | None = None,
    ) -> DockerSandboxRun:
        argv = [str(x) for x in (argv or [])]
        if not self._is_allowed(argv):
            run_id = uuid.uuid4().hex[:12]
            host_workdir = self.manager.host_workspace_root / "sandbox_runs" / run_id
            host_workdir.mkdir(parents=True, exist_ok=True)
            run = DockerSandboxRun(
                run_id=run_id,
                backend="docker",
                host_workdir=host_workdir,
                container_workdir=f"{self.manager.container_workspace_root.rstrip('/')}/sandbox_runs/{run_id}",
                cmd=argv,
                returncode=126,
                stdout="",
                stderr=f"command not allowed: {shlex.join(argv)}",
                duration_s=0.0,
                timeout_s=0,
                ok=False,
            )
            self.manager._persist(run)
            return run

        merged_env = dict(self.extra_env)
        if env:
            merged_env.update({str(k): str(v) for k, v in env.items()})

        run = self.manager.exec(
            argv,
            env=merged_env,
            input_bytes=input_bytes,
            timeout_s=int(timeout_s or self.timeout_s),
            relative_cwd=relative_cwd,
        )

        stdout = (run.stdout or "")[: self.max_output_bytes]
        stderr = (run.stderr or "")[: self.max_output_bytes]

        trimmed = DockerSandboxRun(
            run_id=run.run_id,
            backend=run.backend,
            host_workdir=run.host_workdir,
            container_workdir=run.container_workdir,
            cmd=run.cmd,
            returncode=run.returncode,
            stdout=stdout,
            stderr=stderr,
            duration_s=run.duration_s,
            timeout_s=run.timeout_s,
            ok=run.ok,
        )
        self.manager._persist(trimmed)
        return trimmed
