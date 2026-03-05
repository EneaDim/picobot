from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from picobot.agent.prompts import detect_language

Workflow = Literal[
    "chat",
    "kb_query",
    "kb_ingest_pdf",
    "youtube_summarizer",
    "news_digest",
    "tool",
    "podcast",
    "sandbox_python",
    "sandbox_file",
    "sandbox_web",
]

@dataclass(frozen=True)
class RouteDecision:
    workflow: Workflow
    reason: str
    tool_name: str = ""
    args: dict[str, Any] | None = None
    score: float = 0.0


_WORD_RX = re.compile(r"[a-zA-Z0-9_àèéìòù]+", re.IGNORECASE)
_EXPLICIT_TOOL_RX = re.compile(r"^\s*tool\s+([a-zA-Z0-9_\-]+)\s+(\{.*\})\s*$", re.S)
_URL_RX = re.compile(r"(https?://\S+)")
_YT_RX = re.compile(r"(https?://)?(www\.)?(youtube\.com|youtu\.be)/", re.IGNORECASE)

_INGEST_PDF_RX = re.compile(r"^\s*(?:/kb\s+ingest|ingest\s+pdf|index\s+pdf)\b", re.IGNORECASE)
_NEWS_RX = re.compile(r"^\s*(?:/news|news:)\b", re.IGNORECASE)


def _tokens(text: str) -> list[str]:
    t = (text or "").lower()
    return _WORD_RX.findall(t)


# ---------------- BM25 ----------------
class BM25:
    def __init__(self, corpus: list[list[str]], k1: float = 1.5, b: float = 0.75) -> None:
        self.corpus = corpus
        self.k1 = k1
        self.b = b
        self.N = len(corpus)
        self.avgdl = (sum(len(d) for d in corpus) / self.N) if self.N else 0.0

        df: dict[str, int] = {}
        for doc in corpus:
            for w in set(doc):
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log(1 + (self.N - n + 0.5) / (n + 0.5)) for w, n in df.items()}

        self.tf: list[dict[str, int]] = []
        for doc in corpus:
            d: dict[str, int] = {}
            for w in doc:
                d[w] = d.get(w, 0) + 1
            self.tf.append(d)

    def scores(self, query: list[str]) -> list[float]:
        if not self.corpus:
            return []
        out = [0.0 for _ in range(self.N)]
        for i, doc in enumerate(self.corpus):
            dl = len(doc) or 1
            denom_const = self.k1 * (1 - self.b + self.b * (dl / (self.avgdl or 1)))
            tf = self.tf[i]
            s = 0.0
            for w in query:
                if w not in tf:
                    continue
                f = tf[w]
                s += self.idf.get(w, 0.0) * (f * (self.k1 + 1)) / (f + denom_const)
            out[i] = s
        return out


# --------------- TF-IDF cosine (vector search) ---------------
class TFIDF:
    def __init__(self, corpus: list[list[str]]) -> None:
        self.corpus = corpus
        self.N = len(corpus)
        df: dict[str, int] = {}
        for doc in corpus:
            for w in set(doc):
                df[w] = df.get(w, 0) + 1
        self.idf = {w: math.log((self.N + 1) / (n + 1)) + 1.0 for w, n in df.items()}

        self.doc_vecs: list[dict[str, float]] = []
        self.doc_norms: list[float] = []
        for doc in corpus:
            v = self._vec(doc)
            self.doc_vecs.append(v)
            self.doc_norms.append(self._norm(v))

    def _vec(self, toks: list[str]) -> dict[str, float]:
        tf: dict[str, int] = {}
        for w in toks:
            tf[w] = tf.get(w, 0) + 1
        return {w: float(c) * self.idf.get(w, 0.0) for w, c in tf.items()}

    def _norm(self, v: dict[str, float]) -> float:
        return math.sqrt(sum(x * x for x in v.values())) or 1.0

    def cosine_scores(self, query: list[str]) -> list[float]:
        if not self.corpus:
            return []
        qv = self._vec(query)
        qn = self._norm(qv)
        out: list[float] = []
        for dv, dn in zip(self.doc_vecs, self.doc_norms):
            dot = 0.0
            if len(qv) < len(dv):
                for w, qw in qv.items():
                    dot += qw * dv.get(w, 0.0)
            else:
                for w, dw in dv.items():
                    dot += dw * qv.get(w, 0.0)
            out.append(dot / (qn * dn))
        return out


@dataclass(frozen=True)
class _RouteDoc:
    workflow: Workflow
    tool_name: str
    text: str
    source: str


def _parse_explicit_tool(user_text: str) -> tuple[str, dict[str, Any]] | None:
    m = _EXPLICIT_TOOL_RX.match(user_text or "")
    if not m:
        return None
    name = m.group(1).strip()
    raw = m.group(2).strip()
    try:
        args = json.loads(raw)
    except Exception:
        return None
    return (name, args) if isinstance(args, dict) else None


def _load_state(state_file: Path) -> dict:
    try:
        if state_file.exists():
            d = json.loads(state_file.read_text(encoding="utf-8"))
            return d if isinstance(d, dict) else {}
    except Exception:
        pass
    return {}


def _save_state(state_file: Path, state: dict) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _is_followup(text: str) -> bool:
    t = (text or "").strip()
    if not t or len(t) > 220:
        return False
    if t.startswith("/") or t.lower().startswith("tool ") or t.lower().startswith("news:"):
        return False
    if _YT_RX.search(t):
        return False
    return True


def _routing_docs_dir() -> Path:
    # picobot/routing_kb/routes
    return Path(__file__).resolve().parents[1] / "routing_kb" / "routes"


_FILENAME_TO_WORKFLOW: dict[str, tuple[Workflow, str]] = {
    "chat.md": ("chat", ""),
    "kb_query.md": ("kb_query", ""),
    "kb_ingest_pdf.md": ("kb_ingest_pdf", "kb_ingest_pdf"),
    "youtube_summarizer.md": ("youtube_summarizer", ""),
    "news_digest.md": ("news_digest", ""),
    "sandbox_python.md": ("tool", "sandbox_python"),
    "sandbox_file.md": ("tool", "sandbox_file"),
    "sandbox_web.md": ("tool", "sandbox_web"),
    "podcast.md": ("podcast", ""),
}


def load_route_docs() -> list[_RouteDoc]:
    d = _routing_docs_dir()
    docs: list[_RouteDoc] = []
    if not d.exists():
        return docs

    for p in sorted(d.glob("*.md")):
        key = p.name
        if key not in _FILENAME_TO_WORKFLOW:
            continue
        wf, tool = _FILENAME_TO_WORKFLOW[key]
        text = p.read_text(encoding="utf-8", errors="ignore")
        docs.append(_RouteDoc(workflow=wf, tool_name=tool, text=text, source=str(p)))
    return docs


class RetrievalRouter:
    """
    Router ibrido:
      1) hard rules (tool directive, ingest, youtube url, news syntax)
      2) BM25 + TF-IDF cosine su routing_kb/routes/*.md (IT/EN, scenari)
      3) stickiness su kb_query
    """

    def __init__(self) -> None:
        self.docs = load_route_docs()
        self.doc_tokens = [_tokens(d.text) for d in self.docs]
        self.bm25 = BM25(self.doc_tokens)
        self.tfidf = TFIDF(self.doc_tokens)

    def route(self, user_text: str, state_file: Path, default_language: str = "it") -> RouteDecision:
        t = (user_text or "").strip()
        st = _load_state(state_file)
        last = (st.get("last_workflow") or "chat").strip()

        # 0) explicit tool
        exp = _parse_explicit_tool(t)
        if exp:
            tool_name, args = exp
            st["last_workflow"] = "tool"
            st["last_tool"] = tool_name
            _save_state(state_file, st)
            return RouteDecision("tool", "explicit tool", tool_name=tool_name, args=args, score=1.0)

        # 1) ingest pdf
        if _INGEST_PDF_RX.search(t):
            st["last_workflow"] = "kb_ingest_pdf"
            _save_state(state_file, st)
            return RouteDecision("kb_ingest_pdf", "ingest pdf", tool_name="kb_ingest_pdf", args={"text": t}, score=1.0)

        # 2) youtube url
        if _YT_RX.search(t):
            st["last_workflow"] = "youtube_summarizer"
            _save_state(state_file, st)
            return RouteDecision("youtube_summarizer", "youtube url", score=1.0)

        # 3) explicit news syntax
        if _NEWS_RX.search(t):
            st["last_workflow"] = "news_digest"
            _save_state(state_file, st)
            return RouteDecision("news_digest", "news command", score=1.0)

        # 4) KB followup stickiness
        if last == "kb_query" and _is_followup(t):
            st["last_workflow"] = "kb_query"
            _save_state(state_file, st)
            return RouteDecision("kb_query", "kb followup", score=0.95)

        # 5) retrieval classification
        q = _tokens(t)
        if not q or not self.docs:
            st["last_workflow"] = "chat"
            _save_state(state_file, st)
            return RouteDecision("chat", "empty or no docs", score=0.0)

        bm = self.bm25.scores(q)
        vc = self.tfidf.cosine_scores(q)

        bm_max = max(bm) if bm else 0.0
        bm_n = [(x / bm_max) if bm_max > 0 else 0.0 for x in bm]
        comb = [0.55 * b + 0.45 * v for b, v in zip(bm_n, vc)]

        best_i = max(range(len(comb)), key=lambda i: comb[i])
        best = self.docs[best_i]
        score = float(comb[best_i])

        # threshold: avoid silly misroutes
        if score < 0.22:
            st["last_workflow"] = "chat"
            _save_state(state_file, st)
            return RouteDecision("chat", "low confidence", score=score)

        st["last_workflow"] = best.workflow
        _save_state(state_file, st)

        if best.workflow == "tool":
            return RouteDecision("tool", f"retrieval match ({best.source})", tool_name=best.tool_name, args={}, score=score)

        return RouteDecision(best.workflow, f"retrieval match ({best.source})", tool_name=best.tool_name, args={}, score=score)



def debug_scores(user_text: str) -> dict:
    """
    Returns per-route raw scores to inspect BM25 vs vector behavior.
    """
    rr = _router
    q = _tokens((user_text or "").strip())
    if not q or not rr.docs:
        return {"ok": False, "error": "empty query or no route docs"}

    bm = rr.bm25.scores(q)
    vc = rr.tfidf.cosine_scores(q)

    bm_max = max(bm) if bm else 0.0
    bm_n = [(x / bm_max) if bm_max > 0 else 0.0 for x in bm]
    comb = [0.55 * b + 0.45 * v for b, v in zip(bm_n, vc)]

    rows = []
    for i, d in enumerate(rr.docs):
        rows.append({
            "workflow": d.workflow,
            "tool": d.tool_name,
            "source": d.source,
            "bm25": round(float(bm_n[i]), 4),
            "vec": round(float(vc[i]), 4),
            "score": round(float(comb[i]), 4),
        })

    rows.sort(key=lambda r: r["score"], reverse=True)
    return {"ok": True, "top": rows[:5], "all_count": len(rows)}

_router = RetrievalRouter()

def route_json_one_line(user_text: str, state_file: Path, default_language: str = "it") -> str:
    lang = detect_language((user_text or "").strip(), default=default_language)
    d = _router.route(user_text, state_file, default_language=default_language)

    if d.workflow == "tool":
        args = dict(d.args or {})
        args.setdefault("lang", lang)
        return json.dumps({"route": "tool", "tool_name": d.tool_name, "args": args, "score": d.score, "reason": d.reason}, separators=(",", ":"))

    return json.dumps({"route": "workflow", "workflow": d.workflow, "lang": lang, "score": d.score, "reason": d.reason}, separators=(",", ":"))
