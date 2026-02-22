# Project State: PAM Context

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-19)

**Core value:** Users can ask natural-language questions about their business documents and get accurate, cited answers
**Current focus:** v2.0 Gap Closure — Phase 10

## Current Position

Phase: 10 of 15 (Bitemporal Timestamp Fix)
Plan: 1 of 1 complete
Status: Complete
Last activity: 2026-02-22 — Completed 10-01-PLAN.md (Bitemporal timestamp pipeline fix)

Progress: [##############################] 100% (22/22 plans across all milestones)

## Milestone Progress

| Milestone | Phases | Plans | Status |
|-----------|--------|-------|--------|
| v1 Code Quality Cleanup | 5/5 | 10/10 | Shipped 2026-02-19 |
| v2.0 Knowledge Graph | 4/4 | 12/12 | Complete |

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

Last session: 2026-02-22
Stopped at: Completed 10-01-PLAN.md (Bitemporal timestamp pipeline fix)
Resume file: .planning/phases/10-bitemporal-timestamp-fix/10-01-SUMMARY.md

---
Phase 10 complete. EXTRACT-02 gap closed.
