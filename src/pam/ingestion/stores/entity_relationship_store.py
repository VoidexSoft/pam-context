"""Elasticsearch VDB storage for entity and relationship embeddings.

Implements the LightRAG 3-VDB pattern (segments + entities + relationships)
with content-hash-based skip-re-embedding optimization.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from elasticsearch import AsyncElasticsearch

if TYPE_CHECKING:
    from pam.ingestion.embedders.base import BaseEmbedder

logger = structlog.get_logger()


@dataclass
class EntityVDBRecord:
    """Record for entity VDB index."""

    name: str
    entity_type: str
    description: str
    source_id: str
    file_path: str | None = None


@dataclass
class RelationshipVDBRecord:
    """Record for relationship VDB index."""

    src_entity: str
    tgt_entity: str
    rel_type: str
    keywords: str
    description: str
    source_id: str
    weight: float = 1.0


def get_entity_index_mapping(embedding_dims: int) -> dict:
    """Build the ES index mapping for entity VDB."""
    return {
        "mappings": {
            "properties": {
                "name": {"type": "keyword"},
                "entity_type": {"type": "keyword"},
                "description": {"type": "text", "analyzer": "standard"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "content_hash": {"type": "keyword"},
                "source_ids": {"type": "keyword"},
                "file_paths": {"type": "keyword"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
    }


def get_relationship_index_mapping(embedding_dims: int) -> dict:
    """Build the ES index mapping for relationship VDB."""
    return {
        "mappings": {
            "properties": {
                "src_entity": {"type": "keyword"},
                "tgt_entity": {"type": "keyword"},
                "rel_type": {"type": "keyword"},
                "keywords": {"type": "text", "analyzer": "standard"},
                "description": {"type": "text", "analyzer": "standard"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "content_hash": {"type": "keyword"},
                "weight": {"type": "float"},
                "source_ids": {"type": "keyword"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
    }


def make_relationship_doc_id(src: str, rel_type: str, tgt: str) -> str:
    """Create a deterministic ES doc ID for a relationship.

    Alphabetically sorts src/tgt to ensure A::REL::B == B::REL::A
    for undirected relationships, while allowing multiple relationship
    types between the same entity pair.
    """
    sorted_pair = sorted([src, tgt])
    return f"{sorted_pair[0]}::{rel_type}::{sorted_pair[1]}"


class EntityRelationshipVDBStore:
    """Manages entity and relationship vector indices in Elasticsearch."""

    def __init__(
        self,
        client: AsyncElasticsearch,
        entity_index: str,
        relationship_index: str,
        embedding_dims: int,
    ) -> None:
        self.client = client
        self.entity_index = entity_index
        self.relationship_index = relationship_index
        self._embedding_dims = embedding_dims

    async def ensure_indices(self) -> None:
        """Create entity and relationship indices if they don't exist."""
        for index_name, get_mapping in [
            (self.entity_index, get_entity_index_mapping),
            (self.relationship_index, get_relationship_index_mapping),
        ]:
            exists = await self.client.indices.exists(index=index_name)
            if not exists:
                await self.client.indices.create(
                    index=index_name,
                    body=get_mapping(self._embedding_dims),
                )
                logger.info("vdb_index_created", index=index_name)
            else:
                logger.info("vdb_index_exists", index=index_name)

    async def _filter_unchanged(
        self,
        index_name: str,
        doc_ids: list[str],
        new_hashes: list[str],
    ) -> tuple[list[str], list[int]]:
        """Compare content hashes against existing ES records.

        Returns (texts_to_embed, indices_of_changed) for only records
        whose content hash differs from the stored version.
        """
        if not doc_ids:
            return [], []

        # Fetch existing content_hash fields via mget
        response = await self.client.mget(
            index=index_name,
            body={"ids": doc_ids},
            _source=["content_hash"],
        )

        changed_indices: list[int] = []
        for i, doc in enumerate(response["docs"]):
            if doc.get("found"):
                existing_hash = doc["_source"].get("content_hash", "")
                if existing_hash == new_hashes[i]:
                    continue  # unchanged, skip re-embedding
            changed_indices.append(i)

        return [doc_ids[i] for i in changed_indices], changed_indices

    async def upsert_entities(
        self,
        entities: list[EntityVDBRecord],
        embedder: BaseEmbedder,
        source_id: str,
    ) -> int:
        """Embed and upsert entity records into ES.

        Skips re-embedding for entities whose description content hash
        matches the existing record. Returns the count of upserted records.
        """
        if not entities:
            return 0

        # Build embedding texts (LightRAG format: name\ndescription)
        embedding_texts = [f"{e.name}\n{e.description}" for e in entities]
        content_hashes = [
            hashlib.sha256(text.encode()).hexdigest() for text in embedding_texts
        ]
        doc_ids = [e.name for e in entities]

        # Filter out unchanged entities
        _, changed_indices = await self._filter_unchanged(
            self.entity_index, doc_ids, content_hashes
        )

        if not changed_indices:
            logger.info(
                "vdb_entities_all_unchanged",
                total=len(entities),
                source_id=source_id,
            )
            return 0

        # Embed only changed texts
        texts_to_embed = [embedding_texts[i] for i in changed_indices]
        embeddings = await embedder.embed_texts(texts_to_embed)

        # Build bulk actions
        actions: list[dict] = []
        for idx, embed_idx in enumerate(changed_indices):
            entity = entities[embed_idx]
            action = {
                "index": {
                    "_index": self.entity_index,
                    "_id": entity.name,
                }
            }
            doc = {
                "name": entity.name,
                "entity_type": entity.entity_type,
                "description": entity.description,
                "embedding": embeddings[idx],
                "content_hash": content_hashes[embed_idx],
                "source_ids": [source_id],
                "file_paths": [entity.file_path] if entity.file_path else [],
            }
            actions.append(action)
            actions.append(doc)

        if actions:
            response = await self.client.bulk(operations=actions, refresh="wait_for")
            errors = response.get("errors", False)
            if errors:
                failed_items = [
                    item["index"]["error"]
                    for item in response["items"]
                    if "error" in item.get("index", {})
                ]
                for error in failed_items:
                    logger.error("vdb_entity_bulk_error", error=error)

        upserted = len(changed_indices)
        logger.info(
            "vdb_entities_upserted",
            upserted=upserted,
            skipped=len(entities) - upserted,
            source_id=source_id,
        )
        return upserted

    async def upsert_relationships(
        self,
        relationships: list[RelationshipVDBRecord],
        embedder: BaseEmbedder,
        source_id: str,
    ) -> int:
        """Embed and upsert relationship records into ES.

        Same content-hash optimization as upsert_entities. Uses the LightRAG
        embedding format: keywords\\tsrc_entity\\ntgt_entity\\ndescription.
        Returns the count of upserted records.
        """
        if not relationships:
            return 0

        # Build embedding texts (LightRAG format)
        embedding_texts = [
            f"{r.keywords}\t{r.src_entity}\n{r.tgt_entity}\n{r.description}"
            for r in relationships
        ]
        content_hashes = [
            hashlib.sha256(text.encode()).hexdigest() for text in embedding_texts
        ]
        doc_ids = [
            make_relationship_doc_id(r.src_entity, r.rel_type, r.tgt_entity)
            for r in relationships
        ]

        # Filter out unchanged relationships
        _, changed_indices = await self._filter_unchanged(
            self.relationship_index, doc_ids, content_hashes
        )

        if not changed_indices:
            logger.info(
                "vdb_relationships_all_unchanged",
                total=len(relationships),
                source_id=source_id,
            )
            return 0

        # Embed only changed texts
        texts_to_embed = [embedding_texts[i] for i in changed_indices]
        embeddings = await embedder.embed_texts(texts_to_embed)

        # Build bulk actions
        actions: list[dict] = []
        for idx, embed_idx in enumerate(changed_indices):
            rel = relationships[embed_idx]
            action = {
                "index": {
                    "_index": self.relationship_index,
                    "_id": doc_ids[embed_idx],
                }
            }
            doc = {
                "src_entity": rel.src_entity,
                "tgt_entity": rel.tgt_entity,
                "rel_type": rel.rel_type,
                "keywords": rel.keywords,
                "description": rel.description,
                "embedding": embeddings[idx],
                "content_hash": content_hashes[embed_idx],
                "weight": rel.weight,
                "source_ids": [source_id],
            }
            actions.append(action)
            actions.append(doc)

        if actions:
            response = await self.client.bulk(operations=actions, refresh="wait_for")
            errors = response.get("errors", False)
            if errors:
                failed_items = [
                    item["index"]["error"]
                    for item in response["items"]
                    if "error" in item.get("index", {})
                ]
                for error in failed_items:
                    logger.error("vdb_relationship_bulk_error", error=error)

        upserted = len(changed_indices)
        logger.info(
            "vdb_relationships_upserted",
            upserted=upserted,
            skipped=len(relationships) - upserted,
            source_id=source_id,
        )
        return upserted
