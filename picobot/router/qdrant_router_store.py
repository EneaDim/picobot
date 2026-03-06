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

    def close(self) -> None:
        """
        Chiusura esplicita del client Qdrant embedded.
        """
        try:
            self.client.close()
        except Exception:
            pass

    def recreate_collection(self, vector_size: int) -> None:
        try:
            if self.client.collection_exists(self.collection):
                self.client.delete_collection(self.collection)
        except Exception:
            pass

        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=models.VectorParams(
                size=int(vector_size),
                distance=models.Distance.COSINE,
            ),
        )

    def count(self) -> int:
        try:
            res = self.client.count(collection_name=self.collection, exact=True)
            return int(getattr(res, "count", 0) or 0)
        except Exception:
            return 0

    def upsert(self, points: list[dict[str, Any]]) -> int:
        if not points:
            return 0

        qpoints: list[models.PointStruct] = []

        for point in points:
            source_id = str(point["id"])
            payload = dict(point.get("payload") or {})

            qpoints.append(
                models.PointStruct(
                    id=stable_uuid(source_id),
                    vector=point["vector"],
                    payload={
                        **payload,
                        "_source_id": source_id,
                    },
                )
            )

        self.client.upsert(
            collection_name=self.collection,
            points=qpoints,
            wait=True,
        )

        return len(qpoints)

    def _normalize_query_points_result(self, result: Any) -> list[Any]:
        if result is None:
            return []

        points = getattr(result, "points", None)
        if isinstance(points, list):
            return points

        if isinstance(result, list):
            return result

        return []

    def search(self, *, vector: list[float], top_k: int = 8) -> list[Any]:
        limit = max(1, int(top_k))

        if hasattr(self.client, "query_points"):
            result = self.client.query_points(
                collection_name=self.collection,
                query=vector,
                limit=limit,
                with_payload=True,
            )
            return self._normalize_query_points_result(result)

        if hasattr(self.client, "search"):
            return self.client.search(
                collection_name=self.collection,
                query_vector=vector,
                limit=limit,
                with_payload=True,
            )

        raise RuntimeError("This qdrant-client version supports neither query_points nor search")
