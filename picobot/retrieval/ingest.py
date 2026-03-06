from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from picobot.retrieval.embedder import LocalEmbedder
from picobot.retrieval.qdrant_docs_store import DocsQdrantStore
from picobot.retrieval.store import clear_store, ensure_kb_dirs, write_manifest


@dataclass(frozen=True)
class IngestResult:
    kb_name: str
    source_files: int
    chunk_files: int
    manifest_path: Path


def _read_pdf_text(pdf_path: Path) -> str:
    reader = PdfReader(str(pdf_path))
    parts: list[str] = []
    for page in reader.pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            parts.append("")
    return "\n".join(parts).strip()


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def _chunk_text(text: str, *, chunk_chars: int = 1200, overlap_chars: int = 180) -> list[str]:
    t = _normalize_text(text)
    if not t:
        return []
    out: list[str] = []
    i = 0
    n = len(t)
    while i < n:
        chunk = t[i:i + chunk_chars].strip()
        if chunk:
            out.append(chunk)
        if i + chunk_chars >= n:
            break
        i += max(1, chunk_chars - overlap_chars)
    return out


def ingest_kb(workspace: Path, kb_name: str) -> IngestResult:
    p = clear_store(workspace, kb_name)
    source_files = sorted([x for x in p.source_dir.rglob("*") if x.is_file()])
    chunk_payloads: list[dict] = []

    for src in source_files:
        if src.suffix.lower() != ".pdf":
            continue

        text = _read_pdf_text(src)
        chunks = _chunk_text(text)
        for idx, chunk in enumerate(chunks):
            chunk_id = f"{src.stem}-{idx:04d}"
            payload = {
                "id": chunk_id,
                "source_file": src.name,
                "chunk_index": idx,
                "page": None,
                "section": "",
                "text": chunk,
                "kb_name": p.name,
                "doc_id": src.name,
                "mime_type": "application/pdf",
            }
            chunk_payloads.append(payload)
            (p.chunks_dir / f"{chunk_id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    embedder = LocalEmbedder()
    store = DocsQdrantStore()

    if chunk_payloads:
        vectors = embedder.embed([c["text"] for c in chunk_payloads])
        store.ensure_collection(len(vectors[0]))
        points = []
        for payload, vec in zip(chunk_payloads, vectors):
            points.append(
                {
                    "id": payload["id"],
                    "vector": vec,
                    "payload": payload,
                }
            )
        store.upsert(points)

    manifest = {
        "kb_name": p.name,
        "source_files": len(source_files),
        "chunk_files": len(chunk_payloads),
        "layout": {
            "source_dir": str(p.source_dir),
            "chunks_dir": str(p.chunks_dir),
            "index_dir": str(p.index_dir),
            "manifest_path": str(p.manifest_path),
        },
        "qdrant": {
            "collection": "docs_index",
            "path": ".picobot/qdrant",
        },
    }
    write_manifest(p, manifest)

    # simple compatibility marker files
    (p.index_dir / "collection.txt").write_text("docs_index\n", encoding="utf-8")
    (p.index_dir / "count.txt").write_text(str(len(chunk_payloads)) + "\n", encoding="utf-8")

    return IngestResult(
        kb_name=p.name,
        source_files=len(source_files),
        chunk_files=len(chunk_payloads),
        manifest_path=p.manifest_path,
    )


def ingest_dir(*, source_dir: Path, store_dir: Path) -> None:
    workspace = store_dir.parent.parent.parent
    kb_name = store_dir.parent.name
    ingest_kb(Path(workspace), kb_name)
