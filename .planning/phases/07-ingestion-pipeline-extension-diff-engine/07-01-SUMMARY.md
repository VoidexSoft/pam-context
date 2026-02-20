---
phase: 07-ingestion-pipeline-extension-diff-engine
plan: 01
subsystem: database, api, graph
tags: [graphiti, neo4j, alembic, sqlalchemy, diff-engine, episode-tracking]

# Dependency graph
requires:
  - phase: 06-neo4j-graphiti-infrastructure
    provides: GraphitiService wrapper, entity type taxonomy (ENTITY_TYPES), Neo4j connection
provides:
  - Alembic migration 006 for graph_synced + graph_sync_retries columns
  - Graph extraction orchestrator (extract_graph_for_document, rollback_graph_for_document)
  - Chunk-level diff engine (compute_chunk_diff, build_diff_summary)
  - PostgresStore methods for graph sync flag management
affects: [07-02-PLAN, pipeline-integration, sync-graph-endpoint, ingestion-api]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-chunk add_episode() with group_id=doc-{id} and ENTITY_TYPES constraint"
    - "Episode UUID tracking in segment metadata_ for surgical cleanup"
    - "Content-hash-based chunk diffing for re-ingestion cost optimization"
    - "Field-level entity diff summary with old/new values"

key-files:
  created:
    - alembic/versions/006_add_graph_synced.py
    - src/pam/graph/extraction.py
    - src/pam/ingestion/diff_engine.py
  modified:
    - src/pam/common/models.py
    - src/pam/ingestion/stores/postgres_store.py
    - src/pam/graph/__init__.py

key-decisions:
  - "get_episode() for old entity info before removal -- best-effort with try/except fallback"
  - "Clear segment metadata on rollback regardless of remove_episode success to prevent stale references"

patterns-established:
  - "Episode UUID storage: segment.metadata['graph_episode_uuid'] after each add_episode()"
  - "Chunk diff via content_hash set comparison: O(n) classification of added/removed/unchanged"
  - "Graph rollback: per-episode remove_episode() with individual exception handling for resilience"
  - "Diff summary: field-level old/new detail for modified entities (locked user decision)"

requirements-completed: [EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-06, DIFF-01, DIFF-02]

# Metrics
duration: 4min
completed: 2026-02-20
---

# Phase 7 Plan 1: Graph Extraction + Diff Engine Summary

**Per-chunk Graphiti extraction orchestrator with episode UUID tracking, content-hash chunk diff engine, and graph_synced Alembic migration for sync flag management**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-20T13:03:27Z
- **Completed:** 2026-02-20T13:07:54Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Alembic migration 006 adds graph_synced boolean and graph_sync_retries integer columns to documents table with index
- Graph extraction orchestrator handles first ingestion and re-ingestion via chunk-level diff, calling add_episode() per chunk with ENTITY_TYPES, group_id, and reference_time
- Diff engine compares old vs new segment content_hash sets to classify chunks as added/removed/unchanged, with field-level entity diff summaries
- Rollback function surgically removes episodes on partial failure with per-episode exception handling
- PostgresStore gains set_graph_synced(), get_unsynced_documents(), and get_segments_for_document() methods

## Task Commits

Each task was committed atomically:

1. **Task 1: Alembic migration + Document model + PostgresStore methods** - `71a131d` (feat)
2. **Task 2: Graph extraction orchestrator + chunk-level diff engine** - `50d9167` (feat)

## Files Created/Modified
- `alembic/versions/006_add_graph_synced.py` - Migration adding graph_synced + graph_sync_retries columns with index
- `src/pam/graph/extraction.py` - Graph extraction orchestrator: extract_graph_for_document(), rollback_graph_for_document(), ExtractionResult
- `src/pam/ingestion/diff_engine.py` - ChunkDiff dataclass, compute_chunk_diff(), build_diff_summary() with field-level entity diffs
- `src/pam/common/models.py` - Document model: graph_synced bool + graph_sync_retries int; DocumentResponse: graph_synced field
- `src/pam/ingestion/stores/postgres_store.py` - PostgresStore: set_graph_synced(), get_unsynced_documents(), get_segments_for_document()
- `src/pam/graph/__init__.py` - Exports: ExtractionResult, extract_graph_for_document, rollback_graph_for_document

## Decisions Made
- Used try/except around get_episode() before removal to gather old entity info best-effort -- if the call fails, the removal still proceeds and the diff summary shows removal without entity detail
- Clear graph_episode_uuid and graph_entity_count from segment metadata during rollback regardless of whether remove_episode() succeeds, to prevent stale references pointing to nonexistent episodes

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed sqlalchemy import line length exceeding 120 chars**
- **Found during:** Task 1 (Document model update)
- **Issue:** Adding Boolean and text imports to the existing single-line sqlalchemy import exceeded the 120-char line limit (122 chars) and caused import sort violation
- **Fix:** Split the import into multi-line format
- **Files modified:** src/pam/common/models.py
- **Verification:** ruff check passed
- **Committed in:** 71a131d (part of Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Minor formatting fix required for lint compliance. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All core modules ready for pipeline integration (Plan 07-02)
- extraction.py is designed to be called from pipeline.py's ingest_document() method
- PostgresStore methods ready for set_graph_synced()/get_unsynced_documents() calls from pipeline and sync endpoint
- Diff engine ready for compute_chunk_diff() in re-ingestion path

## Self-Check: PASSED

All 4 created files verified on disk. Both task commits (71a131d, 50d9167) verified in git log.

---
*Phase: 07-ingestion-pipeline-extension-diff-engine*
*Completed: 2026-02-20*
