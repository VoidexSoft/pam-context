"""Orchestrates the entity-to-graph flow: fetch entities, map, extract relationships, write."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pam.common.graph import GraphClient
from pam.common.models import ExtractedEntity
from pam.graph.mapper import EntityGraphMapper
from pam.graph.relationship_extractor import RelationshipExtractor
from pam.graph.writer import GraphWriter

logger = structlog.get_logger(__name__)


class GraphPipeline:
    """Orchestrates building the knowledge graph from extracted entities."""

    def __init__(
        self,
        graph_client: GraphClient,
        relationship_extractor: RelationshipExtractor | None = None,
    ) -> None:
        self._mapper = EntityGraphMapper()
        self._writer = GraphWriter(graph_client)
        self._relationship_extractor = relationship_extractor or RelationshipExtractor()

    async def process_document(
        self,
        document_id: uuid.UUID,
        document_title: str,
        db_session: AsyncSession,
    ) -> int:
        """Build graph nodes and edges for a document's extracted entities.

        Returns the number of nodes written.
        """
        # 1. Fetch extracted entities from PostgreSQL
        result = await db_session.execute(
            select(ExtractedEntity).where(
                ExtractedEntity.source_segment_id.isnot(None)
            )
        )
        all_entities = result.scalars().all()

        # Filter to entities whose segments belong to this document
        # (ExtractedEntity has source_segment_id -> segment -> document_id)
        entities_data = []
        for entity in all_entities:
            if entity.source_segment and entity.source_segment.document_id == document_id:
                entities_data.append({
                    "entity_type": entity.entity_type,
                    "entity_data": entity.entity_data,
                    "confidence": entity.confidence,
                    "source_segment_id": entity.source_segment_id,
                })

        if not entities_data:
            logger.info("graph_pipeline_no_entities", document_id=str(document_id))
            return 0

        # 2. Map entities to nodes
        mapping = self._mapper.map_entities(entities_data)
        all_nodes = mapping.nodes + mapping.implicit_teams + mapping.implicit_data_sources

        # 3. Write nodes
        await self._writer.upsert_nodes_batch(all_nodes)

        # 4. Write document node + DEFINED_IN edges
        await self._writer.write_document_edges(str(document_id), document_title, mapping.nodes)

        # 5. Write implicit OWNED_BY / SOURCED_FROM edges
        await self._writer.write_implicit_edges(mapping.nodes)

        # 6. Extract and write relationships (LLM-assisted)
        try:
            relationships = await self._relationship_extractor.extract_relationships(mapping.nodes)
            if relationships:
                await self._writer.write_relationships(relationships)
        except Exception:
            logger.warning("graph_pipeline_relationship_extraction_failed", exc_info=True)

        node_count = len(all_nodes)
        logger.info(
            "graph_pipeline_complete",
            document_id=str(document_id),
            nodes=node_count,
            relationships=len(relationships) if 'relationships' in dir() else 0,
        )
        return node_count
