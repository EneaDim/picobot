from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Iterable

from picobot.runtime_config import cfg_get
from picobot.sandbox.docker_runner import DockerRunner
from picobot.sandbox.runner import SandboxRunner
from picobot.tools.sandbox_exec import ExecResult


def _get_obj_path(obj: Any, path: str, default: Any = None) -> Any:
    current = obj
    for part in str(path).split("."):
        if current is None:
            return default
        if hasattr(current, part):
            current = getattr(current, part)
        else:
            return default
    return current


class TerminalToolBase:
    """
    Base unificata per tool terminali.

    Backend deciso dalla config:
      sandbox.runtime.backend = "local" | "docker"
    """

    def __init__(
        self,
        *,
        allowed_bins: Iterable[str],
        cfg: Any | None = None,
        timeout_s: int = 180,
        max_output_bytes: int = 200_000,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.cfg = cfg
        self.allowed_bins = [str(x) for x in allowed_bins if str(x).strip()]
        self.timeout_s = int(timeout_s)
        self.max_output_bytes = int(max_output_bytes)
        self.extra_env = dict(extra_env or {})

        self.workspace_root = self._workspace_root()
        self.runs_root = self._runs_root()
        self.backend = self._backend_name()

        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)

        self._runner = self._build_runner()

    def _cfg(self, path: str, default: Any = None) -> Any:
        if self.cfg is not None:
            value = _get_obj_path(self.cfg, path, default)
            if value is not default:
                return value
        return cfg_get(path, default)

    def _workspace_root(self) -> Path:
        explicit = str(self._cfg("sandbox.runtime.workspace_root", "") or "").strip()
        if explicit:
            return Path(explicit).expanduser().resolve()

        root = str(self._cfg("workspace", ".picobot/workspace") or ".picobot/workspace").strip()
        return Path(root).expanduser().resolve()

    def _runs_root(self) -> Path:
        explicit = str(self._cfg("sandbox.runtime.runs_dir", "") or "").strip()
        if explicit:
            return Path(explicit).expanduser().resolve()
        return (self.workspace_root / "sandbox_runs").resolve()

    def _backend_name(self) -> str:
        raw = str(self._cfg("sandbox.runtime.backend", "local") or "local").strip().lower()
        return "docker" if raw == "docker" else "local"

    def _tools_root(self) -> Path:
        raw = str(self._cfg("tools.base_dir", "") or "").strip()
        if raw:
            target = Path(raw).expanduser().resolve()
        else:
            target = (self.workspace_root / "tools").resolve()

        try:
            if os.path.commonpath([str(self.workspace_root), str(target)]) != str(self.workspace_root):
                return (self.workspace_root / "tools").resolve()
        except Exception:
            return (self.workspace_root / "tools").resolve()

        return target

    def _docker_tools_root(self, container_workspace_root: str) -> str:
        tools_root = self._tools_root()
        rel = tools_root.relative_to(self.workspace_root)
        return str((Path(container_workspace_root) / rel).as_posix())

    def _docker_piper_voices(self) -> str:
        values = self._cfg("tools.piper.voices", []) or []
        out: list[str] = []
        seen: set[str] = set()

        for value in values:
            voice = str(value or "").strip()
            if voice and voice not in seen:
                seen.add(voice)
                out.append(voice)

        return ",".join(out)

    def _merge_docker_bootstrap_env(self, extra_run_args: list[str], *, container_workspace_root: str) -> list[str]:
        args = list(extra_run_args or [])

        joined = " ".join(args)
        if "PICO_TOOLS_ROOT=" not in joined:
            args.extend(["-e", f"PICO_TOOLS_ROOT={self._docker_tools_root(container_workspace_root)}"])

        voices = self._docker_piper_voices()
        if voices and "PICO_PIPER_VOICES=" not in joined:
            args.extend(["-e", f"PICO_PIPER_VOICES={voices}"])

        if "PICO_BOOTSTRAP_TOOLS=" not in joined:
            args.extend(["-e", "PICO_BOOTSTRAP_TOOLS=1"])

        return args

    def _build_runner(self):
        if self.backend == "docker":
            image = str(self._cfg("sandbox.runtime.docker.image", "picobot-sandbox:latest") or "picobot-sandbox:latest").strip()
            container_name = str(self._cfg("sandbox.runtime.docker.container_name", "picobot-sandbox") or "picobot-sandbox").strip()
            container_workspace_root = str(self._cfg("sandbox.runtime.docker.container_workspace_root", "/workspace") or "/workspace").strip()
            docker_bin = str(self._cfg("sandbox.runtime.docker.docker_bin", "docker") or "docker").strip()
            auto_create = bool(self._cfg("sandbox.runtime.docker.auto_create", True))
            extra_run_args = list(self._cfg("sandbox.runtime.docker.extra_run_args", []) or [])
            extra_run_args = self._merge_docker_bootstrap_env(extra_run_args, container_workspace_root=container_workspace_root)

            return DockerRunner(
                allowed_bins=self.allowed_bins,
                workspace_root=self.workspace_root,
                image=image,
                container_name=container_name,
                container_workspace_root=container_workspace_root,
                docker_bin=docker_bin,
                timeout_s=self.timeout_s,
                max_output_bytes=self.max_output_bytes,
                extra_env=self.extra_env,
                auto_create=auto_create,
                extra_run_args=extra_run_args,
            )

        return SandboxRunner(
            allowed_bins=self.allowed_bins,
            workspace_root=self.workspace_root,
            runs_root=self.runs_root,
            timeout_s=self.timeout_s,
            max_output_bytes=self.max_output_bytes,
            extra_env=self.extra_env,
        )

    @property
    def runner(self):
        return self._runner

    def map_host_path(self, path: str | Path) -> str:
        return self.runner.map_host_path(path)

    def resolve_workspace_path(self, value: str | Path) -> Path:
        raw = str(value or "").strip()
        if not raw:
            return self.workspace_root

        p = Path(raw).expanduser()
        target = p.resolve() if p.is_absolute() else (self.workspace_root / p).resolve()

        if os.path.commonpath([str(self.workspace_root), str(target)]) != str(self.workspace_root):
            raise ValueError(f"path outside workspace root: {target}")

        return target

    def run_cmd(
        self,
        argv: list[str],
        *,
        prefix: str,
        timeout_s: int | None = None,
        input_bytes: bytes | None = None,
        env: dict[str, str] | None = None,
        relative_cwd: str | Path | None = None,
    ) -> ExecResult:
        _ = prefix
        run = self.runner.run(
            argv,
            timeout_s=timeout_s,
            env=env,
            input_bytes=input_bytes,
            relative_cwd=relative_cwd,
        )
        return run.to_exec_result()

    @staticmethod
    def ok(data: dict[str, Any], *, language: str | None = None) -> dict:
        return {"ok": True, "data": data, "error": None, "language": language}

    @staticmethod
    def fail(msg: str, *, language: str | None = None, data: dict[str, Any] | None = None) -> dict:
        return {"ok": False, "data": data or {}, "error": msg, "language": language}
