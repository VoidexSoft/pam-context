---
phase: 10-bitemporal-timestamp-fix
plan: 01
subsystem: ingestion
tags: [bitemporal, timestamps, graphiti, neo4j, connectors, alembic]

# Dependency graph
requires:
  - phase: 07-ingestion-pipeline-extension-diff-engine
    provides: "graph extraction pipeline with add_episode and reference_time parameter"
  - phase: 06-neo4j-graphiti-infrastructure
    provides: "GraphitiService and Neo4j infrastructure"
provides:
  - "RawDocument.modified_at field populated by all connector types"
  - "Document.modified_at ORM column persisted via Alembic migration 007"
  - "Pipeline passes modified_at through to upsert_document and extract_graph_for_document"
  - "Sync-graph endpoint uses doc.modified_at as primary reference_time with cascading fallback"
affects: [11-graph-polish-tech-debt, graph-extraction, ingestion-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: ["bi-temporal timestamp propagation from connector metadata through pipeline to graph extraction"]

key-files:
  created:
    - "alembic/versions/007_add_modified_at.py"
  modified:
    - "src/pam/common/models.py"
    - "src/pam/ingestion/stores/postgres_store.py"
    - "src/pam/ingestion/connectors/markdown.py"
    - "src/pam/ingestion/connectors/google_docs.py"
    - "src/pam/ingestion/connectors/google_sheets.py"
    - "src/pam/ingestion/pipeline.py"
    - "src/pam/api/routes/ingest.py"
    - "tests/test_ingestion/test_google_docs_connector.py"

key-decisions:
  - "Nullable modified_at with no backfill -- existing documents get NULL which correctly triggers datetime.now(UTC) fallback"
  - "Direct raw_doc.modified_at access replaces getattr fallback pattern for explicit data flow"
  - "Cascading fallback chain in sync-graph: doc.modified_at -> doc.last_synced_at -> datetime.now(UTC)"

patterns-established:
  - "Connector metadata propagation: connectors populate RawDocument fields, pipeline forwards them to stores and graph extraction"
  - "Cascading timestamp fallback: primary source -> secondary source -> current time"

requirements-completed: [EXTRACT-02]

# Metrics
duration: 5min
completed: 2026-02-22
---

# Phase 10 Plan 01: Bitemporal Timestamp Pipeline Fix Summary

**Wire document modified_at timestamps from connector metadata through RawDocument, Document ORM, pipeline, and sync-graph endpoint to Graphiti add_episode reference_time**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-22T15:00:04Z
- **Completed:** 2026-02-22T15:05:32Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Added modified_at field to both RawDocument Pydantic model and Document ORM model with Alembic migration 007
- All three connector types (markdown, Google Docs, Google Sheets) now populate modified_at from source metadata
- Pipeline passes modified_at through to both PostgresStore.upsert_document and extract_graph_for_document reference_time
- Sync-graph endpoint uses doc.modified_at as primary reference_time with cascading fallback chain
- Removed getattr fallback pattern in pipeline for explicit data flow

## Task Commits

Each task was committed atomically:

1. **Task 1: Add modified_at to models and create Alembic migration** - `21f2532` (feat)
2. **Task 2: Wire modified_at through connectors, pipeline, and sync endpoint** - `8c89c37` (feat)
3. **Task 2 test fix: Update google docs test assertion** - `43fd7ab` (fix)

## Files Created/Modified
- `src/pam/common/models.py` - Added modified_at to RawDocument and Document ORM
- `alembic/versions/007_add_modified_at.py` - Migration adding nullable modified_at column
- `src/pam/ingestion/stores/postgres_store.py` - upsert_document accepts and persists modified_at
- `src/pam/ingestion/connectors/markdown.py` - Populates modified_at from filesystem st_mtime (UTC)
- `src/pam/ingestion/connectors/google_docs.py` - Populates modified_at from Drive API modifiedTime
- `src/pam/ingestion/connectors/google_sheets.py` - Populates modified_at from Drive API modifiedTime
- `src/pam/ingestion/pipeline.py` - Direct raw_doc.modified_at access, passes to upsert and graph extraction
- `src/pam/api/routes/ingest.py` - Sync-graph uses doc.modified_at as primary reference_time
- `tests/test_ingestion/test_google_docs_connector.py` - Updated field assertion for modifiedTime

## Decisions Made
- **Nullable modified_at with no backfill:** Existing documents get NULL which correctly triggers the datetime.now(UTC) fallback. No data migration needed.
- **Direct access replaces getattr:** Replaced `getattr(raw_doc, "modified_at", None)` with `raw_doc.modified_at` since the field now exists on the model.
- **Cascading fallback in sync-graph:** `doc.modified_at or doc.last_synced_at or datetime.now(UTC)` prioritizes actual document modification time.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated Google Docs connector test assertion**
- **Found during:** Task 2 (verification step)
- **Issue:** Test `test_requests_correct_metadata_fields` asserted old fields string without modifiedTime
- **Fix:** Updated assertion to match new fields: `"name, owners, webViewLink, modifiedTime"`
- **Files modified:** tests/test_ingestion/test_google_docs_connector.py
- **Verification:** All 143 model and ingestion tests pass
- **Committed in:** 43fd7ab

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Test assertion update was a direct consequence of adding modifiedTime to fetch fields. No scope creep.

## Issues Encountered
- Pre-existing B904 lint warning in `src/pam/api/routes/ingest.py:121` (unrelated to changes, not fixed per scope boundary)
- Pre-existing test failure in `tests/test_common/test_config.py::test_default_values` (agent_model default changed, unrelated to changes)

## User Setup Required
None - no external service configuration required. Run `alembic upgrade head` to apply migration 007 on existing databases.

## Next Phase Readiness
- EXTRACT-02 gap is closed: bi-temporal timestamps flow from connector metadata to graph extraction
- Ready for Phase 11 (Graph Polish + Tech Debt Cleanup) if planned
- Alembic migration 007 must be applied before ingesting new documents to persist modified_at

---
*Phase: 10-bitemporal-timestamp-fix*
*Completed: 2026-02-22*
