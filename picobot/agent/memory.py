from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from picobot.config.schema import Config, MemoryLimits
from picobot.memory.stores import MemoryRepository
from picobot.session.manager import Session


@dataclass(frozen=True)
class MemoryPaths:
    workspace: Path
    session_root: Path

    @property
    def memory_root(self) -> Path:
        return self.workspace / "memory"

    @property
    def global_memory(self) -> Path:
        return self.memory_root / "MEMORY.md"

    @property
    def history(self) -> Path:
        return self.session_root / "HISTORY.md"

    @property
    def summary(self) -> Path:
        return self.session_root / "SUMMARY.md"


class MemoryManager:
    """
    Compatibility layer.

    Espone ancora l'API usata dal codice attuale, ma usa i nuovi store:
    - state.json
    - history.jsonl (+ mirror HISTORY.md)
    - summary.json (+ mirror SUMMARY.md)
    - facts.jsonl (+ mirror MEMORY.md)
    """

    def __init__(self, *, repo: MemoryRepository, limits: MemoryLimits) -> None:
        self.repo = repo
        self.limits = limits

    def init_files(self) -> None:
        self.repo.ensure_all()

    def clear_all(self) -> None:
        self.repo.clear_all()

    def append_turn(self, role: str, content: str) -> None:
        self.repo.history.append(role, content)
        self._truncate_history_if_needed()

    def remember(self, item: str) -> None:
        self.repo.facts.add(item)

    def memory_items(self) -> list[str]:
        return self.repo.facts.read_items()

    def search_memory(self, query: str) -> tuple[str, float, str] | None:
        return self.repo.facts.search(query)

    def read_summary(self) -> str:
        self.init_files()
        text = self.repo.summary.read_text().strip()
        return text or "# Session Summary\n"

    def read_memory(self) -> str:
        self.init_files()
        items = self.repo.facts.read_items()
        if not items:
            return "# Memory\n"
        return "# Memory\n\n" + "\n".join(f"- {item}" for item in items) + "\n"

    def read_history_tail(self, n_lines: int) -> str:
        self.init_files()
        return self.repo.history.read_tail_markdown(n_lines)

    def _truncate_history_if_needed(self) -> None:
        rows = self.repo.history.read_entries()
        if len(rows) <= self.limits.max_history_lines:
            return

        kept = rows[-self.limits.tail_lines:] if self.limits.tail_lines > 0 else []

        self.repo.history.path.write_text("", encoding="utf-8")
        for row in kept:
            self.repo.history.append(
                str(row.get("role") or "unknown"),
                str(row.get("content") or ""),
                message_type=str(row.get("type") or "text"),
            )


def make_memory_manager(cfg: Config, session: Session, workspace: Path) -> MemoryManager:
    repo = MemoryRepository(Path(workspace).expanduser().resolve(), session)
    return MemoryManager(repo=repo, limits=cfg.memory_limits)
