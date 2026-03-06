from __future__ import annotations

# Questo file incapsula completamente la generazione embeddings locali.
#
# Direzione scelta:
# - provider unico: Ollama locale
# - modello embedding: configurabile, default "nomic-embed-text"
# - nessuna dipendenza SaaS
#
# Note importanti:
# - usiamo batching quando possibile
# - facciamo trim dei testi troppo lunghi
# - restituiamo sempre list[list[float]]
# - teniamo questo componente isolato così router e KB possono riusarlo

import json
import urllib.request
from typing import Any

from picobot.runtime_config import cfg_get


class LocalEmbedder:
    """
    Embedder locale basato su Ollama /api/embed.
    """

    def __init__(self) -> None:
        # Base URL di Ollama locale.
        self.base_url = str(
            cfg_get("ollama.base_url", cfg_get("vector.base_url", "http://localhost:11434"))
        ).rstrip("/")

        # Modello embedding scelto.
        # Usiamo la config embeddings.model come fonte principale.
        self.model = str(
            cfg_get(
                "embeddings.model",
                cfg_get("embedding_model", "nomic-embed-text"),
            )
        ).strip() or "nomic-embed-text"

        # Timeout HTTP per chiamate a Ollama.
        self.timeout_s = float(
            cfg_get("ollama.timeout_s", cfg_get("vector.timeout_s", 120.0))
        )

        # Batching locale.
        self.batch_size = int(cfg_get("embeddings.batch_size", 16))

        # Taglio conservativo di sicurezza.
        self.max_chars = int(cfg_get("retrieval.max_embed_chars", 4000))

    def _normalize_text(self, text: str) -> str:
        """
        Normalizza un testo prima dell'embedding.
        """
        out = (text or "").strip()

        # Evitiamo input vuoti per non mandare rumore a Ollama.
        if not out:
            return " "

        # Tagliamo testi troppo lunghi.
        if len(out) > self.max_chars:
            out = out[: self.max_chars]

        return out

    def _post_embed(self, inputs: list[str]) -> list[list[float]]:
        """
        Fa una singola chiamata HTTP a Ollama /api/embed.

        Supporta una lista di input per batching.
        """
        payload = {
            "model": self.model,
            "input": inputs,
        }

        raw = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url=f"{self.base_url}/api/embed",
            data=raw,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            body = resp.read().decode("utf-8", errors="replace")

        data: Any = json.loads(body)

        embeddings = data.get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            raise RuntimeError("Ollama /api/embed returned no embeddings")

        out: list[list[float]] = []

        for vector in embeddings:
            if not isinstance(vector, list) or not vector:
                raise RuntimeError("Invalid embedding vector returned by Ollama")
            out.append([float(x) for x in vector])

        return out

    def embed(self, texts: list[str]) -> list[list[float]]:
        """
        Genera embedding per una lista di testi.

        Manteniamo:
        - ordine di input preservato
        - batching trasparente
        - errore chiaro se il numero di embedding non coincide
        """
        if not texts:
            return []

        normalized = [self._normalize_text(t) for t in texts]
        out: list[list[float]] = []

        batch_size = max(1, int(self.batch_size))

        for i in range(0, len(normalized), batch_size):
            batch = normalized[i : i + batch_size]
            vectors = self._post_embed(batch)

            if len(vectors) != len(batch):
                raise RuntimeError(
                    f"Embedding batch size mismatch: expected {len(batch)}, got {len(vectors)}"
                )

            out.extend(vectors)

        return out
