from __future__ import annotations

from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore


def pdf_to_text(path: Path) -> str:
    if PdfReader is None:
        raise RuntimeError("pypdf is not installed. Install with: pip install pypdf")
    reader = PdfReader(str(path))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n".join(parts).strip()


def chunk_text(text: str, chunk_chars: int = 1200, overlap: int = 150) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    chunks: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        j = min(n, i + chunk_chars)
        chunk = text[i:j].strip()
        if chunk:
            chunks.append(chunk)
        i = max(i + 1, j - overlap)
    return chunks


def ingest_dir(source_dir: Path, store_dir: Path) -> dict:
    """
    Deterministic ingest from source_dir into store_dir.

    - Reads .txt/.md/.csv/.json/.yaml/.yml and .pdf (if pypdf installed)
    - Writes chunks to store_dir/chunks/*.md using add_document_chunks
    - Rebuilds BM25 index (store_dir/index.json)
    """
    from picobot.retrieval.store import KBStore, add_document_chunks

    source_dir = Path(source_dir)
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)

    kb = KBStore(store_dir)  # store_dir is already the kb folder in your layout

    text_exts = {".txt", ".md", ".markdown", ".rst", ".log", ".csv", ".json", ".yaml", ".yml"}

    docs = 0
    chunks_total = 0
    skipped = 0

    if not source_dir.exists():
        kb.rebuild_index()
        return {"ok": True, "docs": 0, "chunks": 0, "skipped": 0, "note": "source_dir missing"}

    for fp in sorted(source_dir.rglob("*")):
        if not fp.is_file():
            continue
        ext = fp.suffix.lower()

        try:
            if ext == ".pdf":
                text = pdf_to_text(fp)
            elif ext in text_exts or ext == "":
                text = fp.read_text(encoding="utf-8", errors="ignore")
            else:
                skipped += 1
                continue
        except Exception:
            skipped += 1
            continue

        ch = chunk_text(text)
        if not ch:
            skipped += 1
            continue

        add_document_chunks(kb.kb_root, fp.name, ch)
        docs += 1
        chunks_total += len(ch)

    kb.rebuild_index()
    return {"ok": True, "docs": docs, "chunks": chunks_total, "skipped": skipped}
