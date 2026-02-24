"""Graph extraction orchestrator for per-chunk episode ingestion into Graphiti.

Handles both first-time ingestion and re-ingestion with chunk-level diffing.
Episode UUIDs are stored in segment metadata for surgical cleanup on failure
or re-ingestion. Does NOT catch exceptions -- the caller (pipeline.py)
handles fault isolation via try/except.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any

import structlog
from graphiti_core.nodes import EpisodeType

from pam.graph.entity_types import ENTITY_TYPES
from pam.ingestion.diff_engine import ChunkDiff, build_diff_summary, compute_chunk_diff

if TYPE_CHECKING:
    from pam.common.models import KnowledgeSegment, Segment
    from pam.graph.service import GraphitiService
    from pam.ingestion.embedders.base import BaseEmbedder
    from pam.ingestion.stores.entity_relationship_store import EntityRelationshipVDBStore

logger = structlog.get_logger()


@dataclass
class ExtractionResult:
    """Result of graph extraction for a single document."""

    episodes_added: int = 0
    episodes_removed: int = 0
    entities_extracted: list[dict] = field(default_factory=list)
    diff_summary: dict = field(default_factory=dict)
    progress_log: list[str] = field(default_factory=list)
    entities_embedded: int = 0
    relationships_embedded: int = 0


async def extract_graph_for_document(
    graph_service: GraphitiService,
    doc_id: uuid.UUID,
    segments: list[KnowledgeSegment],
    document_title: str,
    reference_time: datetime,
    source_id: str,
    old_segments: list[Segment] | None = None,
    vdb_store: EntityRelationshipVDBStore | None = None,
    embedder: BaseEmbedder | None = None,
) -> ExtractionResult:
    """Extract graph entities from document chunks via Graphiti add_episode().

    For first-time ingestion, all segments are treated as added.
    For re-ingestion (when old_segments is provided), a chunk-level diff
    determines which segments to add/remove.

    Args:
        graph_service: Initialized GraphitiService with Graphiti client.
        doc_id: UUID of the document being ingested.
        segments: New KnowledgeSegment objects from the pipeline.
        document_title: Title of the document for episode descriptions.
        reference_time: Bi-temporal reference time (document modified_at).
        source_id: Source identifier for the document.
        old_segments: Previous Segment ORM objects for diff (None = first ingestion).
        vdb_store: Optional VDB store for entity/relationship embedding.
        embedder: Optional embedder for VDB upsert (required if vdb_store is provided).

    Returns:
        ExtractionResult with extraction metrics and diff summary.

    Raises:
        Any exception from Graphiti operations -- caller handles fault isolation.
    """
    result = ExtractionResult()

    # Determine which chunks to process via diff engine
    if old_segments:
        diff = compute_chunk_diff(old_segments, segments)
    else:
        # First ingestion: all segments are new
        diff = ChunkDiff(added=list(segments), removed=[], unchanged=[])

    total_to_extract = len(diff.added)
    group_id = f"doc-{doc_id}"

    # Phase 1: Collect entity info from old episodes before removal
    old_entities: dict[str, dict[str, Any]] = {}
    removed_episode_uuids: list[str] = []

    for seg in diff.removed:
        seg_meta = seg.metadata_ if hasattr(seg, "metadata_") else {}
        episode_uuid = seg_meta.get("graph_episode_uuid")
        if episode_uuid:
            # Attempt to gather entity info before removal
            try:
                episode = await graph_service.client.get_episode(episode_uuid)
                if hasattr(episode, "nodes") and episode.nodes:
                    for node in episode.nodes:
                        node_name = node.name if hasattr(node, "name") else str(node)
                        labels = (
                            [la for la in node.labels if la != "Entity"]
                            if hasattr(node, "labels")
                            else []
                        )
                        old_entities[node_name] = {
                            "type": labels[0] if labels else "Unknown",
                        }
            except Exception:
                logger.debug(
                    "get_episode_before_removal_failed",
                    episode_uuid=episode_uuid,
                )

            await graph_service.client.remove_episode(episode_uuid)
            removed_episode_uuids.append(episode_uuid)
            logger.debug("removed_stale_episode", episode_uuid=episode_uuid)

    result.episodes_removed = len(removed_episode_uuids)

    # Phase 2: Extract new/changed chunks
    added_episode_uuids: list[str] = []
    new_entities: dict[str, dict[str, Any]] = {}
    uuid_to_name: dict[str, str] = {}
    all_edges: dict[str, dict] = {}  # rel_doc_id -> edge info

    for i, seg in enumerate(diff.added):
        episode_result = await graph_service.client.add_episode(
            name=f"chunk-{seg.id}",
            episode_body=seg.content,
            source=EpisodeType.text,
            source_description=(
                f"Document: {document_title} | Source: {source_id} | Chunk: {seg.position}"
            ),
            reference_time=reference_time,
            group_id=group_id,
            entity_types=ENTITY_TYPES,
        )

        # Store episode UUID in segment metadata for later cleanup
        episode_uuid = str(episode_result.episode.uuid)
        seg.metadata["graph_episode_uuid"] = episode_uuid
        seg.metadata["graph_entity_count"] = len(episode_result.nodes)
        added_episode_uuids.append(episode_uuid)

        # Collect entity info from extraction results
        for node in episode_result.nodes:
            node_name = node.name if hasattr(node, "name") else str(node)
            uuid_to_name[node.uuid] = node_name
            labels = (
                [la for la in node.labels if la != "Entity"]
                if hasattr(node, "labels")
                else []
            )
            entity_info: dict[str, Any] = {
                "type": labels[0] if labels else "Unknown",
            }
            # Collect any additional attributes from the node
            if hasattr(node, "summary") and node.summary:
                entity_info["summary"] = node.summary
            new_entities[node_name] = entity_info

            result.entities_extracted.append({
                "name": node_name,
                "type": entity_info["type"],
            })

        # Accumulate relationship edges across all chunks
        for edge in episode_result.edges:
            src_name = uuid_to_name.get(edge.source_node_uuid, edge.source_node_uuid)
            tgt_name = uuid_to_name.get(edge.target_node_uuid, edge.target_node_uuid)
            from pam.ingestion.stores.entity_relationship_store import (
                make_relationship_doc_id,
            )

            rel_key = make_relationship_doc_id(src_name, edge.name, tgt_name)
            all_edges[rel_key] = {
                "src_entity": src_name,
                "tgt_entity": tgt_name,
                "rel_type": edge.name,
                "description": edge.fact if hasattr(edge, "fact") else "",
                "episodes": edge.episodes if hasattr(edge, "episodes") else [],
            }

        progress_msg = f"extracted {i + 1}/{total_to_extract} chunks"
        result.progress_log.append(progress_msg)
        logger.info("graph_extraction_progress", progress=progress_msg, doc_id=str(doc_id))

    result.episodes_added = len(added_episode_uuids)

    # Phase 2b: VDB upsert (entity + relationship embeddings)
    if vdb_store is not None and embedder is not None:
        from pam.ingestion.stores.entity_relationship_store import (
            EntityVDBRecord,
            RelationshipVDBRecord,
        )

        # Build entity records from new_entities dict
        entity_records = [
            EntityVDBRecord(
                name=name,
                entity_type=info.get("type", "Unknown"),
                description=info.get("summary", ""),
                source_id=source_id,
            )
            for name, info in new_entities.items()
        ]

        # Build relationship records from accumulated edges
        rel_records = [
            RelationshipVDBRecord(
                src_entity=e["src_entity"],
                tgt_entity=e["tgt_entity"],
                rel_type=e["rel_type"],
                keywords=e["rel_type"].replace("_", " ").lower(),
                description=e["description"],
                source_id=source_id,
                weight=float(len(e["episodes"])) if e["episodes"] else 1.0,
            )
            for e in all_edges.values()
        ]

        try:
            entities_upserted = await vdb_store.upsert_entities(
                entity_records, embedder, source_id
            )
            rels_upserted = await vdb_store.upsert_relationships(
                rel_records, embedder, source_id
            )
            result.entities_embedded = entities_upserted
            result.relationships_embedded = rels_upserted
            logger.info(
                "vdb_upsert_complete",
                doc_id=str(doc_id),
                entities_upserted=entities_upserted,
                relationships_upserted=rels_upserted,
            )
        except Exception:
            # VDB upsert is non-blocking, same as graph extraction itself
            logger.warning("vdb_upsert_failed", doc_id=str(doc_id), exc_info=True)

    # Phase 3: Build diff summary
    result.diff_summary = build_diff_summary(
        added_entities=result.entities_extracted,
        removed_episode_uuids=removed_episode_uuids,
        old_entities=old_entities,
        new_entities=new_entities,
    )

    logger.info(
        "graph_extraction_complete",
        doc_id=str(doc_id),
        episodes_added=result.episodes_added,
        episodes_removed=result.episodes_removed,
        entities_count=len(result.entities_extracted),
    )

    return result


async def rollback_graph_for_document(
    graph_service: GraphitiService,
    segments: list[KnowledgeSegment],
) -> int:
    """Remove all graph episodes added during a failed ingestion run.

    Iterates over segments, finds any with ``graph_episode_uuid`` in metadata,
    and calls ``remove_episode()`` for each. Catches per-episode exceptions
    to ensure rollback continues even if individual removals fail.

    Args:
        graph_service: Initialized GraphitiService with Graphiti client.
        segments: KnowledgeSegment objects that may have episode UUIDs in metadata.

    Returns:
        Count of successfully rolled-back episodes.
    """
    rolled_back = 0

    for seg in segments:
        episode_uuid = seg.metadata.get("graph_episode_uuid")
        if not episode_uuid:
            continue

        try:
            await graph_service.client.remove_episode(episode_uuid)
            rolled_back += 1
            logger.debug("rollback_episode_removed", episode_uuid=episode_uuid)
        except Exception:
            logger.warning(
                "rollback_episode_failed",
                episode_uuid=episode_uuid,
                exc_info=True,
            )

        # Clear metadata regardless of success to prevent stale references
        seg.metadata.pop("graph_episode_uuid", None)
        seg.metadata.pop("graph_entity_count", None)

    logger.info("graph_rollback_complete", rolled_back=rolled_back, total_segments=len(segments))
    return rolled_back
