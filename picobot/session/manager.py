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
    def history_jsonl_file(self) -> Path:
        return self.root / "history.jsonl"

    @property
    def summary_file(self) -> Path:
        return self.root / "SUMMARY.md"

    @property
    def summary_json_file(self) -> Path:
        return self.root / "summary.json"

    @property
    def memory_file(self) -> Path:
        return self.workspace / "memory" / "MEMORY.md"

    @property
    def memory_facts_file(self) -> Path:
        return self.workspace / "memory" / "facts.jsonl"

    def get_state(self) -> dict:
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
        except Exception:
            return {}
        return {}

    def set_state(self, data: dict) -> None:
        cur = self.get_state()
        cur.update(data or {})
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")


class SessionManager:
    def __init__(self, workspace: Path) -> None:
        self.workspace = Path(workspace)
        self.sessions_root = self.workspace / "memory" / "sessions"
        self.sessions_root.mkdir(parents=True, exist_ok=True)

        mem_root = self.workspace / "memory"
        mem_root.mkdir(parents=True, exist_ok=True)

        legacy_mem = mem_root / "MEMORY.md"
        if not legacy_mem.exists():
            legacy_mem.write_text("# Memory\n\n", encoding="utf-8")

        facts = mem_root / "facts.jsonl"
        if not facts.exists():
            facts.write_text("", encoding="utf-8")

    def get(self, session_id: str) -> Session:
        sid = sanitize_session_id(session_id)
        root = self.sessions_root / sid
        root.mkdir(parents=True, exist_ok=True)

        state = root / "state.json"
        if not state.exists():
            state.write_text("{}", encoding="utf-8")

        history_md = root / "HISTORY.md"
        if not history_md.exists():
            history_md.write_text("# Session History\n\n", encoding="utf-8")

        history_jsonl = root / "history.jsonl"
        if not history_jsonl.exists():
            history_jsonl.write_text("", encoding="utf-8")

        summary_md = root / "SUMMARY.md"
        if not summary_md.exists():
            summary_md.write_text("# Session Summary\n\n", encoding="utf-8")

        summary_json = root / "summary.json"
        if not summary_json.exists():
            summary_json.write_text(
                json.dumps(
                    {
                        "updated_at": "",
                        "summary_text": "",
                        "key_topics": [],
                        "open_loops": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

        return Session(session_id=sid, root=root, workspace=self.workspace)

    def list(self) -> list[str]:
        if not self.sessions_root.exists():
            return []
        return sorted([d.name for d in self.sessions_root.iterdir() if d.is_dir()])
