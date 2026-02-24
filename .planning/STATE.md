# Project State: PAM Context

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-19)

**Core value:** Users can ask natural-language questions about their business documents and get accurate, cited answers
**Current focus:** v3.0 LightRAG Smart Retrieval — Phase 15

## Current Position

Phase: 15 of 15 (LightRAG Retrieval Mode Router)
Plan: 0 of ? complete
Status: In Progress
Last activity: 2026-02-25 — Completed 14-02-PLAN.md (Smart search context assembly integration)

Progress: [##############################] 100% (30/30 plans across all milestones)

## Milestone Progress

| Milestone | Phases | Plans | Status |
|-----------|--------|-------|--------|
| v1 Code Quality Cleanup | 5/5 | 10/10 | Shipped 2026-02-19 |
| v2.0 Knowledge Graph | 6/6 | 14/14 | Complete |
| v3.0 LightRAG Smart Retrieval | 3/4 | 6/? | In Progress |

## Performance Metrics

**Velocity (v1):**
- Total plans completed: 10
- Total execution time: ~3 days
- Average: ~3 plans/day

**Phase 6 (v2.0):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 06-01 | 4min | 2 | 8 |
| 06-02 | 5min | 2 | 9 |
| 06-03 | 3min | 2 | 4 |

**Phase 7 (v2.0):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 07-01 | 4min | 2 | 6 |
| 07-02 | 7min | 2 | 5 |

**Phase 8 (v2.0):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 08-01 | 4min | 2 | 4 |
| 08-02 | 3min | 2 | 1 |

**Phase 9 (v2.0):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 09-01 | 2min | 2 | 2 |
| 09-02 | 4min | 3 | 8 |
| 09-03 | 4min | 2 | 4 |

**Phase 10 (Gap Closure):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 10-01 | 5min | 2 | 9 |

**Phase 11 (Gap Closure):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 11-01 | 8min | 2 | 4 |
| 11-02 | 4min | 2 | 14 |

**Phase 12 (v3.0 LightRAG):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 12-01 | 2min | 2 | 3 |
| 12-02 | 5min | 2 | 2 |

**Phase 13 (v3.0 LightRAG):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 13-01 | 4min | 2 | 7 |
| 13-02 | 5min | 2 | 4 |

**Phase 14 (v3.0 LightRAG):**

| Plan | Duration | Tasks | Files |
|------|----------|-------|-------|
| 14-01 | 5min | 2 | 4 |
| 14-02 | 3min | 2 | 3 |

## Accumulated Context

**Decisions:** See PROJECT.md Key Decisions table (11 entries)
- Phase 6-01: graphiti-core 0.28.1 with async classmethod factory pattern for GraphitiService
- Phase 6-01: Entity type fields all Optional with Field(None, description=...) per Graphiti best-effort extraction
- Phase 6-03: Used --legacy-peer-deps for NVL (peer dep on react 18.0.0 exact)
- Phase 6-03: Feature flag VITE_GRAPH_ENABLED for conditional nav rendering
- Phase 6-03: /graph route registered unconditionally for dev convenience
- Phase 6-02: GraphitiService creation wrapped in try/except for graceful degradation
- Phase 6-02: Graph status endpoint returns 200 with status field rather than error HTTP codes
- Phase 7-01: get_episode() for old entity info before removal is best-effort with try/except fallback
- Phase 7-01: Clear segment metadata on rollback regardless of remove_episode success to prevent stale references
- Phase 7-02: Graph extraction is non-blocking: failure sets graph_synced=False without affecting PG/ES data
- Phase 7-02: Old segments retrieved BEFORE save_segments() for chunk-level diff on re-ingestion
- Phase 7-02: MAX_GRAPH_SYNC_RETRIES=3 as constant in ingest routes
- Phase 8-01: getattr for optional graph_service in deps.py (not Depends) for graceful Neo4j absence
- Phase 8-01: Source citations embedded in result text (not Citation objects) for graph tools
- Phase 8-01: Direct Cypher for get_entity_history, Graphiti search() for search_knowledge_graph
- Phase 8-01: re.escape on entity names in Cypher regex to prevent injection
- Phase 8-02: Entity type validated against ENTITY_TYPES taxonomy dict to prevent Cypher injection in label clause
- Phase 8-02: Separate EntityListResponse model instead of reusing PaginatedResponse (different cursor semantics)
- Phase 8-02: LIMIT 21 in neighborhood query to detect edge overflow beyond 20-edge cap
- Phase 9-01: Entity history returns ALL edges including invalidated for temporal timeline rendering
- Phase 9-01: SyncLog endpoint queries PostgreSQL via AsyncSession (SyncLog is PG model, not Neo4j)
- Phase 9-01: Mixed Neo4j + PostgreSQL endpoints in same router with appropriate DI
- Phase 9-02: Nav link updated to /graph/explore as primary graph experience
- Phase 9-02: Canvas renderer (not WebGL) required for edge label captions
- Phase 9-02: Deep-link via ?entity= URL parameter triggers focusEntity on mount
- Phase 9-02: Disabled state nav text changed to "Graph (Coming Soon)" for clarity
- Phase 9-03: IngestionDiff passes both color map and filter mode via single callback for atomic state updates
- Phase 9-03: EntitySidebar gains footer prop (ReactNode) for extensible bottom-pinned content
- Phase 9-03: Chat entity links use button element for accessibility with navigate() onClick
- Phase 9-03: VITE_GRAPH_ENABLED checked at module level for chat link gating
- Phase 10-01: Nullable modified_at with no backfill -- existing documents get NULL triggering datetime.now(UTC) fallback
- Phase 10-01: Direct raw_doc.modified_at access replaces getattr fallback for explicit data flow
- Phase 10-01: Cascading fallback in sync-graph: doc.modified_at -> doc.last_synced_at -> datetime.now(UTC)
- Phase 11-01: graph_status returns degraded 200 (not 503) when graph_service is None to preserve document counts for frontend empty states
- Phase 11-01: Data endpoints (neighborhood, entities, history) return 503 with structured JSON when graph_service is None
- Phase 11-01: Two empty state branches: documentCount===0 shows 'No documents ingested' with ingest link; documentCount>0 with entityCount===0 shows 'Graph indexing in progress'
- Phase 11-02: Used `from err` (not `from None`) to preserve exception chain context for B904 fix
- Phase 11-02: 2-space YAML indentation for requirements_completed sequence items in SUMMARY frontmatter
- Phase 12-01: Hardcoded claude-3-5-haiku-20241022 as default extraction model (configurable via function param, not env var)
- Phase 12-01: Re-raise on extraction failure (per user decision: return error to agent, not silent fallback)
- Phase 12-01: 15s timeout for keyword extraction (generous for cold starts/API congestion)
- Phase 12-02: Empty keyword lists fall back to original query to avoid empty result pitfall
- Phase 12-02: Graph results passed through as-is from search_graph_relationships (already formatted with relationship structure)
- Phase 12-02: Backfill is informational only (no re-query): other source's full results compensate
- Phase 13-01: LightRAG embedding text format: entities "name\ndescription", relationships "keywords\tsrc\ntgt\ndescription"
- Phase 13-01: Content hash SHA-256 comparison to skip re-embedding unchanged entities/relationships
- Phase 13-01: VDB upsert is non-blocking (try/except) consistent with graph extraction fault isolation
- Phase 13-01: make_relationship_doc_id sorts alphabetically for undirected relationship dedup
- Phase 13-01: Relationship weight derived from episode count (chunks mentioning the relationship)
- Phase 13-02: Query embedding reuse: embed es_query and graph_query in one API call, reuse for VDB searches
- Phase 13-02: VDB store injected via getattr(app.state, 'vdb_store', None) following Phase 8 optional service pattern
- Phase 13-02: Entity VDB uses low-level keyword embedding, relationship VDB uses high-level keyword embedding (LightRAG dual-level routing)
- Phase 14-01: 500-token per-item truncation cap (truncate text, never drop items)
- Phase 14-01: graph_text tokens counted toward relationship budget, appended as supplementary content
- Phase 14-01: Chunk budget dynamically calculated with unused entity/relationship redistribution
- Phase 14-01: Summary header only mentions non-empty categories to avoid mismatch with omitted sections
- Phase 14-02: Removed hashlib import after eliminating content-hash dedup (assemble_context handles dedup by segment_id)
- Phase 14-02: Updated existing VDB tests to match new section names rather than maintaining old assertions
- Phase 14-02: Added tiktoken mock fixture (autouse) to VDB integration test class for seamless context_assembly usage
### Roadmap Evolution
- Phase 10 added: Bi-temporal Timestamp Pipeline Fix (gap closure)
- Phase 11 added: Graph Polish + Tech Debt Cleanup (gap closure)
- Phase 12 added: LightRAG Dual-Level Keyword Extraction + Unified Search Tool
- Phase 13 added: LightRAG Entity & Relationship Vector Indices
- Phase 14 added: LightRAG Graph-Aware Context Assembly with Token Budgets
- Phase 15 added: LightRAG Retrieval Mode Router
- v3.0 milestone created: LightRAG-Inspired Smart Retrieval (Phases 12-15)

**Blockers:** None
**Tech Debt:** 12 items (0 critical) — see `milestones/v1-MILESTONE-AUDIT.md`

**Research Notes (v2.0):**
- Research completed with HIGH confidence across all areas
- Phase 7 needs deeper research during planning: Graphiti 0.28 API for episode tombstoning, diff engine query patterns
- Phase 8 needs empirical testing: tool routing degradation after adding graph tool
- Phases 6 and 9 have well-documented patterns, skip research-phase

## Session Continuity

Last session: 2026-02-25
Stopped at: Completed 14-02-PLAN.md (Smart search context assembly integration)
Resume file: .planning/phases/14-lightrag-graph-aware-context-assembly-with-token-budgets/14-02-SUMMARY.md

---
Phase 14 complete. Token-budgeted context assembly wired into smart_search with structured sections and 10 integration tests.
