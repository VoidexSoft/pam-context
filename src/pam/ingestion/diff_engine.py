"""Chunk-level diff engine for graph re-ingestion.

Compares old vs new segment content_hash sets to classify chunks as
added/removed/unchanged. Builds structured diff summaries with entity-level
detail (including field-level old/new changes) for SyncLog persistence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pam.common.models import KnowledgeSegment, Segment


@dataclass
class ChunkDiff:
    """Result of comparing old vs new segment sets by content_hash."""

    added: list[Any] = field(default_factory=list)  # KnowledgeSegment objects
    removed: list[Any] = field(default_factory=list)  # Segment ORM objects
    unchanged: list[Any] = field(default_factory=list)  # KnowledgeSegment objects


def compute_chunk_diff(
    old_segments: list[Segment],
    new_segments: list[KnowledgeSegment],
) -> ChunkDiff:
    """Compare old and new segments by content_hash to determine changes.

    Args:
        old_segments: Existing Segment ORM objects from the database.
        new_segments: New KnowledgeSegment Pydantic objects from the pipeline.

    Returns:
        ChunkDiff with added, removed, and unchanged segment lists.
    """
    old_hashes: dict[str, Segment] = {seg.content_hash: seg for seg in old_segments}
    new_hashes: dict[str, KnowledgeSegment] = {seg.content_hash: seg for seg in new_segments}

    added = [seg for seg in new_segments if seg.content_hash not in old_hashes]
    removed = [seg for seg in old_segments if seg.content_hash not in new_hashes]

    unchanged = []
    for seg in new_segments:
        if seg.content_hash in old_hashes:
            # Preserve episode tracking from old segment metadata
            old_seg = old_hashes[seg.content_hash]
            old_meta = old_seg.metadata_ if hasattr(old_seg, "metadata_") else {}
            if "graph_episode_uuid" in old_meta:
                seg.metadata["graph_episode_uuid"] = old_meta["graph_episode_uuid"]
            if "graph_entity_count" in old_meta:
                seg.metadata["graph_entity_count"] = old_meta["graph_entity_count"]
            unchanged.append(seg)

    return ChunkDiff(added=added, removed=removed, unchanged=unchanged)


def build_diff_summary(
    added_entities: list[dict],
    removed_episode_uuids: list[str],
    old_entities: dict[str, dict],
    new_entities: dict[str, dict],
) -> dict:
    """Build structured diff summary for SyncLog.details persistence.

    Produces a JSON-serializable dict with added, removed_from_document, and
    modified entities. The ``modified`` key provides field-level old/new detail
    per the locked user decision.

    Args:
        added_entities: Entity dicts extracted from newly-added episodes.
        removed_episode_uuids: UUIDs of episodes that were removed.
        old_entities: Dict keyed by entity name with attribute dicts
            (e.g., ``{"Team Alpha": {"type": "team", "lead": "Alice"}}``).
        new_entities: Dict keyed by entity name with attribute dicts.

    Returns:
        Structured diff dict with keys: added, removed_from_document, modified,
        episodes_added, episodes_removed.
    """
    # Entities present only in new set
    added = [
        {"name": name, **attrs}
        for name, attrs in new_entities.items()
        if name not in old_entities
    ]

    # Entities present only in old set (removed from this document,
    # not necessarily deleted from graph -- Graphiti preserves entities
    # referenced by other episodes)
    removed_from_document = [
        {"name": name, **attrs}
        for name, attrs in old_entities.items()
        if name not in new_entities
    ]

    # Entities present in both but with changed attributes -- field-level detail
    modified: list[dict] = []
    for name in old_entities:
        if name not in new_entities:
            continue
        old_attrs = old_entities[name]
        new_attrs = new_entities[name]
        # Compare all attribute keys across both dicts
        all_keys = set(old_attrs.keys()) | set(new_attrs.keys())
        for attr_key in sorted(all_keys):
            old_val = old_attrs.get(attr_key)
            new_val = new_attrs.get(attr_key)
            if old_val != new_val:
                modified.append({
                    "name": name,
                    "field": attr_key,
                    "old": old_val,
                    "new": new_val,
                })

    return {
        "added": added,
        "removed_from_document": removed_from_document,
        "modified": modified,
        "episodes_added": len(added_entities),
        "episodes_removed": len(removed_episode_uuids),
    }
