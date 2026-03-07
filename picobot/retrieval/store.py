from __future__ import annotations

# Questo file gestisce SOLO il layout filesystem della KB.
# Non deve sapere nulla di embeddings o Qdrant.
# Non deve sapere nulla di routing.
#
# Responsabilità:
# - costruire i path canonici della KB
# - creare directory
# - copiare file sorgente
# - pulire lo store locale
# - leggere/scrivere manifest
# - enumerare chunk JSON locali
import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from picobot.retrieval.schemas import DocumentChunk


@dataclass(frozen=True)
class KBPaths:
    """
    Layout canonico di una KB locale.
    """
    name: str
    root: Path
    source_dir: Path
    store_dir: Path
    chunks_dir: Path
    index_dir: Path
    manifest_path: Path


# Regex conservativa per rendere il nome KB sicuro sul filesystem.
_SAFE_NAME_RX = re.compile(r"[^a-zA-Z0-9._-]+")

# Regex conservativa per nomi file chunk.
_SAFE_FILE_RX = re.compile(r"[^a-zA-Z0-9._-]+")


def sanitize_kb_name(name: str) -> str:
    """
    Normalizza il nome KB in qualcosa di stabile e sicuro.
    """
    raw = (name or "").strip()
    raw = Path(raw).stem
    raw = _SAFE_NAME_RX.sub("-", raw).strip("-.")
    return raw or "default"


def _safe_filename(value: str) -> str:
    """
    Produce un nome file sicuro da usare sul filesystem.
    """
    out = _SAFE_FILE_RX.sub("_", (value or "").strip())
    out = out.strip("._")
    return out or "item"


def kb_paths(workspace: Path, kb_name: str) -> KBPaths:
    """
    Restituisce il layout completo di una KB.
    """
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
    """
    Crea le directory minime della KB se non esistono.
    """
    paths = kb_paths(workspace, kb_name)

    paths.source_dir.mkdir(parents=True, exist_ok=True)
    paths.chunks_dir.mkdir(parents=True, exist_ok=True)
    paths.index_dir.mkdir(parents=True, exist_ok=True)

    return paths


def copy_source_file(workspace: Path, kb_name: str, src_file: Path) -> Path:
    """
    Copia un file sorgente dentro docs/<kb>/source/.

    Manteniamo il nome originale del file.
    """
    paths = ensure_kb_dirs(workspace, kb_name)

    src_file = Path(src_file).expanduser().resolve()
    dst = paths.source_dir / src_file.name

    shutil.copy2(src_file, dst)
    return dst


def clear_store(workspace: Path, kb_name: str) -> KBPaths:
    """
    Pulisce SOLO lo store locale della KB.

    Importante:
    - qui NON tocchiamo Qdrant
    - la pulizia Qdrant è responsabilità del DocsQdrantStore
    - così separiamo chiaramente filesystem e vector store
    """
    paths = ensure_kb_dirs(workspace, kb_name)

    if paths.store_dir.exists():
        for child in paths.store_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)

    paths.chunks_dir.mkdir(parents=True, exist_ok=True)
    paths.index_dir.mkdir(parents=True, exist_ok=True)

    return paths


def write_manifest(paths: KBPaths, payload: dict) -> None:
    """
    Scrive il manifest JSON della KB.
    """
    paths.manifest_path.parent.mkdir(parents=True, exist_ok=True)
    paths.manifest_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def read_manifest(workspace: Path, kb_name: str) -> dict:
    """
    Legge il manifest della KB, se presente.
    """
    paths = kb_paths(workspace, kb_name)

    if not paths.manifest_path.exists():
        return {}

    try:
        data = json.loads(paths.manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return {}

    return data if isinstance(data, dict) else {}


def chunk_json_path(paths: KBPaths, chunk: DocumentChunk) -> Path:
    """
    Costruisce il path JSON di un chunk persistito su disco.

    Non usiamo direttamente chunk_id come nome file perché potrebbe
    contenere caratteri scomodi o troppo verbosi.
    """
    stem = f"{_safe_filename(chunk.doc_id)}__{chunk.chunk_index:06d}"
    return paths.chunks_dir / f"{stem}.json"


def write_chunk(paths: KBPaths, chunk: DocumentChunk) -> Path:
    """
    Salva un chunk come JSON nel filesystem locale.
    """
    out = chunk_json_path(paths, chunk)
    out.write_text(
        json.dumps(chunk.to_payload(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return out


def load_chunk_file(path: Path) -> DocumentChunk:
    """
    Legge un chunk JSON da disco.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"invalid chunk file: {path}")
    return DocumentChunk.from_payload(data)


def load_all_chunks(workspace: Path, kb_name: str) -> list[DocumentChunk]:
    """
    Carica tutti i chunk locali della KB.
    """
    paths = kb_paths(workspace, kb_name)

    if not paths.chunks_dir.exists():
        return []

    out: list[DocumentChunk] = []

    for file_path in sorted(paths.chunks_dir.glob("*.json")):
        try:
            out.append(load_chunk_file(file_path))
        except Exception:
            # In development preferiamo ignorare il chunk corrotto
            # e continuare a caricare il resto.
            continue

    return out


def count_source_files(workspace: Path, kb_name: str) -> int:
    """
    Conta i file presenti nella source dir della KB.
    """
    paths = kb_paths(workspace, kb_name)

    if not paths.source_dir.exists():
        return 0

    return len([p for p in paths.source_dir.rglob("*") if p.is_file()])


def count_store_files(workspace: Path, kb_name: str) -> int:
    """
    Conta i file presenti nello store della KB.
    """
    paths = kb_paths(workspace, kb_name)

    if not paths.store_dir.exists():
        return 0

    return len([p for p in paths.store_dir.rglob("*") if p.is_file()])


def list_kbs(workspace: Path) -> list[str]:
    """
    Elenca le KB presenti sotto docs/.
    """
    docs_root = (workspace / "docs").resolve()
    docs_root.mkdir(parents=True, exist_ok=True)

    return sorted([p.name for p in docs_root.iterdir() if p.is_dir()])
