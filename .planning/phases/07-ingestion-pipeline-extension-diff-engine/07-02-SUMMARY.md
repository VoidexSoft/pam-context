---
phase: 07-ingestion-pipeline-extension-diff-engine
plan: 02
subsystem: api, ingestion, graph, ui
tags: [graphiti, pipeline, graph-extraction, sync-graph, diff-engine, fastapi, react]

# Dependency graph
requires:
  - phase: 07-ingestion-pipeline-extension-diff-engine
    plan: 01
    provides: Graph extraction orchestrator, diff engine, PostgresStore graph sync methods, Alembic migration
provides:
  - Pipeline graph extraction step after PG+ES commit (non-blocking, fault-tolerant)
  - POST /ingest/sync-graph endpoint for retry of failed graph extractions
  - ?skip_graph=true query param on /ingest/folder
  - graph_service flow from app.state through task_manager to pipeline
  - Admin dashboard Sync Graph button with loading state and result display
affects: [08-agent-graph-tool, ingestion-api, admin-dashboard, graph-sync]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Non-blocking graph extraction after PG+ES commit with try/except fault isolation"
    - "Old segment retrieval before save_segments() for chunk-level diff on re-ingestion"
    - "Episode UUID metadata persistence via sa_update(Segment) after extraction"
    - "Sync recovery endpoint with per-document retry count and limit cap"

key-files:
  created: []
  modified:
    - src/pam/ingestion/pipeline.py
    - src/pam/ingestion/task_manager.py
    - src/pam/api/routes/ingest.py
    - web/src/api/client.ts
    - web/src/pages/AdminDashboard.tsx

key-decisions:
  - "Graph extraction is non-blocking: failure sets graph_synced=False without affecting PG/ES data"
  - "Old segments retrieved BEFORE save_segments() to preserve diff data before deletion"
  - "Sync endpoint uses Depends(get_graph_service) for DI; ingest_folder uses getattr(app.state) for background task pattern"
  - "MAX_GRAPH_SYNC_RETRIES=3 as constant in ingest routes"

patterns-established:
  - "Pipeline graph step: extract after ES write, rollback episodes on failure, persist episode UUIDs in segment metadata"
  - "Sync recovery pattern: query unsynced docs, retry extraction per-document with commit after each, count remaining"
  - "from __future__ import annotations for TYPE_CHECKING-guarded GraphitiService in dataclass fields"

requirements-completed: [EXTRACT-04, EXTRACT-05, DIFF-03]

# Metrics
duration: 7min
completed: 2026-02-20
---

# Phase 7 Plan 2: Pipeline Integration + Sync API Summary

**Graph extraction wired into ingestion pipeline with fault-tolerant try/except, sync-graph recovery endpoint with retry limits, skip_graph param, and admin dashboard sync button**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-20T13:11:24Z
- **Completed:** 2026-02-20T13:18:37Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Pipeline calls extract_graph_for_document() after PG+ES commit, wrapped in try/except so graph failure never corrupts PG/ES data
- Re-ingestion retrieves old segments before deletion for chunk-level diff comparison via the diff engine
- POST /ingest/sync-graph endpoint retries graph extraction for unsynced documents with limit and retry count (3)
- ?skip_graph=true query param on /ingest/folder skips graph extraction entirely
- graph_service flows from app.state through spawn_ingestion_task to IngestionPipeline
- Admin dashboard has a "Sync Graph" button with loading spinner, result counts, and error display

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire graph extraction into pipeline + task manager** - `1ad45f9` (feat)
2. **Task 2: Sync recovery endpoint + skip_graph param + Sync Graph button** - `3f1f5c6` (feat)

## Files Created/Modified
- `src/pam/ingestion/pipeline.py` - Added graph extraction step 11 after ES write, old segment retrieval before save_segments, graph fields on IngestionResult and IngestionPipeline
- `src/pam/ingestion/task_manager.py` - Added graph_service and skip_graph params to spawn_ingestion_task and run_ingestion_background, graph fields in progress callback
- `src/pam/api/routes/ingest.py` - Added POST /ingest/sync-graph endpoint with retry logic, skip_graph query param on ingest_folder, graph_service pass-through
- `web/src/api/client.ts` - Added SyncGraphResult interface and syncGraph() API client function
- `web/src/pages/AdminDashboard.tsx` - Added Sync Graph card with button, loading spinner, result display, and error handling

## Decisions Made
- Graph extraction is non-blocking: failure sets graph_synced=False without affecting PG/ES data integrity
- Old segments retrieved BEFORE save_segments() deletes them, preserving data needed for chunk-level diff
- Sync endpoint uses Depends(get_graph_service) for dependency injection (consistent with Phase 6 graph route pattern); ingest_folder uses getattr(app.state) since it passes to background task
- MAX_GRAPH_SYNC_RETRIES set to 3 as a module-level constant

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added from __future__ import annotations to pipeline.py and task_manager.py**
- **Found during:** Task 1 (Pipeline graph_service field)
- **Issue:** GraphitiService type annotation under TYPE_CHECKING was not available at runtime for dataclass field annotations, causing NameError
- **Fix:** Added `from __future__ import annotations` to both pipeline.py and task_manager.py to defer annotation evaluation
- **Files modified:** src/pam/ingestion/pipeline.py, src/pam/ingestion/task_manager.py
- **Verification:** Import checks pass, no circular imports
- **Committed in:** 1ad45f9 (Task 1 commit)

**2. [Rule 1 - Bug] Removed unused `field` import from pipeline.py**
- **Found during:** Task 1 (ruff check)
- **Issue:** `from dataclasses import dataclass, field` had unused `field` import after adding `from __future__ import annotations`
- **Fix:** Changed to `from dataclasses import dataclass`
- **Files modified:** src/pam/ingestion/pipeline.py
- **Verification:** ruff check passed
- **Committed in:** 1ad45f9 (Task 1 commit)

**3. [Rule 1 - Bug] Removed unnecessary forward reference quotes on IngestionResult**
- **Found during:** Task 1 (ruff check)
- **Issue:** With `from __future__ import annotations`, the quoted `"IngestionResult"` in Callable type hint triggered ruff UP037
- **Fix:** Removed quotes: `Callable[[IngestionResult], Awaitable[None]]`
- **Files modified:** src/pam/ingestion/pipeline.py
- **Verification:** ruff check passed
- **Committed in:** 1ad45f9 (Task 1 commit)

---

**Total deviations:** 3 auto-fixed (1 blocking, 2 bugs)
**Impact on plan:** All auto-fixes necessary for correctness and lint compliance. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Graph extraction is fully integrated into the ingestion pipeline
- All graph sync infrastructure (flags, retries, sync endpoint) is operational
- Phase 7 complete -- ready for Phase 8 (Agent Graph Tool integration)
- The agent can now be extended with a graph search tool that queries Neo4j entities

## Self-Check: PASSED

All 5 modified files verified on disk. Both task commits (1ad45f9, 3f1f5c6) verified in git log.

---
*Phase: 07-ingestion-pipeline-extension-diff-engine*
*Completed: 2026-02-20*
