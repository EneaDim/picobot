from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


def sanitize_session_id(s: str) -> str:
    s = (s or "default").strip()
    if not s:
        return "default"
    s = s.replace("/", "-").replace("\\", "-")
    s = re.sub(r"[^a-zA-Z0-9._-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "default"


@dataclass(frozen=True)
class Session:
    session_id: str
    root: Path
    workspace: Path

    @property
    def state_file(self) -> Path:
        return self.root / "state.json"

    @property
    def history_file(self) -> Path:
        return self.root / "HISTORY.md"

    @property
    def summary_file(self) -> Path:
        return self.root / "SUMMARY.md"

    @property
    def memory_file(self) -> Path:
        # global memory file (compat with older tests)
        return self.workspace / "memory" / "MEMORY.md"

    def get_state(self) -> dict:
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return {}

    def set_state(self, data: dict) -> None:
        cur = self.get_state()
        cur.update(data or {})
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(cur, indent=2), encoding="utf-8")


class SessionManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.sessions_root = self.workspace / "memory" / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)

        # ensure global memory exists
        mem = self.workspace / "memory" / "MEMORY.md"
        mem.parent.mkdir(parents=True, exist_ok=True)
        if not mem.exists():
            mem.write_text("# Memory\n\n", encoding="utf-8")

    def get(self, session_id: str) -> Session:
        sid = sanitize_session_id(session_id)
        root = self.sessions_root / sid
        root.mkdir(parents=True, exist_ok=True)

        # ensure files exist
        hf = root / "HISTORY.md"
        sf = root / "SUMMARY.md"
        if not hf.exists():
            hf.write_text("# Session History\n\n", encoding="utf-8")
        if not sf.exists():
            sf.write_text("# Session Summary\n\n", encoding="utf-8")
        if not (root / "state.json").exists():
            (root / "state.json").write_text("{}", encoding="utf-8")

        return Session(session_id=sid, root=root, workspace=self.workspace)

    def list(self) -> list[str]:
        if not self.sessions_root.exists():
            return []
        return sorted([d.name for d in self.sessions_root.iterdir() if d.is_dir()])
