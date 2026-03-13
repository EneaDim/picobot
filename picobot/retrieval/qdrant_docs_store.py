from __future__ import annotations

import uuid
from typing import Any

from picobot.runtime_config import cfg_get

try:
    from qdrant_client import QdrantClient, models

    QDRANT_AVAILABLE = True
    QDRANT_IMPORT_ERROR: Exception | None = None
except Exception as e:  # pragma: no cover - dipende dall'ambiente
    QdrantClient = None  # type: ignore[assignment]
    models = None  # type: ignore[assignment]
    QDRANT_AVAILABLE = False
    QDRANT_IMPORT_ERROR = e


def stable_uuid(value: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, value))


class DocsQdrantStore:
    def __init__(self) -> None:
        self.path = str(cfg_get("qdrant.path", ".picobot/qdrant"))
        self.collection = str(cfg_get("qdrant.docs_collection", "docs_index"))
        self.enabled = QDRANT_AVAILABLE
        self.client = QdrantClient(path=self.path) if QDRANT_AVAILABLE else None

    def close(self) -> None:
        """
        Chiusura esplicita del client Qdrant embedded.
        """
        if not self.client:
            return

        try:
            self.client.close()
        except Exception:
            pass

    def ensure_collection(self, vector_size: int) -> None:
        if not self.client or not models:
            return

        vector_size = int(vector_size)

        try:
            exists = self.client.collection_exists(self.collection)
        except Exception:
            exists = False

        if not exists:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )
            return

        try:
            info = self.client.get_collection(self.collection)
            current_vectors = info.config.params.vectors
            current_size = int(getattr(current_vectors, "size", vector_size))
        except Exception:
            current_size = vector_size

        if current_size != vector_size:
            self.client.delete_collection(self.collection)
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=vector_size,
                    distance=models.Distance.COSINE,
                ),
            )

    def delete_kb(self, kb_name: str) -> None:
        if not self.client or not models:
            return

        kb_name = str(kb_name or "").strip()
        if not kb_name:
            return

        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="kb_name",
                    match=models.MatchValue(value=kb_name),
                )
            ]
        )

        try:
            self.client.delete(
                collection_name=self.collection,
                points_selector=models.FilterSelector(filter=query_filter),
                wait=True,
            )
        except Exception:
            pass

    def upsert(self, points: list[dict[str, Any]]) -> int:
        if not self.client or not models:
            return 0

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

    def search(
        self,
        *,
        vector: list[float],
        kb_name: str,
        top_k: int = 8,
    ) -> list[Any]:
        if not self.client or not models:
            return []

        limit = max(1, int(top_k))

        query_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="kb_name",
                    match=models.MatchValue(value=kb_name),
                )
            ]
        )

        try:
            if hasattr(self.client, "query_points"):
                result = self.client.query_points(
                    collection_name=self.collection,
                    query=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )
                return self._normalize_query_points_result(result)

            if hasattr(self.client, "search"):
                return self.client.search(
                    collection_name=self.collection,
                    query_vector=vector,
                    query_filter=query_filter,
                    limit=limit,
                    with_payload=True,
                )

            raise RuntimeError("This qdrant-client version supports neither query_points nor search")
        except Exception as exc:
            message = str(exc).lower()
            if "collection" in message and "not found" in message:
                return []
            raise
