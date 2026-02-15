"""Elasticsearch storage for segments with vector embeddings."""

import uuid

import structlog
from elasticsearch import AsyncElasticsearch

from pam.common.models import KnowledgeSegment

logger = structlog.get_logger()


def get_index_mapping(embedding_dims: int) -> dict:
    """Build the Haystack-compatible ES index mapping with the given embedding dimensions."""
    return {
        "mappings": {
            "properties": {
                "content": {"type": "text", "analyzer": "standard"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "meta": {
                    "properties": {
                        "segment_id": {"type": "keyword"},
                        "document_id": {"type": "keyword"},
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
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
    }


class ElasticsearchStore:
    def __init__(self, client: AsyncElasticsearch, index_name: str, embedding_dims: int) -> None:
        self.client = client
        self.index_name = index_name
        self._embedding_dims = embedding_dims

    async def ensure_index(self) -> None:
        """Create the index if it doesn't exist."""
        exists = await self.client.indices.exists(index=self.index_name)
        if not exists:
            await self.client.indices.create(index=self.index_name, body=get_index_mapping(self._embedding_dims))
            logger.info("elasticsearch_index_created", index=self.index_name)
        else:
            logger.info("elasticsearch_index_exists", index=self.index_name)

    async def bulk_index(self, segments: list[KnowledgeSegment]) -> int:
        """Index segments with embeddings using bulk API (Haystack-compatible format)."""
        if not segments:
            return 0

        actions: list[dict] = []
        for seg in segments:
            if seg.embedding is None:
                logger.warning("skip_segment_no_embedding", segment_id=str(seg.id))
                continue

            action = {"index": {"_index": self.index_name, "_id": str(seg.id)}}
            doc = {
                "content": seg.content,
                "embedding": seg.embedding,
                "meta": {
                    "segment_id": str(seg.id),
                    "document_id": str(seg.document_id) if seg.document_id else None,
                    "source_type": seg.source_type,
                    "source_id": seg.source_id,
                    "source_url": seg.source_url,
                    "document_title": seg.document_title,
                    "section_path": seg.section_path,
                    "segment_type": seg.segment_type,
                    "position": seg.position,
                },
            }
            actions.append(action)
            actions.append(doc)

        if actions:
            total = len(actions) // 2
            response = await self.client.bulk(operations=actions, refresh="wait_for")
            errors = response.get("errors", False)
            if errors:
                failed_items = [
                    item["index"]["error"]
                    for item in response["items"]
                    if "error" in item.get("index", {})
                ]
                for error in failed_items:
                    logger.error("es_bulk_error", error=error)
                raise RuntimeError(f"ES bulk indexing failed: {len(failed_items)} of {total} documents failed")

            logger.info("es_bulk_index", index=self.index_name, count=total, errors=errors)
            return total
        return 0

    async def delete_by_document(self, document_id: uuid.UUID) -> int:
        """Delete all segments for a given document."""
        response = await self.client.delete_by_query(
            index=self.index_name,
            body={"query": {"term": {"meta.document_id": str(document_id)}}},
            refresh=True,
        )
        deleted: int = response.get("deleted", 0)
        logger.info("es_delete_by_document", document_id=str(document_id), deleted=deleted)
        return deleted
