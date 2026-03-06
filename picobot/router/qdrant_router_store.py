from __future__ import annotations

import uuid
from typing import Any

from qdrant_client import QdrantClient, models

from picobot.runtime_config import cfg_get


def stable_uuid(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


class RouterQdrantStore:
    def __init__(self) -> None:
        self.path = str(cfg_get("qdrant.path", ".picobot/qdrant"))
        self.collection = str(cfg_get("qdrant.router_collection", "router_index"))
        self.client = QdrantClient(path=self.path)

    def ensure_collection(self, vector_size: int) -> None:
        exists = False
        try:
            exists = self.client.collection_exists(self.collection)
        except Exception:
            exists = False

        if not exists:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=int(vector_size),
                    distance=models.Distance.COSINE,
                ),
            )

    def count(self) -> int:
        try:
            return int(self.client.count(collection_name=self.collection, exact=True).count)
        except Exception:
            return 0

    def upsert(self, points: list[dict[str, Any]]) -> None:
        qpoints: list[models.PointStruct] = []
        for p in points:
            qpoints.append(
                models.PointStruct(
                    id=stable_uuid(str(p["id"])),
                    vector=p["vector"],
                    payload={
                        **dict(p["payload"]),
                        "_source_id": str(p["id"]),
                    },
                )
            )
        if qpoints:
            self.client.upsert(collection_name=self.collection, points=qpoints)

    def search(self, *, vector: list[float], top_k: int = 5) -> list[Any]:
        return self.client.search(
            collection_name=self.collection,
            query_vector=vector,
            limit=max(1, int(top_k)),
            with_payload=True,
        )
