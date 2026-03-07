from __future__ import annotations

# Ingest KB completo:
# - legge PDF da docs/<kb>/source/
# - chunking page-aware
# - salva chunk JSON locali
# - ricostruisce indice BM25 locale
# - cancella la KB da Qdrant
# - re-indicizza i nuovi chunk in Qdrant
#
# Questo file è volutamente più "service-like":
# - tutta la logica di ingest è qui
# - niente scorciatoie sparse altrove
# - rebuild completo e coerente
import hashlib
from pathlib import Path

from pypdf import PdfReader

from picobot.retrieval.bm25 import BM25Index
from picobot.retrieval.embedder import LocalEmbedder
from picobot.retrieval.qdrant_docs_store import DocsQdrantStore
from picobot.retrieval.schemas import DocumentChunk, IngestResult
from picobot.retrieval.store import clear_store, ensure_kb_dirs, write_chunk, write_manifest
from picobot.runtime_config import cfg_get


def _normalize_text(text: str) -> str:
    """
    Normalizzazione minima del testo estratto.
    """
    return " ".join((text or "").split()).strip()


def _page_texts_from_pdf(pdf_path: Path) -> list[tuple[int, str]]:
    """
    Estrae il testo pagina per pagina da un PDF.

    Restituisce:
    [
      (1, "testo pagina 1"),
      (2, "testo pagina 2"),
      ...
    ]
    """
    reader = PdfReader(str(pdf_path))
    out: list[tuple[int, str]] = []

    for idx, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""

        text = _normalize_text(text)

        if text:
            out.append((idx, text))

    return out


def _chunk_text(text: str, *, chunk_chars: int, overlap_chars: int) -> list[str]:
    """
    Chunking semplice a caratteri con overlap.

    Per ora è una scelta pragmatica:
    - robusta
    - prevedibile
    - facile da capire
    - sufficiente come base
    """
    text = _normalize_text(text)

    if not text:
        return []

    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be > 0")

    if overlap_chars < 0:
        raise ValueError("overlap_chars must be >= 0")

    if overlap_chars >= chunk_chars:
        overlap_chars = max(0, chunk_chars // 4)

    out: list[str] = []
    start = 0
    step = max(1, chunk_chars - overlap_chars)

    while start < len(text):
        chunk = text[start : start + chunk_chars].strip()
        if chunk:
            out.append(chunk)

        if start + chunk_chars >= len(text):
            break

        start += step

    return out


def _doc_id_for_file(file_path: Path) -> str:
    """
    Produce un doc_id stabile per il file sorgente.

    Manteniamo un doc_id leggibile ma sufficientemente stabile.
    """
    name = file_path.name
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:10]
    return f"{name}__{digest}"


def _chunk_id(kb_name: str, doc_id: str, chunk_index: int) -> str:
    """
    Produce un ID chunk globale e univoco.
    """
    return f"{kb_name}::{doc_id}::{chunk_index:06d}"


def _build_chunks_for_pdf(
    *,
    kb_name: str,
    pdf_path: Path,
    chunk_chars: int,
    overlap_chars: int,
) -> list[DocumentChunk]:
    """
    Costruisce i chunk di un singolo PDF.
    """
    doc_id = _doc_id_for_file(pdf_path)
    pages = _page_texts_from_pdf(pdf_path)

    chunks: list[DocumentChunk] = []
    chunk_index = 0

    for page_number, page_text in pages:
        page_chunks = _chunk_text(
            page_text,
            chunk_chars=chunk_chars,
            overlap_chars=overlap_chars,
        )

        for piece in page_chunks:
            chunks.append(
                DocumentChunk(
                    chunk_id=_chunk_id(kb_name, doc_id, chunk_index),
                    kb_name=kb_name,
                    doc_id=doc_id,
                    source_file=pdf_path.name,
                    text=piece,
                    chunk_index=chunk_index,
                    page_start=page_number,
                    page_end=page_number,
                    section="",
                    mime_type="application/pdf",
                    metadata={},
                )
            )
            chunk_index += 1

    return chunks


def ingest_kb(workspace: Path, kb_name: str) -> IngestResult:
    """
    Ricostruisce interamente una KB.

    Flusso:
    1. pulizia store locale
    2. delete Qdrant per kb_name
    3. lettura sorgenti PDF
    4. chunking
    5. salvataggio chunk JSON
    6. build indice BM25
    7. embeddings + upsert Qdrant
    8. scrittura manifest
    """
    workspace = Path(workspace).resolve()
    paths = clear_store(workspace, kb_name)

    # Config retrieval.
    chunk_chars = int(cfg_get("retrieval.chunk_chars", 900))
    chunk_overlap = int(cfg_get("retrieval.chunk_overlap", 120))
    bm25_k1 = float(cfg_get("retrieval.bm25_k1", 1.5))
    bm25_b = float(cfg_get("retrieval.bm25_b", 0.75))
    embed_batch_size = int(cfg_get("embeddings.batch_size", 16))

    # Elenco sorgenti.
    source_files = sorted([
        p for p in paths.source_dir.rglob("*")
        if p.is_file() and p.suffix.lower() == ".pdf"
    ])

    # Pulizia Qdrant della KB PRIMA del nuovo ingest.
    docs_store = DocsQdrantStore()
    docs_store.delete_kb(paths.name)

    # Chunking di tutti i PDF.
    all_chunks: list[DocumentChunk] = []

    for src in source_files:
        all_chunks.extend(
            _build_chunks_for_pdf(
                kb_name=paths.name,
                pdf_path=src,
                chunk_chars=chunk_chars,
                overlap_chars=chunk_overlap,
            )
        )

    # Salvataggio chunk JSON.
    for chunk in all_chunks:
        write_chunk(paths, chunk)

    # Costruzione indice lessicale BM25.
    bm25_index = BM25Index.build(
        all_chunks,
        k1=bm25_k1,
        b=bm25_b,
    )
    bm25_path = paths.index_dir / "bm25.json"
    bm25_index.save(bm25_path)

    # Indicizzazione vettoriale Qdrant.
    indexed_points = 0

    if all_chunks:
        embedder = LocalEmbedder()
        texts = [chunk.text for chunk in all_chunks]
        vectors = embedder.embed(texts)

        if len(vectors) != len(all_chunks):
            raise RuntimeError(
                f"embedding count mismatch: expected {len(all_chunks)}, got {len(vectors)}"
            )

        docs_store.ensure_collection(vector_size=len(vectors[0]))

        points: list[dict] = []

        for chunk, vector in zip(all_chunks, vectors):
            points.append(
                {
                    "id": chunk.chunk_id,
                    "vector": vector,
                    "payload": chunk.to_payload(),
                }
            )

        indexed_points = docs_store.upsert(points)

    # Marker semplici, utili in development.
    (paths.index_dir / "collection.txt").write_text(
        f"{docs_store.collection}\n",
        encoding="utf-8",
    )
    (paths.index_dir / "count.txt").write_text(
        f"{len(all_chunks)}\n",
        encoding="utf-8",
    )
    (paths.index_dir / "embed_batch_size.txt").write_text(
        f"{embed_batch_size}\n",
        encoding="utf-8",
    )

    # Manifest finale della KB.
    manifest = {
        "kb_name": paths.name,
        "source_files": len(source_files),
        "chunk_files": len(all_chunks),
        "indexed_points": indexed_points,
        "layout": {
            "root": str(paths.root),
            "source_dir": str(paths.source_dir),
            "store_dir": str(paths.store_dir),
            "chunks_dir": str(paths.chunks_dir),
            "index_dir": str(paths.index_dir),
            "manifest_path": str(paths.manifest_path),
        },
        "retrieval": {
            "chunk_chars": chunk_chars,
            "chunk_overlap": chunk_overlap,
            "bm25_k1": bm25_k1,
            "bm25_b": bm25_b,
        },
        "embeddings": {
            "provider": "ollama",
            "model": str(cfg_get("embeddings.model", cfg_get("embedding_model", "nomic-embed-text"))),
            "base_url": str(cfg_get("ollama.base_url", "http://localhost:11434")),
        },
        "qdrant": {
            "path": str(cfg_get("qdrant.path", ".picobot/qdrant")),
            "collection": str(cfg_get("qdrant.docs_collection", "docs_index")),
            "mode": "embedded",
        },
    }
    write_manifest(paths, manifest)

    return IngestResult(
        kb_name=paths.name,
        source_files=len(source_files),
        chunk_files=len(all_chunks),
        indexed_points=indexed_points,
        manifest_path=str(paths.manifest_path),
    )


def ingest_dir(*, source_dir: Path, store_dir: Path) -> None:
    """
    Wrapper legacy/compatibility.

    Dal layout corrente:
    - source_dir = docs/<kb>/source
    - store_dir  = docs/<kb>/kb

    Risaliamo al workspace e ricaviamo kb_name.
    """
    source_dir = Path(source_dir).resolve()
    store_dir = Path(store_dir).resolve()

    kb_root = store_dir.parent
    docs_root = kb_root.parent
    workspace = docs_root.parent
    kb_name = kb_root.name

    # Ci assicuriamo che le directory esistano.
    ensure_kb_dirs(workspace, kb_name)

    # Eseguiamo ingest completo.
    ingest_kb(workspace, kb_name)
