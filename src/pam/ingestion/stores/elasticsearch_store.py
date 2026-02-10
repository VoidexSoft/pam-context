"""Elasticsearch storage for segments with vector embeddings."""

import uuid

import structlog
from elasticsearch import AsyncElasticsearch

from pam.common.config import settings
from pam.common.models import KnowledgeSegment

logger = structlog.get_logger()

INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "segment_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "content": {"type": "text", "analyzer": "standard"},
            "embedding": {
                "type": "dense_vector",
                "dims": settings.embedding_dims,
                "index": True,
                "similarity": "cosine",
            },
            "source_type": {"type": "keyword"},
            "source_id": {"type": "keyword"},
            "source_url": {"type": "keyword"},
            "document_title": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "section_path": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
            "segment_type": {"type": "keyword"},
            "position": {"type": "integer"},
            "project": {"type": "keyword"},
            "owner": {"type": "keyword"},
            "tags": {"type": "keyword"},
            "updated_at": {"type": "date"},
        }
    },
    "settings": {
        "number_of_shards": 1,
        "number_of_replicas": 0,
    },
}


class ElasticsearchStore:
    def __init__(self, client: AsyncElasticsearch, index_name: str | None = None) -> None:
        self.client = client
        self.index_name = index_name or settings.elasticsearch_index

    async def ensure_index(self) -> None:
        """Create the index if it doesn't exist."""
        exists = await self.client.indices.exists(index=self.index_name)
        if not exists:
            await self.client.indices.create(index=self.index_name, body=INDEX_MAPPING)
            logger.info("elasticsearch_index_created", index=self.index_name)
        else:
            logger.info("elasticsearch_index_exists", index=self.index_name)

    async def bulk_index(self, segments: list[KnowledgeSegment]) -> int:
        """Index segments with embeddings using bulk API."""
        if not segments:
            return 0

        actions = []
        for seg in segments:
            if seg.embedding is None:
                logger.warning("skip_segment_no_embedding", segment_id=str(seg.id))
                continue

            action = {"index": {"_index": self.index_name, "_id": str(seg.id)}}
            doc = {
                "segment_id": str(seg.id),
                "document_id": str(seg.document_id) if seg.document_id else None,
                "content": seg.content,
                "embedding": seg.embedding,
                "source_type": seg.source_type,
                "source_id": seg.source_id,
                "source_url": seg.source_url,
                "document_title": seg.document_title,
                "section_path": seg.section_path,
                "segment_type": seg.segment_type,
                "position": seg.position,
            }
            actions.append(action)
            actions.append(doc)

        if actions:
            response = await self.client.bulk(body=actions, refresh="wait_for")
            errors = response.get("errors", False)
            if errors:
                for item in response["items"]:
                    if "error" in item.get("index", {}):
                        logger.error("es_bulk_error", error=item["index"]["error"])

            indexed = len(actions) // 2
            logger.info("es_bulk_index", index=self.index_name, count=indexed, errors=errors)
            return indexed
        return 0

    async def delete_by_document(self, document_id: uuid.UUID) -> int:
        """Delete all segments for a given document."""
        response = await self.client.delete_by_query(
            index=self.index_name,
            body={"query": {"term": {"document_id": str(document_id)}}},
            refresh=True,
        )
        deleted = response.get("deleted", 0)
        logger.info("es_delete_by_document", document_id=str(document_id), deleted=deleted)
        return deleted
