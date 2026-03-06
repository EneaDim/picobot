from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class KBPaths:
    name: str
    root: Path
    source_dir: Path
    store_dir: Path
    chunks_dir: Path
    index_dir: Path
    manifest_path: Path


_SAFE_NAME_RX = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_kb_name(name: str) -> str:
    s = (name or "").strip()
    s = Path(s).stem
    s = _SAFE_NAME_RX.sub("-", s).strip("-.")
    return s or "default"


def kb_paths(workspace: Path, kb_name: str) -> KBPaths:
    name = sanitize_kb_name(kb_name)
    root = (workspace / "docs" / name).resolve()
    source_dir = root / "source"
    store_dir = root / "kb"
    chunks_dir = store_dir / "chunks"
    index_dir = store_dir / "index"
    manifest_path = store_dir / "manifest.json"
    return KBPaths(
        name=name,
        root=root,
        source_dir=source_dir,
        store_dir=store_dir,
        chunks_dir=chunks_dir,
        index_dir=index_dir,
        manifest_path=manifest_path,
    )


def ensure_kb_dirs(workspace: Path, kb_name: str) -> KBPaths:
    p = kb_paths(workspace, kb_name)
    p.source_dir.mkdir(parents=True, exist_ok=True)
    p.chunks_dir.mkdir(parents=True, exist_ok=True)
    p.index_dir.mkdir(parents=True, exist_ok=True)
    return p


def copy_source_file(workspace: Path, kb_name: str, src_file: Path) -> Path:
    p = ensure_kb_dirs(workspace, kb_name)
    dst = p.source_dir / src_file.name
    shutil.copy2(src_file, dst)
    return dst


def clear_store(workspace: Path, kb_name: str) -> KBPaths:
    p = ensure_kb_dirs(workspace, kb_name)
    if p.store_dir.exists():
        for child in p.store_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
    p.chunks_dir.mkdir(parents=True, exist_ok=True)
    p.index_dir.mkdir(parents=True, exist_ok=True)
    return p


def write_manifest(p: KBPaths, payload: dict) -> None:
    p.manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_manifest(workspace: Path, kb_name: str) -> dict:
    p = kb_paths(workspace, kb_name)
    if not p.manifest_path.exists():
        return {}
    try:
        data = json.loads(p.manifest_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def count_source_files(workspace: Path, kb_name: str) -> int:
    p = kb_paths(workspace, kb_name)
    if not p.source_dir.exists():
        return 0
    return len([x for x in p.source_dir.rglob("*") if x.is_file()])


def count_store_files(workspace: Path, kb_name: str) -> int:
    p = kb_paths(workspace, kb_name)
    if not p.store_dir.exists():
        return 0
    return len([x for x in p.store_dir.rglob("*") if x.is_file()])


def list_kbs(workspace: Path) -> list[str]:
    docs = (workspace / "docs").resolve()
    docs.mkdir(parents=True, exist_ok=True)
    return sorted([p.name for p in docs.iterdir() if p.is_dir()])
