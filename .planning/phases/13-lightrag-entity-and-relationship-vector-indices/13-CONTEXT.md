# Phase 13: Entity & Relationship Vector Indices - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Entity descriptions and relationship descriptions are independently embedded and stored in Elasticsearch as vector indices (`pam_entities`, `pam_relationships`) — enabling semantic entity discovery ("find teams working on deployment") and relationship discovery ("what connects infrastructure to reliability") without knowing exact entity names. During ingestion, entity/relationship embeddings are created alongside existing Neo4j writes. `smart_search` uses these VDB indices for low-level (entity) and high-level (relationship) keyword matching. This follows LightRAG's 3-VDB pattern.

</domain>

<decisions>
## Implementation Decisions

### Embedding content format
- Entity embedding text: `"{name}\n{description}"` (LightRAG format)
- Relationship embedding text: `"{keywords}\t{src_entity}\n{tgt_entity}\n{description}"` (LightRAG format)
- entity_type stored as ES metadata field for filtering, NOT included in embedding text
- Embed all entities/relationships regardless of description length — even short descriptions have semantic value for name-based discovery

### Embedding model
- Use the same embedder configured for chunks (text-embedding-3-small, 1536-dim)
- Reuse existing BaseEmbedder infrastructure — no separate model config needed

### Index lifecycle & sync
- **Entity upsert:** Use entity name as ES document ID — re-ingestion overwrites with updated description + re-embedded vector
- **Relationship upsert:** ES document ID = `"{sorted_src}::{rel_type}::{sorted_tgt}"` — allows multiple relationships between the same entity pair (e.g., A MANAGES B and A MENTORS B)
- **Index creation:** Auto-create with mapping on first ingestion if index doesn't exist (same pattern as `pam_segments`)
- **Orphan cleanup:** Track `source_ids` per entity/relationship. When all source documents are removed, delete the orphaned entity/relationship from ES

### Search integration in smart_search
- Entity/relationship VDB results returned as **distinct result types** (e.g., `source='entity_vdb'`, `source='relationship_vdb'`) — agent sees them differently from document chunks
- All 4 searches (ES segments, Graphiti, entity VDB, relationship VDB) run **concurrently** via asyncio.gather
- Default: top 5 entities and top 5 relationships per search
- Result merge strategy across 4 sources: Claude's discretion

### Embedding cost management
- Entity embeddings batched together, relationship embeddings batched together — **separate** from chunk embedding batches
- **Skip re-embedding** unchanged descriptions: hash embedding text content, compare against existing ES record hash, skip API call if unchanged
- No toggle to disable entity/relationship embedding — always runs when graph extraction is enabled
- Log embedding count and latency via structlog (consistent with existing ingestion logging)

### Claude's Discretion
- Merge/ranking strategy for 4-way search results in smart_search
- Exact ES index mapping details (analyzer, similarity function)
- Batch size for embedding API calls
- Hash algorithm for change detection (SHA-256 consistent with existing content hashing)

</decisions>

<specifics>
## Specific Ideas

- Follow LightRAG's proven embedding text formats exactly — don't reinvent
- Relationship key includes rel_type to support multiple relationship types between the same entity pair
- Orphan cleanup ensures index doesn't accumulate stale entities over time

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 13-lightrag-entity-and-relationship-vector-indices*
*Context gathered: 2026-02-24*
