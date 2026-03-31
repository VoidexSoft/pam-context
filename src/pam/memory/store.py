"""Elasticsearch store for memory embeddings and kNN search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch

logger = structlog.get_logger()


def get_memory_index_mapping(embedding_dims: int) -> dict:
    """Build the ES index mapping for the memory VDB."""
    return {
        "mappings": {
            "properties": {
                "content": {"type": "text", "analyzer": "standard"},
                "user_id": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "type": {"type": "keyword"},
                "source": {"type": "keyword"},
                "importance": {"type": "float"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
    }


class MemoryStore:
    """Elasticsearch store for memory vector search."""

    def __init__(
        self,
        client: AsyncElasticsearch,
        index_name: str,
        embedding_dims: int,
    ) -> None:
        self._client = client
        self._index_name = index_name
        self._embedding_dims = embedding_dims

    async def ensure_index(self) -> None:
        """Create the memory index if it does not exist."""
        exists = await self._client.indices.exists(index=self._index_name)
        if not exists:
            mapping = get_memory_index_mapping(self._embedding_dims)
            await self._client.indices.create(index=self._index_name, body=mapping)
            logger.info("memory_index_created", index=self._index_name)

    async def index_memory(
        self,
        memory_id: UUID,
        content: str,
        embedding: list[float],
        user_id: UUID | None,
        project_id: UUID | None,
        memory_type: str,
        importance: float,
        source: str | None = None,
    ) -> None:
        """Index a memory document for kNN search."""
        doc: dict[str, Any] = {
            "content": content,
            "embedding": embedding,
            "type": memory_type,
            "importance": importance,
        }
        if user_id:
            doc["user_id"] = str(user_id)
        if project_id:
            doc["project_id"] = str(project_id)
        if source:
            doc["source"] = source

        await self._client.index(
            index=self._index_name,
            id=str(memory_id),
            document=doc,
            refresh="wait_for",
        )

    async def search(
        self,
        query_embedding: list[float],
        user_id: UUID | None = None,
        project_id: UUID | None = None,
        type_filter: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """kNN search with optional user/project/type filters."""
        if top_k < 1 or top_k > 100:
            top_k = min(max(top_k, 1), 100)

        filters: list[dict] = []
        if user_id:
            filters.append({"term": {"user_id": str(user_id)}})
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})
        if type_filter:
            filters.append({"term": {"type": type_filter}})

        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": top_k,
            "num_candidates": top_k * 10,
        }
        if filters:
            knn["filter"] = {"bool": {"must": filters}}

        result = await self._client.search(
            index=self._index_name,
            knn=knn,
            size=top_k,
        )

        return [
            {
                "memory_id": hit["_id"],
                "score": hit["_score"],
                "content": hit["_source"].get("content", ""),
                "type": hit["_source"].get("type", ""),
                "importance": hit["_source"].get("importance", 0),
            }
            for hit in result["hits"]["hits"]
        ]

    async def find_duplicates(
        self,
        embedding: list[float],
        user_id: UUID | None,
        threshold: float = 0.9,
    ) -> list[dict[str, Any]]:
        """Find semantically similar memories for dedup check.

        Returns memories with cosine similarity >= threshold.
        """
        filters: list[dict] = []
        if user_id:
            filters.append({"term": {"user_id": str(user_id)}})

        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": embedding,
            "k": 5,
            "num_candidates": 50,
            "similarity": threshold,
        }
        if filters:
            knn["filter"] = {"bool": {"must": filters}}

        result = await self._client.search(
            index=self._index_name,
            knn=knn,
            size=5,
        )

        # ES knn `similarity` parameter already filters by threshold;
        # no redundant Python post-filter needed.
        return [
            {
                "memory_id": hit["_id"],
                "score": hit["_score"],
                "content": hit["_source"].get("content", ""),
            }
            for hit in result["hits"]["hits"]
        ]

    async def delete(self, memory_id: UUID) -> None:
        """Remove a memory from the ES index."""
        await self._client.delete(
            index=self._index_name,
            id=str(memory_id),
            refresh="wait_for",
        )

    async def update_importance(self, memory_id: UUID, importance: float) -> None:
        """Update the importance score of a memory in ES."""
        await self._client.update(
            index=self._index_name,
            id=str(memory_id),
            doc={"importance": importance},
            refresh="wait_for",
        )
