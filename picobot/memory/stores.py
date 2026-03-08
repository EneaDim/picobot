from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from picobot.session.manager import Session

_WORD = re.compile(r"[a-zA-Z0-9_]+")
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "or", "in", "on", "for", "with", "what", "which", "who",
    "il", "lo", "la", "i", "gli", "le", "un", "una", "uno", "e", "o", "di", "del", "della", "dei", "degli", "che", "cosa", "qual", "quale", "quali", "chi",
}
_Q_CUES = ("what", "which", "who", "qual", "quale", "quali", "chi", "cosa", "dimmi", "tell me")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        return dict(default or {})
    return dict(default or {})


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def _append_jsonl(path: Path, item: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def _tokenize(text: str) -> set[str]:
    toks = {m.group(0).lower() for m in _WORD.finditer(text or "")}
    return {t for t in toks if t and t not in _STOPWORDS}


@dataclass(frozen=True)
class SessionStateStore:
    path: Path

    def ensure(self) -> None:
        if not self.path.exists():
            _write_json(self.path, {})

    def read(self) -> dict[str, Any]:
        self.ensure()
        return _read_json(self.path, {})

    def update(self, data: dict[str, Any]) -> dict[str, Any]:
        cur = self.read()
        cur.update(data or {})
        _write_json(self.path, cur)
        return cur

    def clear(self) -> None:
        _write_json(self.path, {})


@dataclass(frozen=True)
class HistoryStore:
    path: Path
    legacy_path: Path

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        if not self.legacy_path.exists():
            self.legacy_path.write_text("# Session History\n\n", encoding="utf-8")

    def append(self, role: str, content: str, message_type: str = "text") -> None:
        self.ensure()
        item = {
            "ts": _utc_now(),
            "role": str(role).strip(),
            "content": (content or "").strip(),
            "type": message_type,
        }
        _append_jsonl(self.path, item)
        self._sync_legacy_markdown()

    def read_entries(self) -> list[dict[str, Any]]:
        self.ensure()
        return _read_jsonl(self.path)

    def read_recent_messages(self, limit: int = 16) -> list[dict[str, str]]:
        rows = self.read_entries()
        out: list[dict[str, str]] = []
        for row in rows[-max(0, limit):]:
            role = str(row.get("role") or "").strip()
            content = str(row.get("content") or "").strip()
            if role in {"user", "assistant", "system"} and content:
                out.append({"role": role, "content": content})
        return out

    def read_tail_markdown(self, n_lines: int) -> str:
        self.ensure()
        lines = self.legacy_path.read_text(encoding="utf-8").splitlines()
        kept = lines[-n_lines:] if n_lines > 0 else []
        return "\n".join(kept).strip() + "\n"

    def clear(self) -> None:
        self.ensure()
        self.path.write_text("", encoding="utf-8")
        self.legacy_path.write_text("# Session History\n\n", encoding="utf-8")

    def _sync_legacy_markdown(self) -> None:
        rows = self.read_entries()
        parts = ["# Session History", ""]
        for row in rows:
            role = str(row.get("role") or "unknown").strip() or "unknown"
            ts = str(row.get("ts") or "").strip()
            content = str(row.get("content") or "").strip()
            parts.append(f"## {role}")
            parts.append("")
            parts.append(f"- [{ts}] {content}" if ts else f"- {content}")
            parts.append("")
        self.legacy_path.write_text("\n".join(parts).strip() + "\n", encoding="utf-8")


@dataclass(frozen=True)
class SummaryStore:
    path: Path
    legacy_path: Path

    def ensure(self) -> None:
        if not self.path.exists():
            _write_json(self.path, {
                "updated_at": "",
                "summary_text": "",
                "key_topics": [],
                "open_loops": [],
            })
        if not self.legacy_path.exists():
            self.legacy_path.write_text("# Session Summary\n\n", encoding="utf-8")

    def read(self) -> dict[str, Any]:
        self.ensure()
        data = _read_json(self.path, {})
        if "summary_text" not in data:
            data["summary_text"] = ""
        if "key_topics" not in data:
            data["key_topics"] = []
        if "open_loops" not in data:
            data["open_loops"] = []
        if "updated_at" not in data:
            data["updated_at"] = ""
        return data

    def read_text(self) -> str:
        data = self.read()
        return str(data.get("summary_text") or "").strip()

    def write(
        self,
        *,
        summary_text: str,
        key_topics: list[str] | None = None,
        open_loops: list[str] | None = None,
    ) -> None:
        self.ensure()
        payload = {
            "updated_at": _utc_now(),
            "summary_text": (summary_text or "").strip(),
            "key_topics": list(key_topics or []),
            "open_loops": list(open_loops or []),
        }
        _write_json(self.path, payload)
        self._sync_legacy_markdown(payload)

    def clear(self) -> None:
        self.write(summary_text="", key_topics=[], open_loops=[])

    def _sync_legacy_markdown(self, payload: dict[str, Any]) -> None:
        lines = ["# Session Summary", ""]
        summary_text = str(payload.get("summary_text") or "").strip()
        key_topics = [str(x).strip() for x in payload.get("key_topics") or [] if str(x).strip()]
        open_loops = [str(x).strip() for x in payload.get("open_loops") or [] if str(x).strip()]

        if summary_text:
            lines.extend([summary_text, ""])
        if key_topics:
            lines.append("## Key Topics")
            lines.append("")
            lines.extend(f"- {item}" for item in key_topics)
            lines.append("")
        if open_loops:
            lines.append("## Open Loops")
            lines.append("")
            lines.extend(f"- {item}" for item in open_loops)
            lines.append("")

        self.legacy_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


@dataclass(frozen=True)
class MemoryFactsStore:
    path: Path
    legacy_path: Path

    def ensure(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")
        if not self.legacy_path.exists():
            self.legacy_path.write_text("# Memory\n\n", encoding="utf-8")

    def add(self, content: str, *, scope: str = "user", confidence: float = 1.0, source: str = "conversation") -> None:
        self.ensure()
        value = (content or "").strip()
        if not value:
            return

        existing = self.read_items()
        if value in existing:
            return

        _append_jsonl(self.path, {
            "fact_id": f"fact-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S%f')}",
            "scope": scope,
            "content": value,
            "confidence": float(confidence),
            "source": source,
            "updated_at": _utc_now(),
        })
        self._sync_legacy_markdown()

    def read_rows(self) -> list[dict[str, Any]]:
        self.ensure()
        return _read_jsonl(self.path)

    def read_items(self) -> list[str]:
        return [str(row.get("content") or "").strip() for row in self.read_rows() if str(row.get("content") or "").strip()]

    def search(self, query: str) -> tuple[str, float, str] | None:
        items = self.read_items()
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

        for item in items:
            item_low = item.lower()
            item_tokens = _tokenize(item_low)
            if not item_tokens:
                continue
            overlap = len(q_tokens & item_tokens)
            score = overlap / max(1, len(q_tokens))

            parts = item.split(None, 1)
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
                best_item = item
                best_mode = mode

        if not best_item or best_score < 0.35:
            return None
        return best_item, float(best_score), best_mode

    def clear(self) -> None:
        self.ensure()
        self.path.write_text("", encoding="utf-8")
        self.legacy_path.write_text("# Memory\n\n", encoding="utf-8")

    def _sync_legacy_markdown(self) -> None:
        items = self.read_items()
        lines = ["# Memory", ""]
        lines.extend(f"- {item}" for item in items)
        if items:
            lines.append("")
        self.legacy_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


@dataclass(frozen=True)
class MemoryRepository:
    workspace: Path
    session: Session

    @property
    def session_root(self) -> Path:
        return self.session.root

    @property
    def memory_root(self) -> Path:
        return self.workspace / "memory"

    @property
    def state(self) -> SessionStateStore:
        return SessionStateStore(self.session_root / "state.json")

    @property
    def history(self) -> HistoryStore:
        return HistoryStore(
            self.session_root / "history.jsonl",
            self.session_root / "HISTORY.md",
        )

    @property
    def summary(self) -> SummaryStore:
        return SummaryStore(
            self.session_root / "summary.json",
            self.session_root / "SUMMARY.md",
        )

    @property
    def facts(self) -> MemoryFactsStore:
        return MemoryFactsStore(
            self.memory_root / "facts.jsonl",
            self.memory_root / "MEMORY.md",
        )

    def ensure_all(self) -> None:
        self.state.ensure()
        self.history.ensure()
        self.summary.ensure()
        self.facts.ensure()

    def clear_all(self) -> None:
        self.ensure_all()
        self.state.clear()
        self.history.clear()
        self.summary.clear()
        self.facts.clear()
