# Phase 7: Ingestion Pipeline Extension + Diff Engine - Research

**Researched:** 2026-02-20
**Domain:** Graphiti episode ingestion, bi-temporal knowledge graph updates, entity-level diff detection, graph fault isolation
**Confidence:** HIGH

## Summary

This phase extends the existing ingestion pipeline (`src/pam/ingestion/pipeline.py`) to call Graphiti's `add_episode()` after PG/ES commit, producing entity nodes and relationship edges in Neo4j with bi-temporal timestamps. The pipeline currently follows a clean linear flow: fetch -> hash-check -> parse -> chunk -> embed -> PG write -> ES write. Graph extraction inserts as a non-blocking step after ES write, catching all exceptions to preserve PG/ES integrity.

The key technical challenge is re-ingestion with change detection. The user's locked decision specifies chunk-level diffing: compare old vs new chunk content_hash values, only re-extract changed chunks through Graphiti. This saves LLM calls on unchanged content. Graphiti provides `remove_episode()` for individual episode cleanup and `add_episode()` with full edge invalidation -- but no built-in "diff and update" mechanism. The diff engine must be hand-built: compare old segment content hashes against new ones to identify added/modified/removed chunks, remove stale episodes, and re-add only changed chunks.

The `clear_data(driver, group_ids=[...])` utility function from `graphiti_core.utils.maintenance.graph_data_operations` can delete all graph data for a given group_id, but this is a nuclear option that defeats the chunk-level diff purpose. Instead, the implementation should track episode UUIDs per chunk (stored in PG segment metadata) and use `remove_episode(episode_uuid)` for surgical cleanup of changed/removed chunks only.

**Primary recommendation:** Add graph extraction as a try/except-wrapped step after ES write in the existing pipeline, using one `add_episode()` call per chunk with `group_id=f"doc-{doc_id}"` and `reference_time=document.modified_at`. Track episode UUIDs in segment metadata for chunk-level re-ingestion. Add `graph_synced` boolean to the Document model via Alembic migration. Build the diff engine as a comparison of old vs new segment content_hash sets.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Entity extraction flow
- One Graphiti episode per chunk (not per document)
- Chunk size should be optimized for extraction quality -- researcher should investigate optimal chunk sizing for Graphiti episodes (web research requested)
- Constrain extraction to our Phase 6 entity type taxonomy upfront -- pass entity types to Graphiti so it only extracts matching entities
- Use Graphiti's built-in entity resolution for cross-document deduplication (auto-merge by name)
- Track document provenance on each entity/edge -- store source document IDs so we can answer "where did this fact come from?"

#### Graph write timing
- Graph extraction runs inline during ingestion but is non-blocking -- failures are caught and don't prevent PG/ES commit
- On graph failure mid-document, roll back all graph writes for that document (no partial graph state)
- Mark failed documents with `graph_synced=False` in PostgreSQL for later retry
- Graph extraction progress is visible in the ingestion response (e.g., "extracting entities 3/10 chunks")
- Support `?skip_graph=true` query param to opt out of graph extraction per ingestion call (useful for bulk imports)

#### Diff summary content
- Full before/after detail in diffs -- e.g., `{modified: [{name: "Team Alpha", field: "lead", old: "Alice", new: "Bob"}]}`
- Distinguish between "removed from this document" vs "deleted from graph entirely" (orphaned node with no remaining sources)
- Chunk-level diff first -- compare old vs new chunk text, only re-extract changed chunks through Graphiti (saves LLM calls on unchanged content)
- Diff summary both returned in the ingestion API response AND persisted in SyncLog.details

#### Sync recovery behavior
- `POST /ingest/sync-graph` accepts `?limit=N` for batch size control (default to all if no limit)
- Per-document results in response: `{synced: [{doc_id, status, entities_added}], failed: [{doc_id, error}], remaining: N}`
- Max retry count before marking a document as permanently failed (`graph_sync_failed`) -- prevents infinite retry loops
- "Sync Graph" button in admin dashboard UI that calls the endpoint -- not API-only

### Claude's Discretion
- Exact max retry count for permanent failure marking
- Default batch size for sync-graph
- How to handle the graph rollback on partial failure (Graphiti transaction semantics vs manual cleanup)
- Loading/progress UI for the sync button in admin dashboard
- Exact format of the progress field in ingestion response

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| EXTRACT-01 | Ingestion pipeline calls add_episode() (never add_episode_bulk) after PG commit for each segment | Graphiti `add_episode()` API fully documented with all parameters; confirmed `add_episode_bulk` skips temporal invalidation |
| EXTRACT-02 | Entity nodes and relationship edges created in Neo4j with bi-temporal timestamps sourced from document modified_at | `reference_time` parameter maps to edge `valid_at`; Graphiti's LLM extracts temporal markers; `created_at` auto-set on ingestion |
| EXTRACT-03 | graph_synced boolean added to PG documents table via Alembic migration | Existing migration pattern (004, 005) documented; straightforward column addition to Document model |
| EXTRACT-04 | Graph extraction runs as background step -- failure never rolls back PG/ES data | Pipeline structure (PG commit -> ES write -> graph) with try/except isolation; `remove_episode()` for rollback on partial failure |
| EXTRACT-05 | Reconciliation endpoint /ingest/sync-graph retries documents with graph_synced=False | Query `Document.graph_synced == False`, run graph extraction for each, update flag on success; retry count tracking via `graph_sync_retries` column |
| EXTRACT-06 | Orphan node prevention via group_id-scoped episode tombstoning before re-ingestion | `remove_episode(episode_uuid)` cleans up edges/nodes only referenced by that episode; track episode UUIDs in segment metadata; diff engine identifies removed chunks for cleanup |
| DIFF-01 | Diff engine detects entity-level changes on re-ingestion (added/modified/removed entities) | Compare old vs new segment content_hash sets; AddEpisodeResults returns extracted nodes/edges; compare against previous extraction results |
| DIFF-02 | Superseded edges have t_invalid set via Graphiti conflict resolution | Graphiti's `add_episode()` automatically detects contradictions via LLM invalidation prompt, sets `invalid_at` on superseded edges |
| DIFF-03 | Entity-level diff summaries written to SyncLog.details as structured JSON | SyncLog.details is JSONB column (already exists); diff summary computed from AddEpisodeResults comparison |

</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| graphiti-core[anthropic] | 0.28.1 (installed) | Episode ingestion, entity extraction, temporal invalidation | Already installed in Phase 6; only mature bi-temporal knowledge graph engine for Neo4j |
| SQLAlchemy + Alembic | (already installed) | Database migration for graph_synced column | Existing migration pattern in project |
| structlog | (already installed) | Structured logging for graph extraction steps | Project standard |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| graphiti_core.utils.maintenance.graph_data_operations | (from graphiti-core) | `clear_data()` utility for group-scoped cleanup | Emergency full-document graph reset; not for normal re-ingestion |
| graphiti_core.nodes | (from graphiti-core) | `EpisodeType` enum, `EpisodicNode`, `EntityNode` types | Type annotations and result handling |
| graphiti_core.edges | (from graphiti-core) | `EntityEdge` type with temporal fields | Reading extraction results for diff summaries |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Per-chunk `add_episode()` | Per-document `add_episode()` with full doc text | Coarser temporal granularity, worse extraction quality on large documents |
| `remove_episode()` per changed chunk | `clear_data(driver, group_ids=[doc_group_id])` for full doc cleanup | Simpler but destroys unchanged chunk data, loses cross-document entity references from that doc |
| Custom diff engine | No diff (always re-extract all chunks) | Simpler but wastes LLM calls on unchanged content; user explicitly wants chunk-level diff |

**No new installation needed** -- all libraries are already in the project from Phase 6.

## Architecture Patterns

### Recommended Project Structure

```
src/pam/
├── graph/
│   ├── service.py           # MODIFIED: Add add_episode_for_chunk(), remove_episode_for_chunk() helper methods
│   ├── entity_types.py      # UNCHANGED: 7 entity types already defined
│   └── extraction.py        # NEW: Graph extraction orchestrator (extract_graph_for_document)
├── ingestion/
│   ├── pipeline.py          # MODIFIED: Add graph extraction step after ES write
│   ├── diff_engine.py       # NEW: Chunk-level diff logic + entity-level diff summary
│   ├── task_manager.py      # MODIFIED: Pass graph_service to pipeline
│   └── stores/
│       └── postgres_store.py # MODIFIED: Add graph_synced query/update methods
├── api/
│   ├── routes/
│   │   ├── ingest.py        # MODIFIED: Add POST /ingest/sync-graph endpoint, ?skip_graph param
│   │   └── graph.py         # UNCHANGED
│   └── deps.py              # UNCHANGED
├── common/
│   └── models.py            # MODIFIED: Add graph_synced, graph_sync_retries to Document model
└── alembic/
    └── versions/
        └── 006_add_graph_synced.py  # NEW: Alembic migration
```

### Pattern 1: Non-Blocking Graph Extraction in Pipeline

**What:** After PG commit and ES write succeed, attempt graph extraction wrapped in try/except. Failures set `graph_synced=False` but never roll back PG/ES data.
**When to use:** Every document ingestion.

```python
# In pipeline.py ingest_document() -- after ES write (step 10)

# 11. Graph extraction (non-blocking)
if self.graph_service and not skip_graph:
    try:
        extraction_result = await extract_graph_for_document(
            graph_service=self.graph_service,
            doc_id=doc_id,
            segments=segments,
            chunks=chunks,
            document_title=raw_doc.title,
            reference_time=raw_doc.modified_at or datetime.now(UTC),
            old_segments=old_segments,  # For diff engine
        )
        await pg_store.set_graph_synced(doc_id, True)
        # Log diff summary
        await pg_store.log_sync(doc_id, "graph_synced", count, details=extraction_result.diff_summary)
    except Exception as graph_err:
        logger.error("pipeline_graph_extraction_failed", source_id=source_id, error=str(graph_err))
        await pg_store.set_graph_synced(doc_id, False)
        # Rollback any partial graph writes for this document
        try:
            await rollback_graph_for_document(self.graph_service, doc_id, segments)
        except Exception:
            logger.error("pipeline_graph_rollback_failed", source_id=source_id)
```

### Pattern 2: Chunk-Level Diff Engine

**What:** Compare old segment content_hash values against new ones to classify chunks as added/modified/removed. Only re-extract changed/added chunks through Graphiti.
**When to use:** Every re-ingestion (when `existing_doc` is not None).

```python
# In diff_engine.py

@dataclass
class ChunkDiff:
    added: list[KnowledgeSegment]      # New chunks not in old set
    modified: list[KnowledgeSegment]   # Changed chunks (same position, different hash)
    removed: list[Segment]             # Old chunks not in new set
    unchanged: list[KnowledgeSegment]  # Same content_hash -- skip graph extraction

def compute_chunk_diff(
    old_segments: list[Segment],
    new_segments: list[KnowledgeSegment],
) -> ChunkDiff:
    old_hashes = {seg.content_hash for seg in old_segments}
    new_hashes = {seg.content_hash for seg in new_segments}

    added = [s for s in new_segments if s.content_hash not in old_hashes]
    removed = [s for s in old_segments if s.content_hash not in new_hashes]
    unchanged = [s for s in new_segments if s.content_hash in old_hashes]

    return ChunkDiff(added=added, modified=[], removed=removed, unchanged=unchanged)
```

### Pattern 3: Episode UUID Tracking in Segment Metadata

**What:** Store the Graphiti episode UUID in each segment's `metadata_` JSONB field. This enables surgical cleanup during re-ingestion (remove only the episodes for changed/removed chunks).
**When to use:** After every successful `add_episode()` call.

```python
# After add_episode returns
result: AddEpisodeResults = await graph_service.client.add_episode(...)
episode_uuid = result.episode.uuid

# Store in segment metadata for later cleanup
segment.metadata_["graph_episode_uuid"] = episode_uuid
segment.metadata_["graph_entity_count"] = len(result.nodes)
segment.metadata_["graph_edge_count"] = len(result.edges)
```

### Pattern 4: Document-Scoped group_id

**What:** Use `group_id=f"doc-{doc_id}"` for all episodes from the same document. This scopes graph operations and enables document-level cleanup.
**When to use:** Every `add_episode()` call.

```python
await graph_service.client.add_episode(
    name=f"chunk-{segment.id}",
    episode_body=segment.content,
    source=EpisodeType.text,
    source_description=f"Document: {document_title} | Segment: {segment.position}",
    reference_time=document_modified_at,  # Bi-temporal: valid_time from document
    group_id=f"doc-{doc_id}",             # Scoped to document
    entity_types=ENTITY_TYPES,            # Phase 6 entity taxonomy
)
```

### Pattern 5: Graph Rollback on Partial Failure

**What:** If graph extraction fails mid-document (e.g., chunk 5 of 10 fails), remove all episodes that were successfully added for this document in this ingestion run. This prevents partial graph state.
**When to use:** On any exception during the graph extraction loop.

```python
async def rollback_graph_for_document(
    graph_service: GraphitiService,
    doc_id: uuid.UUID,
    segments_with_episodes: list[KnowledgeSegment],
) -> None:
    """Remove all episodes added during this ingestion run for the given document."""
    for seg in segments_with_episodes:
        episode_uuid = seg.metadata.get("graph_episode_uuid")
        if episode_uuid:
            try:
                await graph_service.client.remove_episode(episode_uuid)
            except Exception:
                logger.warning("rollback_episode_failed", episode_uuid=episode_uuid)
```

### Pattern 6: Sync Recovery Endpoint

**What:** `POST /ingest/sync-graph` queries documents with `graph_synced=False`, runs graph extraction for each, and updates the flag.
**When to use:** Operational recovery after Neo4j outage.

```python
@router.post("/ingest/sync-graph")
async def sync_graph(
    limit: int | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
    graph_service: GraphitiService = Depends(get_graph_service),
):
    # Query unsynced documents
    stmt = select(Document).where(
        Document.graph_synced == False,
        Document.graph_sync_retries < MAX_RETRIES,
    )
    if limit:
        stmt = stmt.limit(limit)

    results = {"synced": [], "failed": [], "remaining": 0}
    # Process each document...
```

### Anti-Patterns to Avoid

- **Don't use `add_episode_bulk()`.** Per project requirements, it skips temporal invalidation. Always use `add_episode()` one chunk at a time.
- **Don't use `clear_data(group_ids=[...])` for normal re-ingestion.** It destroys all graph data for the document including cross-document entity references. Use surgical `remove_episode()` per changed chunk instead.
- **Don't run graph extraction before PG commit.** The pipeline must commit PG first (PG is authoritative). Graph extraction comes after, isolated by try/except.
- **Don't store episode UUIDs only in Neo4j.** They must be in PG segment metadata for reliable cleanup even when Neo4j is unreachable.
- **Don't block the ingestion response on graph extraction.** While extraction runs inline (not background), the response should still include partial results if graph fails. The `graph_synced` flag communicates the outcome.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Entity extraction from text | Custom NER pipeline | Graphiti `add_episode()` with `entity_types` param | Graphiti handles prompt engineering, entity resolution, deduplication |
| Temporal edge invalidation | Manual Cypher to set `invalid_at` | Graphiti's built-in conflict detection in `add_episode()` | LLM-driven contradiction detection with proper temporal semantics |
| Entity resolution / dedup | Custom name-matching logic | Graphiti's 3-tier resolution (embedding + MinHash + LLM) | Handles synonyms, abbreviations, ambiguous names |
| Episode cleanup on re-ingestion | Manual Cypher DELETE queries | `remove_episode(episode_uuid)` | Correctly handles shared entities referenced by other episodes |
| Content hash diffing | Full text comparison | SHA-256 `content_hash` (already computed in chunker) | Exact match detection with O(1) set lookups |

**Key insight:** Graphiti handles the hard graph operations (extraction, resolution, invalidation). The custom code for this phase is the diff engine (comparing chunk hashes) and the orchestration layer (when to call add_episode vs remove_episode, tracking results, fault isolation).

## Common Pitfalls

### Pitfall 1: Partial Graph State on Mid-Document Failure

**What goes wrong:** If chunk 5/10 fails during `add_episode()`, chunks 1-4 have episodes in Neo4j but chunks 5-10 don't. The document has inconsistent graph representation.
**Why it happens:** Each `add_episode()` call is independent -- there's no transaction spanning multiple episodes.
**How to avoid:** Track which episodes were successfully added during this ingestion run. On failure, call `remove_episode()` for each successfully-added episode to roll back to the pre-ingestion state. Set `graph_synced=False` for retry.
**Warning signs:** Entity counts that don't match expected extraction from a full document.

### Pitfall 2: LLM Cost Explosion on Re-ingestion

**What goes wrong:** Re-ingesting a document with minor changes sends all 10 chunks through Graphiti's LLM extraction, costing the same as initial ingestion.
**Why it happens:** Without chunk-level diffing, every re-ingestion is a full extraction.
**How to avoid:** Compare old segment `content_hash` values against new ones. Only send changed/added chunks through `add_episode()`. Remove episodes for deleted chunks via `remove_episode()`.
**Warning signs:** LLM API costs linearly proportional to total document volume rather than change volume.

### Pitfall 3: Orphaned Entities After Chunk Removal

**What goes wrong:** Removing a chunk's episode via `remove_episode()` doesn't remove entities that are referenced by other episodes from other documents.
**Why it happens:** `remove_episode()` only deletes entities exclusively mentioned by that episode. Cross-document entities survive.
**How to avoid:** This is actually correct behavior. Distinguish in the diff summary between "removed from this document" (entity still exists, referenced by other docs) vs "deleted from graph" (entity had no other references). Check `remove_episode()` return or query entity reference count.
**Warning signs:** Diff summary showing "removed" entities that still appear in graph queries.

### Pitfall 4: `modified_at` Not Set on Markdown Files

**What goes wrong:** The `reference_time` passed to `add_episode()` defaults to `datetime.now(UTC)` because `MarkdownConnector.list_documents()` sets `modified_at=None`.
**Why it happens:** The connector was written before graph features existed. `modified_at` is not populated from file system `stat.st_mtime`.
**How to avoid:** Update `MarkdownConnector` to populate `modified_at` from `Path.stat().st_mtime`. Pass this through `RawDocument` to the pipeline. Use it as `reference_time` for `add_episode()`.
**Warning signs:** All graph edges having `valid_at` set to ingestion time rather than document modification time.

### Pitfall 5: `group_id` Character Restrictions

**What goes wrong:** Graphiti `group_id` validation rejects characters outside ASCII alphanumeric, dashes, and underscores.
**Why it happens:** UUID strings contain hyphens which are allowed, but other special characters in source_id paths would fail.
**How to avoid:** Use `f"doc-{doc_id}"` format where `doc_id` is a UUID (hyphens are valid). Never use raw file paths as group_id.
**Warning signs:** `ValueError` from Graphiti during `add_episode()` mentioning group_id validation.

### Pitfall 6: Sync Recovery Infinite Retry Loop

**What goes wrong:** A document permanently fails graph extraction (e.g., content triggers LLM error), and the sync-graph endpoint retries it on every call.
**Why it happens:** No retry limit -- the endpoint just queries `graph_synced=False` each time.
**How to avoid:** Add `graph_sync_retries` counter column to Document. Increment on each failed retry. After reaching max retries (recommendation: 3), set a `graph_sync_failed=True` flag and exclude from future retry queries.
**Warning signs:** The same documents appearing in every sync-graph response.

### Pitfall 7: `add_episode()` Blocking Pipeline Too Long

**What goes wrong:** Graph extraction for 10 chunks takes 30-60 seconds (each `add_episode()` involves LLM calls for extraction + entity resolution + invalidation), making the ingestion response very slow.
**Why it happens:** Each `add_episode()` call invokes the LLM for entity extraction, makes embedding calls, and runs entity resolution queries.
**How to avoid:** This is a known tradeoff of inline extraction. The progress callback (`extracting entities 3/10 chunks`) keeps the user informed. The `?skip_graph=true` parameter allows opting out for bulk imports. Future optimization: async background extraction (out of scope for this phase).
**Warning signs:** Ingestion response times > 30 seconds per document.

## Code Examples

### Graphiti add_episode() with Full Parameters

```python
# Source: Graphiti source code (graphiti_core/graphiti.py) - verified from GitHub
from datetime import datetime, UTC
from graphiti_core.nodes import EpisodeType
from pam.graph.entity_types import ENTITY_TYPES

result = await graph_service.client.add_episode(
    name=f"chunk-{segment_id}",
    episode_body=chunk_text,
    source=EpisodeType.text,
    source_description=f"Document: {doc_title} | Source: {source_id} | Chunk: {position}",
    reference_time=document_modified_at or datetime.now(UTC),
    group_id=f"doc-{doc_id}",
    entity_types=ENTITY_TYPES,
    # Optional: custom extraction instructions for domain-specific guidance
    # custom_extraction_instructions="Focus on organizational structure and technology relationships.",
)

# Result structure
episode_node = result.episode        # EpisodicNode
extracted_nodes = result.nodes       # list[EntityNode]
extracted_edges = result.edges       # list[EntityEdge]
```

### AddEpisodeResults Processing for Diff Summary

```python
# Source: Graphiti source code - AddEpisodeResults BaseModel
from graphiti_core.edges import EntityEdge

def build_diff_summary(
    added_results: list[AddEpisodeResults],
    removed_episode_uuids: list[str],
    old_entity_names: set[str],
) -> dict:
    """Build structured diff summary for SyncLog.details."""
    new_entities = []
    for result in added_results:
        for node in result.nodes:
            new_entities.append({
                "name": node.name,
                "type": next((l for l in node.labels if l != "Entity"), "Unknown"),
                "uuid": str(node.uuid),
            })

    new_entity_names = {e["name"] for e in new_entities}

    return {
        "added": [e for e in new_entities if e["name"] not in old_entity_names],
        "modified": [],  # Detected via edge invalidation in Graphiti
        "removed_from_document": list(old_entity_names - new_entity_names),
        "episodes_added": len(added_results),
        "episodes_removed": len(removed_episode_uuids),
    }
```

### EntityEdge Temporal Fields

```python
# Source: Graphiti source code (graphiti_core/edges.py)
# EntityEdge fields relevant to bi-temporal tracking:

class EntityEdge:
    uuid: str
    name: str                    # Relation name
    fact: str                    # Fact text representing the relationship
    fact_embedding: list[float]  # Embedding of the fact
    episodes: list[str]          # Episode UUIDs that reference this edge

    # Bi-temporal timestamps
    created_at: datetime         # System time: when ingested into graph
    expired_at: datetime | None  # System time: when superseded in system
    valid_at: datetime | None    # Event time: when fact became true
    invalid_at: datetime | None  # Event time: when fact stopped being true

    # Provenance
    source_node_uuid: str
    target_node_uuid: str
    group_id: str
```

### Alembic Migration for graph_synced Column

```python
# Source: Existing migration pattern in project (004_add_extracted_entities.py)

"""Add graph_synced and graph_sync_retries to documents table.

Revision ID: 006
Revises: 005
"""

def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("graph_synced", sa.Boolean, server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "documents",
        sa.Column("graph_sync_retries", sa.Integer, server_default=sa.text("0"), nullable=False),
    )
    op.create_index("ix_documents_graph_synced", "documents", ["graph_synced"])

def downgrade() -> None:
    op.drop_index("ix_documents_graph_synced")
    op.drop_column("documents", "graph_sync_retries")
    op.drop_column("documents", "graph_synced")
```

### Chunk-Level Diff with Episode Cleanup

```python
# Source: Application pattern built on researched Graphiti API

async def diff_and_extract(
    graph_service: GraphitiService,
    doc_id: uuid.UUID,
    old_segments: list[Segment],
    new_segments: list[KnowledgeSegment],
    document_title: str,
    reference_time: datetime,
) -> dict:
    """Diff old vs new chunks, remove stale episodes, extract new/changed chunks."""
    old_hashes = {seg.content_hash: seg for seg in old_segments}
    new_hashes = {seg.content_hash: seg for seg in new_segments}

    # Identify changes
    removed_hashes = set(old_hashes.keys()) - set(new_hashes.keys())
    added_hashes = set(new_hashes.keys()) - set(old_hashes.keys())

    # Remove episodes for deleted/changed chunks
    removed_uuids = []
    for h in removed_hashes:
        seg = old_hashes[h]
        episode_uuid = seg.metadata_.get("graph_episode_uuid")
        if episode_uuid:
            await graph_service.client.remove_episode(episode_uuid)
            removed_uuids.append(episode_uuid)

    # Extract new/changed chunks
    results = []
    for h in added_hashes:
        seg = new_hashes[h]
        result = await graph_service.client.add_episode(
            name=f"chunk-{seg.id}",
            episode_body=seg.content,
            source=EpisodeType.text,
            source_description=f"Document: {document_title}",
            reference_time=reference_time,
            group_id=f"doc-{doc_id}",
            entity_types=ENTITY_TYPES,
        )
        seg.metadata["graph_episode_uuid"] = str(result.episode.uuid)
        results.append(result)

    return {"added": len(added_hashes), "removed": len(removed_hashes), "results": results}
```

## Chunk Size Considerations for Graphiti Episodes

The user requested research on optimal chunk sizing for Graphiti extraction quality. Based on research:

**What we know:**
- Graphiti uses LLM extraction with context from the "last n episodes" (default n=4 in Zep's implementation)
- The LLM receives the episode body plus context from recent episodes for entity recognition
- Graphiti's default max token limit is 8K for standard clients, 16K for local models
- The project's current `CHUNK_SIZE_TOKENS=512` was optimized for embedding/retrieval, not extraction

**Recommendation (MEDIUM confidence):**
- **Keep the existing 512-token chunks for PG/ES storage** (optimized for retrieval)
- **Consider a separate, larger chunking for graph extraction** if extraction quality is poor -- around 1000-2000 tokens per episode would give the LLM more context for entity extraction
- **Start with 512 tokens and measure** -- if entities are being split across chunks (e.g., "Team Alpha" mentioned in one chunk, its lead "Alice" in the next), increase the episode body by concatenating adjacent chunks
- **The `source_description` field helps** -- include document title and section path so the LLM has context even with small chunks
- This is an empirical question best answered during implementation with real documents

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `add_episode_bulk()` for batch ingestion | `add_episode()` per chunk for temporal integrity | Graphiti design principle | Must use `add_episode()` to get edge invalidation |
| Neo4j transactions for atomic multi-episode writes | Per-episode writes with manual rollback | Graphiti API constraint | No multi-episode transaction; must track and rollback manually |
| Full document re-extraction on any change | Chunk-level diff with selective re-extraction | Custom for this project | Saves LLM costs proportional to change size |
| `remove_episode()` then `add_episode()` | Can also use `add_episode(uuid=existing_uuid)` for update | Graphiti v0.28 | Passing existing UUID treats it as update; alternative to delete+recreate |

**Important discovery:** The `add_episode()` method accepts a `uuid` parameter. Passing an existing episode UUID makes it an update operation rather than requiring delete+create. This could simplify re-ingestion for modified chunks -- update the episode in place rather than removing and re-adding. However, the exact behavior of updating vs. creating new episodes needs validation during implementation.

**Deprecated/outdated:**
- `add_episode_bulk()`: Still exists but project explicitly excludes its use (skips temporal invalidation)
- `clear_data()` for re-ingestion: Too destructive; surgical `remove_episode()` is preferred

## Open Questions

1. **`add_episode(uuid=existing_uuid)` behavior for updates**
   - What we know: The parameter accepts an existing episode UUID. DeepWiki describes it as "update."
   - What's unclear: Does it re-run full extraction and invalidation? Does it compare old vs new episode body? Or does it simply overwrite?
   - Recommendation: During implementation, test with a modified chunk to see if passing the existing UUID produces correct edge invalidation. If it does, this is simpler than remove+add. If unclear, fall back to remove+add pattern. **Confidence: LOW** -- this needs empirical testing.

2. **Cross-document entity provenance tracking**
   - What we know: The user wants to answer "where did this fact come from?" Graphiti's `EntityEdge.episodes` field stores episode UUIDs. Episode names contain document info.
   - What's unclear: How to efficiently query "all documents that mention entity X" without iterating all episodes. Graphiti's `search()` returns edges, not episode provenance chains.
   - Recommendation: Store `document_id` in each episode's `source_description` field (e.g., `"Document: {title} | doc_id: {doc_id}"`). For provenance queries, use a Cypher query through Graphiti's driver: `MATCH (e:Episodic)-[:MENTIONS]->(n:Entity {name: $name}) RETURN e.source_description`. This is a Phase 8 concern but the data must be stored correctly in Phase 7.

3. **Full before/after detail in diff summaries**
   - What we know: User wants `{modified: [{name: "Team Alpha", field: "lead", old: "Alice", new: "Bob"}]}`.
   - What's unclear: Graphiti doesn't expose "what changed" in a structured way. It returns `AddEpisodeResults` with new nodes/edges, and separately invalidates old edges. The old vs new comparison must be built manually.
   - Recommendation: Before re-extraction, query existing entities for the document's group_id via Cypher. After extraction, compare the new entities against the old set. Build the diff from the comparison. This adds a Cypher query per re-ingestion but enables the full before/after detail. **Confidence: MEDIUM** -- the pattern is sound but the Cypher query needs crafting.

4. **Graph rollback semantics with remove_episode()**
   - What we know: `remove_episode()` deletes edges created by that episode and nodes only referenced by it.
   - What's unclear: If entity X was created by episode A (chunk 1) and also mentioned by episode B (chunk 2), and we rollback episode A, entity X survives because episode B still references it. Is this the desired behavior for a mid-document rollback?
   - Recommendation: Yes, this is correct. During rollback, we only want to undo the graph changes from the failed ingestion run. Entities shared with previously-successful chunks from the same document (or other documents) should survive. The next sync-graph retry will re-add the failed chunks.

## Sources

### Primary (HIGH confidence)
- [Graphiti graphiti.py source code](https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py) -- `add_episode()` full signature, `remove_episode()`, `search()`, `retrieve_episodes()`
- [Graphiti edges.py source code](https://github.com/getzep/graphiti/blob/main/graphiti_core/edges.py) -- `EntityEdge` temporal fields (created_at, expired_at, valid_at, invalid_at)
- [Graphiti nodes.py source code](https://github.com/getzep/graphiti/blob/main/graphiti_core/nodes.py) -- `EpisodicNode`, `EntityNode`, `EpisodeType` enum
- [Graphiti graph_data_operations.py](https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/maintenance/graph_data_operations.py) -- `clear_data()` utility with group_id filtering
- [Zep Documentation - Adding Episodes](https://help.getzep.com/graphiti/core-concepts/adding-episodes) -- Episode types, parameters
- [Zep Documentation - Custom Entity Types](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types) -- entity_types parameter behavior
- [Zep Documentation - Graph Namespacing](https://help.getzep.com/graphiti/core-concepts/graph-namespacing) -- group_id isolation semantics

### Secondary (MEDIUM confidence)
- [DeepWiki - Graphiti Core Client](https://deepwiki.com/getzep/graphiti/4.1-graphiti-core) -- add_episode parameter descriptions, AddEpisodeResults structure, group_id partitioning
- [Zep Temporal Knowledge Graph Paper (arXiv)](https://arxiv.org/html/2501.13956v1) -- Bi-temporal model formalization, entity resolution algorithm (embedding + MinHash + LLM), edge invalidation semantics
- [Zep Blog - Beyond Static Knowledge Graphs](https://blog.getzep.com/beyond-static-knowledge-graphs/) -- Edge invalidation process, non-chronological re-ingestion, date extraction pipeline
- [Neo4j Blog - Graphiti Knowledge Graph Memory](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) -- Bi-temporal overview, edge validity intervals

### Tertiary (LOW confidence)
- Chunk size recommendations for Graphiti extraction quality -- no authoritative source found; recommendation is empirical (start with 512, adjust based on results)
- `add_episode(uuid=existing_uuid)` update behavior -- documented in DeepWiki but not verified in official docs or source code comments

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All libraries already installed; Graphiti API signatures verified from source code
- Architecture: HIGH -- Existing pipeline structure is clear; extension points well-defined; Graphiti API matches requirements
- Pitfalls: HIGH -- Temporal invalidation, partial failure, and episode management are well-documented in sources
- Diff engine: MEDIUM -- Chunk-level hash comparison is straightforward; entity-level diff detail requires Cypher queries that need empirical validation
- Chunk sizing: LOW -- No authoritative guidance exists; empirical testing required during implementation

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (30 days -- Graphiti 0.28.1 is current stable; API unlikely to change in patch releases)
