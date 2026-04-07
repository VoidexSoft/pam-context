"""Elasticsearch store for glossary term embeddings and search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch

logger = structlog.get_logger()


def get_glossary_index_mapping(embedding_dims: int) -> dict:
    """Build the ES index mapping for glossary terms."""
    return {
        "mappings": {
            "properties": {
                "canonical": {"type": "keyword", "normalizer": "lowercase"},
                "canonical_text": {"type": "text", "analyzer": "standard"},
                "aliases": {"type": "keyword", "normalizer": "lowercase"},
                "aliases_text": {"type": "text", "analyzer": "standard"},
                "definition": {"type": "text", "analyzer": "standard"},
                "category": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "normalizer": {
                    "lowercase": {
                        "type": "custom",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
    }


class GlossaryStore:
    """Elasticsearch store for glossary term vector + keyword search."""

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
        """Create the glossary index if it does not exist."""
        exists = await self._client.indices.exists(index=self._index_name)
        if not exists:
            mapping = get_glossary_index_mapping(self._embedding_dims)
            await self._client.indices.create(index=self._index_name, body=mapping)
            logger.info("glossary_index_created", index=self._index_name)

    async def index_term(
        self,
        term_id: UUID,
        canonical: str,
        aliases: list[str],
        definition: str,
        embedding: list[float],
        category: str,
        project_id: UUID | None = None,
    ) -> None:
        """Index a glossary term for kNN + keyword search."""
        doc: dict[str, Any] = {
            "canonical": canonical,
            "canonical_text": canonical,
            "aliases": [a.strip() for a in aliases if a.strip()],
            "aliases_text": " ".join(a.strip() for a in aliases if a.strip()),
            "definition": definition,
            "embedding": embedding,
            "category": category,
        }
        if project_id:
            doc["project_id"] = str(project_id)

        await self._client.index(
            index=self._index_name,
            id=str(term_id),
            document=doc,
            refresh="wait_for",
        )

    async def search(
        self,
        query_embedding: list[float],
        project_id: UUID | None = None,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic kNN search for glossary terms."""
        if top_k < 1 or top_k > 100:
            top_k = min(max(top_k, 1), 100)

        filters: list[dict] = []
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})
        if category:
            filters.append({"term": {"category": category}})

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
                "term_id": hit["_id"],
                "score": hit["_score"],
                "canonical": hit["_source"].get("canonical", ""),
                "aliases": hit["_source"].get("aliases", []),
                "definition": hit["_source"].get("definition", ""),
                "category": hit["_source"].get("category", ""),
            }
            for hit in result["hits"]["hits"]
        ]

    async def search_by_alias(
        self,
        alias: str,
        project_id: UUID | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Keyword search on canonical + aliases fields (case-insensitive).

        Uses multi_match across keyword (exact, lowercased) and text (analyzed) fields.
        """
        filters: list[dict] = []
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})

        query: dict[str, Any] = {
            "bool": {
                "should": [
                    {"term": {"canonical": alias.lower()}},
                    {"term": {"aliases": alias.lower()}},
                    {"match": {"canonical_text": {"query": alias, "boost": 2.0}}},
                    {"match": {"aliases_text": {"query": alias, "boost": 1.5}}},
                    {"match": {"definition": {"query": alias, "boost": 0.5}}},
                ],
                "minimum_should_match": 1,
            }
        }
        if filters:
            query["bool"]["filter"] = filters

        result = await self._client.search(
            index=self._index_name,
            query=query,
            size=top_k,
        )

        return [
            {
                "term_id": hit["_id"],
                "score": hit["_score"],
                "canonical": hit["_source"].get("canonical", ""),
                "aliases": hit["_source"].get("aliases", []),
                "definition": hit["_source"].get("definition", ""),
                "category": hit["_source"].get("category", ""),
            }
            for hit in result["hits"]["hits"]
        ]

    async def find_duplicates(
        self,
        embedding: list[float],
        project_id: UUID | None,
        threshold: float = 0.92,
    ) -> list[dict[str, Any]]:
        """Find semantically similar terms for dedup check."""
        filters: list[dict] = []
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})

        normalized_threshold = (1.0 + threshold) / 2.0
        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": embedding,
            "k": 5,
            "num_candidates": 50,
            "similarity": normalized_threshold,
        }
        if filters:
            knn["filter"] = {"bool": {"must": filters}}

        result = await self._client.search(
            index=self._index_name,
            knn=knn,
            size=5,
        )

        return [
            {
                "term_id": hit["_id"],
                "score": hit["_score"],
                "canonical": hit["_source"].get("canonical", ""),
            }
            for hit in result["hits"]["hits"]
        ]

    async def delete(self, term_id: UUID) -> None:
        """Remove a term from the ES index. Tolerates missing docs."""
        await self._client.options(ignore_status=404).delete(
            index=self._index_name,
            id=str(term_id),
            refresh="wait_for",
        )
