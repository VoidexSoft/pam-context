---
phase: 11-graph-polish-tech-debt
plan: 01
subsystem: api, ui
tags: [fastapi, react, sqlalchemy, tailwind, empty-state, null-guard]

# Dependency graph
requires:
  - phase: 06-neo4j-graphiti-infrastructure
    provides: GraphitiService singleton and get_graph_service DI
  - phase: 09-graph-explorer-ui
    provides: GraphExplorerPage, useGraphExplorer hook, GraphStatus interface
provides:
  - Extended graph_status endpoint with PG document counts
  - Two-branch empty state in graph explorer (no-docs vs indexing-in-progress)
  - Explicit 503 null guards on graph data endpoints
affects: [12-lightrag-dual-level-keyword-extraction-unified-search-tool]

# Tech tracking
tech-stack:
  added: []
  patterns: [null-guard-before-neo4j-ops, degraded-200-for-status-endpoints]

key-files:
  created: []
  modified:
    - src/pam/api/routes/graph.py
    - web/src/api/client.ts
    - web/src/hooks/useGraphExplorer.ts
    - web/src/pages/GraphExplorerPage.tsx

key-decisions:
  - "graph_status returns degraded 200 (not 503) when graph_service is None to preserve document counts for frontend empty states"
  - "Data endpoints (neighborhood, entities, history) return 503 with structured JSON when graph_service is None"
  - "Two empty state branches: documentCount===0 shows 'No documents ingested' with ingest link; documentCount>0 with entityCount===0 shows 'Graph indexing in progress'"

patterns-established:
  - "Null guard pattern: check graph_service is None before Neo4j ops, raise 503 for data endpoints"
  - "Degraded status pattern: status endpoints return 200 with 'unavailable' status and partial data"

requirements_completed:
  - id: VIZ-06
    desc: Graph indexing in progress empty state

# Metrics
duration: 8min
completed: 2026-02-23
---

# Phase 11 Plan 01: VIZ-06 Empty State + Graph Null Guards Summary

**Two-branch graph explorer empty state with PG document counts and explicit 503 null guards on graph data endpoints**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-23T15:22:10Z
- **Completed:** 2026-02-23T15:30:24Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Extended `/graph/status` with `document_count` and `graph_synced_count` from PostgreSQL, returned in all response paths (connected, unavailable, disconnected)
- Implemented two-branch empty state: "No documents ingested" with Go to Ingest button, and "Graph indexing in progress" with pending document count
- Added explicit null guards on three graph data endpoints (neighborhood, entities, history) returning 503 with `{"detail": "Graph service unavailable"}`

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend graph_status with PG document counts and add null guards** - `1a0e893` (feat)
2. **Task 2: Update frontend types, hook state, and GraphExplorerPage empty states** - `b3c7616` (feat)

## Files Created/Modified
- `src/pam/api/routes/graph.py` - Added PG count queries to graph_status, null guards on 4 endpoints, degraded 200 response for status
- `web/src/api/client.ts` - Extended GraphStatus interface with document_count and graph_synced_count fields
- `web/src/hooks/useGraphExplorer.ts` - Added documentCount and graphSyncedCount to hook state and return values
- `web/src/pages/GraphExplorerPage.tsx` - Replaced single empty state with two branches: no-documents and indexing-in-progress

## Decisions Made
- **graph_status returns 200 (not 503) when graph_service is None:** Status endpoints serve as health probes and the frontend needs document counts to render the correct empty state. A 503 would prevent the frontend from getting document counts. Used `"status": "unavailable"` to differentiate from `"disconnected"` (Neo4j connection failure at runtime).
- **Consistent indigo color palette for empty states:** Both empty state branches use `bg-indigo-50` backgrounds and `text-indigo-400` icons to match the explorer's existing color scheme, per user constraint.
- **Pending count calculation:** `documentCount - graphSyncedCount` for the "awaiting graph indexing" message, with singular/plural grammar handling.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- VIZ-06 requirement satisfied, ready for plan 02 (lint fix + SUMMARY frontmatter standardization)
- All graph endpoints now have explicit null guards for graceful Neo4j absence

## Self-Check: PASSED

- All 4 modified files exist on disk
- Commit 1a0e893 (Task 1) verified in git log
- Commit b3c7616 (Task 2) verified in git log

---
*Phase: 11-graph-polish-tech-debt*
*Completed: 2026-02-23*
