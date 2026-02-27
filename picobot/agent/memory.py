from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from picobot.config.schema import Config, MemoryLimits
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


_WORD = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS = {
    "the","a","an","is","are","was","were","to","of","and","or","in","on","for","with","what","which","who",
    "il","lo","la","i","gli","le","un","una","uno","e","o","di","del","della","dei","degli","che","cosa","qual","quale","quali","chi",
}
_Q_CUES = ("what","which","who","qual","quale","quali","chi","cosa","dimmi","tell me")


def _tokenize(text: str) -> set[str]:
    toks = {m.group(0).lower() for m in _WORD.finditer(text or "")}
    return {t for t in toks if t and t not in _STOPWORDS}


def _tail_lines(lines: list[str], n: int) -> list[str]:
    return lines[-n:] if n > 0 else []


class MemoryManager:
    def __init__(self, paths: MemoryPaths, limits: MemoryLimits) -> None:
        self.paths = paths
        self.limits = limits

    def init_files(self) -> None:
        self.paths.memory_root.mkdir(parents=True, exist_ok=True)
        self.paths.session_root.mkdir(parents=True, exist_ok=True)
        if not self.paths.global_memory.exists():
            self.paths.global_memory.write_text("# Memory\n\n", encoding="utf-8")
        if not self.paths.history.exists():
            self.paths.history.write_text("# Session History\n\n", encoding="utf-8")
        if not self.paths.summary.exists():
            self.paths.summary.write_text("# Session Summary\n\n", encoding="utf-8")

    def clear_all(self) -> None:
        self.init_files()
        self.paths.global_memory.write_text("# Memory\n\n", encoding="utf-8")
        self.paths.history.write_text("# Session History\n\n", encoding="utf-8")
        self.paths.summary.write_text("# Session Summary\n\n", encoding="utf-8")

    def append_turn(self, role: str, content: str) -> None:
        self.init_files()
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        block = f"\n## {role}\n\n- [{ts}] {content.strip()}\n"
        self.paths.history.write_text(self.paths.history.read_text(encoding="utf-8") + block, encoding="utf-8")
        self._truncate_history_if_needed()

    def remember(self, item: str) -> None:
        self.init_files()
        item = item.strip()
        if not item:
            return
        existing = self.paths.global_memory.read_text(encoding="utf-8")
        line = f"- {item}\n"
        if line.strip() in existing:
            return
        self.paths.global_memory.write_text(existing + line, encoding="utf-8")

    def memory_items(self) -> list[str]:
        self.init_files()
        lines = self.paths.global_memory.read_text(encoding="utf-8").splitlines()
        out: list[str] = []
        for ln in lines:
            ln = ln.strip()
            if ln.startswith("- "):
                v = ln[2:].strip()
                if v:
                    out.append(v)
        return out

    def search_memory(self, query: str) -> tuple[str, float, str] | None:
        items = self.memory_items()
        if not items:
            return None

        q = (query or "").strip().lower()
        q_tokens = _tokenize(q)
        if not q_tokens:
            return None

        looks_like_recall = ("?" in q) or any(q.startswith(c) for c in _Q_CUES) or any(c in q for c in _Q_CUES)
        if not looks_like_recall:
            return None

        best_item = None
        best_score = 0.0
        best_mode = "full"

        for it in items:
            it_low = it.lower()
            it_tokens = _tokenize(it_low)
            if not it_tokens:
                continue
            overlap = len(q_tokens & it_tokens)
            score = overlap / max(1, len(q_tokens))

            parts = it.split(None, 1)
            if len(parts) == 2:
                key, rest = parts[0].lower(), parts[1].strip()
                if key in q_tokens and rest:
                    score += 0.35
                    mode = "key_rest"
                else:
                    mode = "full"
            else:
                mode = "full"

            if score > best_score:
                best_score = score
                best_item = it
                best_mode = mode

        if not best_item or best_score < 0.35:
            return None
        return best_item, float(best_score), best_mode

    def read_summary(self) -> str:
        self.init_files()
        return self.paths.summary.read_text(encoding="utf-8")

    def read_memory(self) -> str:
        self.init_files()
        return self.paths.global_memory.read_text(encoding="utf-8")

    def read_history_tail(self, n_lines: int) -> str:
        self.init_files()
        lines = self.paths.history.read_text(encoding="utf-8").splitlines()
        return "\n".join(_tail_lines(lines, n_lines)).strip() + "\n"

    def _truncate_history_if_needed(self) -> None:
        self.init_files()
        lines = self.paths.history.read_text(encoding="utf-8").splitlines()
        if len(lines) <= self.limits.max_history_lines:
            return
        kept = _tail_lines(lines, self.limits.tail_lines)
        if kept and not kept[0].startswith("# Session History"):
            kept = ["# Session History", ""] + kept
        self.paths.history.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")


def make_memory_manager(cfg: Config, session: Session, workspace: Path) -> MemoryManager:
    paths = MemoryPaths(workspace=workspace, session_root=session.root)
    return MemoryManager(paths=paths, limits=cfg.memory_limits)
