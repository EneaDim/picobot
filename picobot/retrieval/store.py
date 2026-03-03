from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict


_WORD = re.compile(r"[a-zA-Z0-9_]+")


def _tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text or "")]


def _safe_slug(name: str) -> str:
    s = (name or "doc").strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "doc"


@dataclass
class BM25Index:
    """
    Minimal BM25 index for chunk_id -> text.
    Stored as index.json under kb_root.
    """
    k1: float = 1.2
    b: float = 0.75
    docs: Dict[str, Dict[str, int]] = None  # cid -> termfreq
    doc_len: Dict[str, int] = None          # cid -> length
    df: Dict[str, int] = None               # term -> docfreq
    n_docs: int = 0
    avg_dl: float = 0.0

    def __post_init__(self):
        self.docs = self.docs or {}
        self.doc_len = self.doc_len or {}
        self.df = self.df or {}
        self.n_docs = int(self.n_docs or 0)
        self.avg_dl = float(self.avg_dl or 0.0)

    @classmethod
    def build(cls, chunk_texts: list[tuple[str, str]], k1: float = 1.2, b: float = 0.75) -> "BM25Index":
        docs: Dict[str, Dict[str, int]] = {}
        doc_len: Dict[str, int] = {}
        df: Dict[str, int] = {}

        for cid, text in chunk_texts:
            terms = _tokenize(text)
            if not terms:
                continue
            tf: Dict[str, int] = {}
            for t in terms:
                tf[t] = tf.get(t, 0) + 1
            docs[cid] = tf
            doc_len[cid] = len(terms)
            for t in tf.keys():
                df[t] = df.get(t, 0) + 1

        n_docs = len(docs)
        avg_dl = (sum(doc_len.values()) / n_docs) if n_docs else 0.0
        return cls(k1=k1, b=b, docs=docs, doc_len=doc_len, df=df, n_docs=n_docs, avg_dl=avg_dl)

    def score(self, query: str) -> list[tuple[str, float]]:
        q_terms = _tokenize(query)
        if not q_terms or not self.n_docs:
            return []
        scores: Dict[str, float] = {}
        for term in q_terms:
            df = self.df.get(term, 0)
            if df == 0:
                continue
            # BM25 idf with +1 smoothing
            idf = math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for cid, tf in self.docs.items():
                f = tf.get(term, 0)
                if f == 0:
                    continue
                dl = self.doc_len.get(cid, 0) or 0
                denom = f + self.k1 * (1 - self.b + self.b * (dl / (self.avg_dl or 1.0)))
                score = idf * (f * (self.k1 + 1) / (denom or 1.0))
                scores[cid] = scores.get(cid, 0.0) + score

        return list(scores.items())

    def to_dict(self) -> dict:
        return {
            "k1": self.k1,
            "b": self.b,
            "docs": self.docs,
            "doc_len": self.doc_len,
            "df": self.df,
            "n_docs": self.n_docs,
            "avg_dl": self.avg_dl,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "BM25Index":
        return cls(
            k1=float(d.get("k1", 1.2)),
            b=float(d.get("b", 0.75)),
            docs=d.get("docs", {}) or {},
            doc_len=d.get("doc_len", {}) or {},
            df=d.get("df", {}) or {},
            n_docs=int(d.get("n_docs", 0) or 0),
            avg_dl=float(d.get("avg_dl", 0.0) or 0.0),
        )


def _load_manifest(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"docs": {}}


def _save_manifest(path: Path, m: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(m, indent=2), encoding="utf-8")


def add_document_chunks(kb_root: Path, doc_name: str, chunks: list[str]) -> dict:
    kb_root.mkdir(parents=True, exist_ok=True)
    chunk_dir = kb_root / "chunks"
    chunk_dir.mkdir(parents=True, exist_ok=True)

    manifest_path = kb_root / "manifest.json"
    m = _load_manifest(manifest_path)

    doc_id = _safe_slug(doc_name)
    ids: list[str] = []
    for idx, ch in enumerate(chunks):
        cid = f"{doc_id}-{idx:04d}"
        (chunk_dir / f"{cid}.md").write_text((ch or "").strip() + "\n", encoding="utf-8")
        ids.append(cid)

    m["docs"][doc_id] = {"name": doc_name, "chunks": ids}
    _save_manifest(manifest_path, m)
    return {"doc_id": doc_id, "chunks": len(ids)}


def iter_all_chunks(kb_root: Path) -> list[tuple[str, str]]:
    chunk_dir = kb_root / "chunks"
    if not chunk_dir.exists():
        return []
    out: list[tuple[str, str]] = []
    for fp in sorted(chunk_dir.glob("*.md")):
        out.append((fp.stem, fp.read_text(encoding="utf-8", errors="ignore")))
    return out


class KBStore:
    """
    Store rooted at workspace/kb.
    Index is stored per KB name:
      workspace/kb/<kb_name>/index.json
      workspace/kb/<kb_name>/chunks/*.md
    BUT for backward compatibility with existing code/tests,
    KBStore(root) uses:
      root/index.json and root/chunks if root is already a kb_name folder,
      otherwise root/default.
    """
    def __init__(self, root: Path, kb_name: str | None = None) -> None:
        self.root = Path(root)
        self.kb_name = kb_name
        self.kb_root = self._resolve_kb_root()

    def _resolve_kb_root(self) -> Path:
        # If root already looks like a KB folder (has chunks/ or manifest.json), keep it.
        if (self.root / "chunks").exists() or (self.root / "manifest.json").exists():
            return self.root
        # Otherwise treat root as workspace/kb and pick kb_name/default
        name = self.kb_name or "default"
        return self.root / name

    @property
    def index_path(self) -> Path:
        return self.kb_root / "index.json"

    @property
    def legacy_index_path(self) -> Path:
        return self.kb_root / "bm25_index.json"

    @property
    def chunk_dir(self) -> Path:
        return self.kb_root / "chunks"

    def read_chunk(self, cid: str) -> str:
        fp = self.chunk_dir / f"{cid}.md"
        if not fp.exists():
            return ""
        return fp.read_text(encoding="utf-8", errors="ignore")

    def load_index(self) -> BM25Index | None:
        # new format
        try:
            if self.index_path.exists():
                d = json.loads(self.index_path.read_text(encoding="utf-8"))
                return BM25Index.from_dict(d)
        except Exception:
            return None

        # legacy format used by older tests/projects
        try:
            if self.legacy_index_path.exists():
                d = json.loads(self.legacy_index_path.read_text(encoding="utf-8"))
                docs = d.get("docs") or []
                doc_ids = d.get("doc_ids") or []
                k1 = float(d.get("k1", 1.2))
                b = float(d.get("b", 0.75))
                pairs = []
                for cid, text in zip(doc_ids, docs):
                    pairs.append((str(cid), str(text)))
                return BM25Index.build(pairs, k1=k1, b=b)
        except Exception:
            return None

        return None

    def rebuild_index(self, k1: float = 1.2, b: float = 0.75) -> BM25Index:
        chunks = iter_all_chunks(self.kb_root)
        idx = BM25Index.build(chunks, k1=k1, b=b)
        self.kb_root.mkdir(parents=True, exist_ok=True)
        self.index_path.write_text(json.dumps(idx.to_dict(), indent=2), encoding="utf-8")
        return idx

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Return top-k chunks with score and text (minimal helper for tools/orchestrator)."""
        idx = self.load_index()
        if not idx:
            return []
        scored = sorted(idx.score(query), key=lambda x: x[1], reverse=True)
        top = [(cid, s) for cid, s in scored if s > 0][: max(1, int(top_k))]
        out: list[dict] = []
        for cid, s in top:
            out.append({"chunk_id": cid, "score": float(s), "text": self.read_chunk(cid)})
        return out
