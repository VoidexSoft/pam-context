# Phase 7: Ingestion Pipeline Extension + Diff Engine - Context

**Gathered:** 2026-02-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Extend the document ingestion pipeline to extract knowledge graph entities and relationships into Neo4j via Graphiti. Every ingested document produces entity nodes and relationship edges with bi-temporal timestamps. Graph failures never corrupt PG/ES data. Re-ingestion detects entity-level changes via a diff engine. A sync recovery endpoint retries failed graph extractions. This phase creates queryable graph knowledge — user-facing graph queries and UI are separate phases (8 and 9).

</domain>

<decisions>
## Implementation Decisions

### Entity extraction flow
- One Graphiti episode per chunk (not per document)
- Chunk size should be optimized for extraction quality — researcher should investigate optimal chunk sizing for Graphiti episodes (web research requested)
- Constrain extraction to our Phase 6 entity type taxonomy upfront — pass entity types to Graphiti so it only extracts matching entities
- Use Graphiti's built-in entity resolution for cross-document deduplication (auto-merge by name)
- Track document provenance on each entity/edge — store source document IDs so we can answer "where did this fact come from?"

### Graph write timing
- Graph extraction runs inline during ingestion but is non-blocking — failures are caught and don't prevent PG/ES commit
- On graph failure mid-document, roll back all graph writes for that document (no partial graph state)
- Mark failed documents with `graph_synced=False` in PostgreSQL for later retry
- Graph extraction progress is visible in the ingestion response (e.g., "extracting entities 3/10 chunks")
- Support `?skip_graph=true` query param to opt out of graph extraction per ingestion call (useful for bulk imports)

### Diff summary content
- Full before/after detail in diffs — e.g., `{modified: [{name: "Team Alpha", field: "lead", old: "Alice", new: "Bob"}]}`
- Distinguish between "removed from this document" vs "deleted from graph entirely" (orphaned node with no remaining sources)
- Chunk-level diff first — compare old vs new chunk text, only re-extract changed chunks through Graphiti (saves LLM calls on unchanged content)
- Diff summary both returned in the ingestion API response AND persisted in SyncLog.details

### Sync recovery behavior
- `POST /ingest/sync-graph` accepts `?limit=N` for batch size control (default to all if no limit)
- Per-document results in response: `{synced: [{doc_id, status, entities_added}], failed: [{doc_id, error}], remaining: N}`
- Max retry count before marking a document as permanently failed (`graph_sync_failed`) — prevents infinite retry loops
- "Sync Graph" button in admin dashboard UI that calls the endpoint — not API-only

### Claude's Discretion
- Exact max retry count for permanent failure marking
- Default batch size for sync-graph
- How to handle the graph rollback on partial failure (Graphiti transaction semantics vs manual cleanup)
- Loading/progress UI for the sync button in admin dashboard
- Exact format of the progress field in ingestion response

</decisions>

<specifics>
## Specific Ideas

- User wants chunk-level diffing before extraction to save on LLM costs — compare text first, only send changed chunks through Graphiti
- Provenance tracking is important — entities should know which documents contributed to them
- Admin dashboard should have a visible "Sync Graph" button for operational recovery
- Research needed: optimal chunk sizing for Graphiti episode extraction quality (web research)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 07-ingestion-pipeline-extension-diff-engine*
*Context gathered: 2026-02-20*
