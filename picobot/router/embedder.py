from __future__ import annotations

import json
import urllib.request

from picobot.runtime_config import cfg_get


class LocalEmbedder:
    def __init__(self) -> None:
        self.provider = str(cfg_get("vector.provider", "ollama"))
        self.base_url = str(cfg_get("vector.base_url", "http://localhost:11434")).rstrip("/")
        self.model = str(cfg_get("vector.embed_model", "qwen3-embedding:0.6b"))
        self.timeout_s = float(cfg_get("vector.timeout_s", 60))

        if self.provider != "ollama":
            raise RuntimeError(f"Unsupported vector provider: {self.provider}")

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            payload = json.dumps({
                "model": self.model,
                "input": text,
            }).encode("utf-8")

            req = urllib.request.Request(
                f"{self.base_url}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))

            emb = data.get("embeddings") or []
            if not emb or not isinstance(emb, list):
                raise RuntimeError("Ollama /api/embed returned no embeddings")
            vec = emb[0]
            if not isinstance(vec, list) or not vec:
                raise RuntimeError("Invalid embedding vector from Ollama")
            out.append([float(x) for x in vec])
        return out
