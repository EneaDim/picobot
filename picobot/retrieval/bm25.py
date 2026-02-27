from __future__ import annotations

import math
import re
from dataclasses import dataclass


_WORD = re.compile(r"[a-zA-Z0-9_]+")


def tokenize(text: str) -> list[str]:
    return [m.group(0).lower() for m in _WORD.finditer(text or "")]


@dataclass
class BM25Index:
    docs: list[str]
    doc_ids: list[str]
    k1: float = 1.5
    b: float = 0.75

    def __post_init__(self) -> None:
        self.tok_docs = [tokenize(d) for d in self.docs]
        self.df: dict[str, int] = {}
        self.tf: list[dict[str, int]] = []
        self.doc_len: list[int] = [len(t) for t in self.tok_docs]
        for toks in self.tok_docs:
            counts: dict[str, int] = {}
            for t in toks:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in set(toks):
                self.df[t] = self.df.get(t, 0) + 1
        self.avgdl = sum(self.doc_len) / max(1, len(self.doc_len))

    def _idf(self, term: str) -> float:
        n = len(self.docs)
        df = self.df.get(term, 0)
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str) -> list[tuple[str, float]]:
        q = tokenize(query)
        scores = [0.0 for _ in self.docs]
        for term in q:
            idf = self._idf(term)
            for i, tf in enumerate(self.tf):
                f = tf.get(term, 0)
                if f == 0:
                    continue
                dl = self.doc_len[i]
                denom = f + self.k1 * (1 - self.b + self.b * (dl / self.avgdl))
                scores[i] += idf * (f * (self.k1 + 1) / denom)
        return [(self.doc_ids[i], scores[i]) for i in range(len(scores))]
