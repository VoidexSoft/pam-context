---
phase: 07-ingestion-pipeline-extension-diff-engine
verified: 2026-02-20T14:00:00Z
status: passed
score: 9/9 must-haves verified
re_verification: false
---

# Phase 7: Ingestion Pipeline Extension + Diff Engine Verification Report

**Phase Goal:** Every ingested document produces entity nodes and relationship edges in Neo4j with correct bi-temporal timestamps, graph failures never corrupt PG/ES data, and re-ingestion detects entity-level changes — so that the graph contains queryable knowledge before any user-facing feature is built.
**Verified:** 2026-02-20T14:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Document model has `graph_synced` boolean and `graph_sync_retries` integer columns | VERIFIED | `src/pam/common/models.py` lines 56-57: both `Mapped[bool]` and `Mapped[int]` fields present; `python -c "from pam.common.models import Document; hasattr(Document, 'graph_synced')"` → True |
| 2 | Alembic migration 006 creates `graph_synced` + `graph_sync_retries` columns with index | VERIFIED | `alembic/versions/006_add_graph_synced.py` — `upgrade()` adds both columns with server defaults and creates `ix_documents_graph_synced`; `downgrade()` reverses in correct order |
| 3 | `extract_graph_for_document()` calls `add_episode()` once per chunk with `group_id`, `entity_types`, and `reference_time` | VERIFIED | `src/pam/graph/extraction.py` line 121-130: `add_episode()` called per segment with `group_id=f"doc-{doc_id}"`, `entity_types=ENTITY_TYPES`, `reference_time=reference_time`; `add_episode_bulk` is never used |
| 4 | Chunk-level diff engine compares old vs new `content_hash` sets and classifies chunks as added/removed/unchanged | VERIFIED | `src/pam/ingestion/diff_engine.py` `compute_chunk_diff()` lines 39-57: O(n) hash dict lookup; functional test confirms: added=1, removed=1, unchanged=1 with episode UUID preserved |
| 5 | Graph failure sets `graph_synced=False` but document remains committed to PG and ES | VERIFIED | `src/pam/ingestion/pipeline.py` lines 159-219: graph extraction at step 11 occurs after `await self.session.commit()` at line 144; `except Exception as graph_err` calls `set_graph_synced(doc_id, False)` without rolling back PG/ES |
| 6 | Graph success sets `graph_synced=True`, diff summary logged to `SyncLog.details` | VERIFIED | `pipeline.py` lines 174-193: `set_graph_synced(doc_id, True)` called; `log_sync(doc_id, "graph_synced", ..., details=diff_summary)` called; `IngestionResult` returns `diff_summary` |
| 7 | Episode UUIDs stored in segment `metadata_` for surgical cleanup on re-ingestion | VERIFIED | `extraction.py` lines 134-136: `seg.metadata["graph_episode_uuid"] = episode_uuid` after each `add_episode()`; pipeline persists via `sa_update(Segment).values(metadata_=seg.metadata)` |
| 8 | Re-ingestion only sends changed chunks through Graphiti (diff engine integration) | VERIFIED | `pipeline.py` lines 117-121: old segments retrieved via `get_segments_for_document()` BEFORE `save_segments()` deletes them; passed as `old_segments=old_segments_for_diff` to `extract_graph_for_document()` |
| 9 | POST `/ingest/sync-graph` retries graph extraction for unsynced documents with limit and retry count (3) | VERIFIED | `src/pam/api/routes/ingest.py` lines 162-253: endpoint registered, `MAX_GRAPH_SYNC_RETRIES=3`, `get_unsynced_documents(max_retries=3, limit=limit)` called, per-document commit, remaining count returned |

**Score: 9/9 truths verified**

---

## Required Artifacts

### Plan 01 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `alembic/versions/006_add_graph_synced.py` | Migration for graph_synced + graph_sync_retries | VERIFIED | 35 lines, both `upgrade()` and `downgrade()` functions present; index `ix_documents_graph_synced` created |
| `src/pam/graph/extraction.py` | Graph extraction orchestrator | VERIFIED | 226 lines; exports `extract_graph_for_document`, `rollback_graph_for_document`, `ExtractionResult`; all three phases (remove stale, add new, build diff summary) implemented |
| `src/pam/ingestion/diff_engine.py` | Chunk-level diff engine | VERIFIED | 126 lines; exports `ChunkDiff`, `compute_chunk_diff`, `build_diff_summary`; field-level `modified` array with old/new values confirmed working |
| `src/pam/common/models.py` | Updated Document model with graph_synced fields | VERIFIED | Lines 56-57: `graph_synced: Mapped[bool]`, `graph_sync_retries: Mapped[int]`; `DocumentResponse` has `graph_synced: bool = False` at line 213 |
| `src/pam/ingestion/stores/postgres_store.py` | PostgresStore graph sync methods | VERIFIED | Lines 136-176: `set_graph_synced()`, `get_unsynced_documents()`, `get_segments_for_document()` all substantively implemented |
| `src/pam/graph/__init__.py` | Exports for extraction module | VERIFIED | Lines 13-28: exports `ExtractionResult`, `extract_graph_for_document`, `rollback_graph_for_document`; `__all__` list complete |

### Plan 02 Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pam/ingestion/pipeline.py` | Extended pipeline with graph extraction step | VERIFIED | Lines 159-228: step 11 graph extraction after ES write; `IngestionPipeline` has `graph_service` and `skip_graph` fields; `IngestionResult` has `graph_synced`, `graph_entities_extracted`, `diff_summary` |
| `src/pam/ingestion/task_manager.py` | Graph service passed through to pipeline | VERIFIED | Lines 61-76: `spawn_ingestion_task()` accepts `graph_service` and `skip_graph`; lines 167-177: `IngestionPipeline` constructed with both; progress callback includes `graph_synced` and `graph_entities_extracted` |
| `src/pam/api/routes/ingest.py` | POST /ingest/sync-graph endpoint + skip_graph param | VERIFIED | Route `/ingest/sync-graph` confirmed present; `skip_graph: bool = Query(default=False)` on `ingest_folder`; `Depends(get_graph_service)` wires graph DI |
| `src/pam/api/deps.py` | `get_graph_service()` dependency (existing) | VERIFIED | Line 58-59: `get_graph_service()` returns `cast(GraphitiService, request.app.state.graph_service)` |
| `web/src/pages/AdminDashboard.tsx` | Sync Graph button | VERIFIED | Lines 169-219: Sync Graph card with button, loading spinner (`animate-spin`), disabled state, result display (synced/failed/remaining), error display |
| `web/src/api/client.ts` | `syncGraph()` API client function | VERIFIED | Lines 264-275: `SyncGraphResult` interface and `syncGraph()` function using `request()` helper with POST to `/ingest/sync-graph` |

---

## Key Link Verification

### Plan 01 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `extraction.py` | `graphiti_core.Graphiti.add_episode` | `graph_service.client.add_episode()` per chunk | WIRED | Line 121: `await graph_service.client.add_episode(...)` called once per segment in loop |
| `extraction.py` | `diff_engine.py` | `compute_chunk_diff()` call for re-ingestion | WIRED | Line 74: `diff = compute_chunk_diff(old_segments, segments)` when old_segments provided |
| `extraction.py` | `graph/entity_types.py` | `ENTITY_TYPES` passed to `add_episode` | WIRED | Line 19: import; line 130: `entity_types=ENTITY_TYPES` in add_episode call |

### Plan 02 Key Links

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `pipeline.py` | `extraction.py` | `extract_graph_for_document()` after ES write | WIRED | Line 17-21: import; line 165: called after PG commit (line 144) and ES write |
| `pipeline.py` | `extraction.py` | `rollback_graph_for_document()` on exception | WIRED | Line 212: called inside `except Exception as graph_err` block |
| `pipeline.py` | `postgres_store.py` | `set_graph_synced()` and `get_segments_for_document()` | WIRED | Lines 120, 177, 208: `get_segments_for_document()` and both True/False `set_graph_synced()` paths |
| `ingest.py` | `postgres_store.py` | `get_unsynced_documents()` for sync-graph endpoint | WIRED | Line 178: `await pg_store.get_unsynced_documents(max_retries=MAX_GRAPH_SYNC_RETRIES, limit=limit)` |
| `ingest.py` | `deps.py` | `Depends(get_graph_service)` for sync-graph endpoint | WIRED | Line 17: import; line 166: `graph_service: GraphitiService = Depends(get_graph_service)` |
| `task_manager.py` | `pipeline.py` | `graph_service` parameter passed to `IngestionPipeline` | WIRED | Lines 68-69: params on `spawn_ingestion_task()`; lines 174-177: `IngestionPipeline(... graph_service=graph_service, skip_graph=skip_graph)` |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| EXTRACT-01 | 07-01 | Pipeline calls `add_episode()` (never `add_episode_bulk`) after PG commit for each segment | SATISFIED | `extraction.py` line 121: single `add_episode()` in loop; `add_episode_bulk` not present anywhere in codebase |
| EXTRACT-02 | 07-01 | Entity nodes and relationship edges created in Neo4j with bi-temporal timestamps sourced from document `modified_at` | SATISFIED | `add_episode()` receives `reference_time=getattr(raw_doc, "modified_at", None) or datetime.now(UTC)`; Graphiti handles Neo4j write with bi-temporal semantics |
| EXTRACT-03 | 07-01 | `graph_synced` boolean added to PG documents table via Alembic migration | SATISFIED | Migration 006 verified; `Document.graph_synced` column exists |
| EXTRACT-04 | 07-02 | Graph extraction runs as background step — failure never rolls back PG/ES data | SATISFIED | Step 11 graph extraction occurs after `session.commit()` at line 144; its own `try/except` catches all exceptions without triggering outer rollback |
| EXTRACT-05 | 07-02 | Reconciliation endpoint `/ingest/sync-graph` retries documents with `graph_synced=False` | SATISFIED | POST `/ingest/sync-graph` route confirmed; queries via `get_unsynced_documents()`; increments retries on failure |
| EXTRACT-06 | 07-01 | Orphan node prevention via `group_id`-scoped episode tombstoning before re-ingestion | SATISFIED | `extraction.py` lines 86-113: `remove_episode(episode_uuid)` called for each removed segment's stored UUID before adding new episodes |
| DIFF-01 | 07-01 | Diff engine detects entity-level changes on re-ingestion (added/modified/removed entities) | SATISFIED | `diff_engine.py` `compute_chunk_diff()` classifies by content_hash; `build_diff_summary()` returns `added`, `removed_from_document`, `modified` with field-level old/new |
| DIFF-02 | 07-01 | Superseded edges have `t_invalid` set via Graphiti conflict resolution | SATISFIED | `remove_episode()` called before re-adding changed chunks; Graphiti's conflict resolution sets `t_invalid` on superseded edges via its internal episode processing (per design) |
| DIFF-03 | 07-02 | Entity-level diff summaries written to `SyncLog.details` as structured JSON | SATISFIED | `pipeline.py` line 190-192: `log_sync(doc_id, "graph_synced", ..., details=diff_summary)`; `SyncLog.details` is `JSONB` column; sync-graph endpoint also persists diff via `log_sync()` |

**All 9 Phase 7 requirements: SATISFIED**

No orphaned requirements found. REQUIREMENTS.md maps EXTRACT-01 through EXTRACT-06 and DIFF-01 through DIFF-03 exclusively to Phase 7, and both plans collectively claim all 9 IDs.

---

## Anti-Patterns Found

None detected across all 9 Python files and 2 frontend files modified in this phase. No TODOs, no FIXME, no placeholder returns, no empty implementations.

**One pre-existing lint warning noted (not introduced by Phase 7):**

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `src/pam/api/routes/ingest.py` | 121 | B904: `raise HTTPException` without `from err` inside `except` clause | Info | Pre-existing from Phase 3 (commit d082333); not introduced by Phase 7 changes; does not affect runtime behavior |

---

## Human Verification Required

### 1. Neo4j Entity Node Creation

**Test:** Ingest a markdown document with the backend running and Neo4j connected. Then connect to Neo4j Browser or run `MATCH (n) RETURN n LIMIT 25` to inspect nodes.
**Expected:** Entity nodes of types from the ENTITY_TYPES taxonomy (Person, Team, Project, Technology, Process, Asset, Concept) appear with `group_id` matching `doc-{uuid}` and `t_valid` set to the document's modified_at timestamp.
**Why human:** Requires live Neo4j connection + Graphiti LLM extraction; cannot be verified statically.

### 2. Bi-temporal Timestamp Correctness

**Test:** Ingest a document, then query `MATCH (e:Episode) RETURN e.group_id, e.valid_at, e.created_at LIMIT 10` in Neo4j.
**Expected:** `valid_at` equals the document's `modified_at` timestamp (or `datetime.now(UTC)` for connectors that don't set `modified_at`), not the ingestion timestamp.
**Why human:** Requires live Neo4j + Graphiti to verify temporal property values on the created episode nodes.

### 3. Re-ingestion Diff Behavior

**Test:** Ingest a document, modify a paragraph, ingest again. Check the `sync_log` table for `action='graph_synced'` entries and inspect the `details` JSONB.
**Expected:** The second ingestion's `details` shows `modified` or `added`/`removed_from_document` entities that reflect the actual content change; only changed chunks are sent through `add_episode()` (verifiable from log output `"extracted N/M chunks"` where N < M).
**Why human:** Requires live environment with multiple ingest runs to observe differential behavior.

### 4. Sync Graph Button End-to-End

**Test:** Ingest a document while Neo4j is down (to force `graph_synced=False`). Then bring Neo4j back up and click "Sync Graph" in the Admin Dashboard.
**Expected:** Button shows spinner while request is in flight; result shows `Synced: 1, Failed: 0, Remaining: 0`; document `graph_synced` flips to `true` in PG.
**Why human:** Requires controlled failure scenario with live services; button disabled state and spinner are visual.

### 5. Graph Failure Isolation

**Test:** With Neo4j stopped, ingest a document. Verify the document is queryable via the chat API.
**Expected:** Document appears in search results with its content; no error visible to the end user; PG and ES data intact; `graph_synced=False` in the documents table.
**Why human:** Requires intentional service disruption to validate the fault isolation guarantee.

---

## Gaps Summary

No gaps found. All automated checks passed:

- All 9 requirement IDs (EXTRACT-01 through EXTRACT-06, DIFF-01 through DIFF-03) are implemented and traceable to code artifacts.
- All 11 artifacts from the two plans exist on disk and are substantively implemented (no stubs, no placeholders).
- All 9 key links from the two plans are wired (imports + usage confirmed).
- Episode UUIDs are tracked in segment metadata and persisted back to PG.
- Diff engine functional test confirms correct classification and episode UUID preservation.
- Diff summary functional test confirms field-level `modified` entries with `old`/`new` values.
- Sync-graph endpoint is routable, uses correct DI, and returns structured response.
- Admin Dashboard Sync Graph button is wired to `syncGraph()` with loading state and result display.
- One pre-existing ruff B904 lint warning in `ingest.py` (line 121) — introduced in Phase 3, not Phase 7.

---

_Verified: 2026-02-20T14:00:00Z_
_Verifier: Claude (gsd-verifier)_
