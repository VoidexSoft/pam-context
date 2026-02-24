---
phase: 13-lightrag-entity-and-relationship-vector-indices
verified: 2026-02-24T15:55:00Z
status: passed
score: 5/5 success criteria verified
re_verification: false
requirements_note: >
  VDB-01, VDB-02, VDB-03 are referenced in plan frontmatter but are NOT defined
  in .planning/REQUIREMENTS.md (which covers only the v2.0 milestone requirements
  INFRA-*, EXTRACT-*, GRAPH-*, DIFF-*, VIZ-*). These are new Phase 13-specific
  requirement IDs that were not formally added to REQUIREMENTS.md. The implementation
  satisfies what those IDs describe, but the IDs themselves are orphaned from the
  requirements registry. This is a documentation gap, not an implementation gap.
---

# Phase 13: LightRAG Entity & Relationship Vector Indices — Verification Report

**Phase Goal:** Entity descriptions and relationship descriptions are independently embedded and searchable in Elasticsearch — so that semantic entity discovery ("find teams working on deployment") and relationship discovery ("what connects infrastructure to reliability") work without knowing exact entity names, following LightRAG's 3-VDB pattern.
**Verified:** 2026-02-24T15:55:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | ES index `pam_entities` stores entity records with fields: `name`, `entity_type`, `description`, `embedding` (1536-dim), `source_ids`, `file_paths` | VERIFIED | `get_entity_index_mapping()` in `entity_relationship_store.py` lines 46-69 defines all required fields with correct types: `name`/`entity_type` as keyword, `description` as text, `embedding` as dense_vector with 1536 dims and cosine similarity, `source_ids`/`file_paths` as keyword arrays |
| 2 | ES index `pam_relationships` stores relationship records with fields: `src_entity`, `tgt_entity`, `keywords`, `description`, `embedding` (1536-dim), `weight`, `source_ids` | VERIFIED | `get_relationship_index_mapping()` lines 72-97 defines all required fields: `src_entity`/`tgt_entity`/`rel_type` as keyword, `keywords`/`description` as text, `embedding` as 1536-dim dense_vector, `weight` as float, `source_ids` as keyword array |
| 3 | During graph extraction, entity and relationship descriptions are embedded and upserted into these indices alongside the existing Neo4j writes | VERIFIED | `extraction.py` Phase 2b (lines 194-243) accumulates entity records from `new_entities` dict and relationship records from `all_edges` dict, then calls `vdb_store.upsert_entities()` and `vdb_store.upsert_relationships()`. Full chain wired: lifespan → `app.state.vdb_store` → `ingest.py` → `task_manager.py` → `pipeline.py` → `extraction.py` |
| 4 | `smart_search` uses entity VDB for low-level keyword matching and relationship VDB for high-level keyword matching (in addition to existing `pam_segments` and Graphiti search) | VERIFIED | `agent.py` `_smart_search()` runs 4-way `asyncio.gather` (lines 473-479): ES segments + Graphiti + `_entity_vdb_search_coro` (uses `es_query_embedding`) + `_rel_vdb_search_coro` (uses `graph_query_embedding`). Output includes `## Entity Matches` and `## Relationship Matches` sections (lines 567, 578). 13/13 integration tests pass |
| 5 | Re-ingestion updates entity/relationship embeddings when descriptions change (keyed by entity name or sorted src+tgt pair) | VERIFIED | `_filter_unchanged()` (lines 142-171) performs `mget` of existing `content_hash` fields, compares SHA-256 of embedding text content; skips re-embedding when unchanged. Entity doc ID = `entity.name`, relationship doc ID = `make_relationship_doc_id(src, rel_type, tgt)` which alphabetically sorts src/tgt (line 107-108) |

**Score:** 5/5 success criteria verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `src/pam/ingestion/stores/entity_relationship_store.py` | EntityRelationshipVDBStore with index mappings, ensure_indices, upsert_entities, upsert_relationships, search_entities, search_relationships | VERIFIED | 447 lines (min 150 required). All 6 public methods present. Contains `upsert_entities`, `search_entities`, `search_relationships`. |
| `src/pam/common/config.py` | entity_index and relationship_index name settings | VERIFIED | Lines 69-76: `entity_index = "pam_entities"`, `relationship_index = "pam_relationships"`, `smart_search_entity_limit = 5`, `smart_search_relationship_limit = 5` |
| `src/pam/graph/extraction.py` | VDB upsert integration after graph extraction loop | VERIFIED | Lines 194-243: Phase 2b VDB upsert block with uuid_to_name resolution, entity/edge accumulation, and try/except non-blocking pattern. `vdb_store` and `embedder` parameters in function signature (lines 52-53). |
| `src/pam/api/main.py` | VDB store creation in lifespan | VERIFIED | Lines 56-66: `EntityRelationshipVDBStore` created with `entity_index`/`relationship_index`/`embedding_dims` from settings, `ensure_indices()` called, stored on `app.state.vdb_store` |
| `src/pam/agent/agent.py` | 4-way asyncio.gather in _smart_search with entity/relationship VDB coroutines | VERIFIED | Lines 456-479: `_entity_vdb_search_coro` and `_rel_vdb_search_coro` defined and included in 4-way `asyncio.gather`. Contains `entity_vdb_search` reference (via `vdb_store.search_entities`) |
| `tests/test_agent/test_smart_search_vdb.py` | Integration tests for VDB search in smart_search | VERIFIED | 312 lines (min 40 required). 13 tests across 3 test classes: `TestVDBStoreSearchMethods`, `TestSmartSearchVDBIntegration`, `TestConfigDefaults`. All 13 pass. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `src/pam/graph/extraction.py` | `entity_relationship_store.py` | `upsert_entities()` and `upsert_relationships()` calls after chunk loop | WIRED | Lines 227-231 call `vdb_store.upsert_entities(entity_records, embedder, source_id)` and `vdb_store.upsert_relationships(rel_records, embedder, source_id)` inside Phase 2b block |
| `src/pam/api/main.py` | `entity_relationship_store.py` | `EntityRelationshipVDBStore` creation in lifespan | WIRED | Lines 57-66: `from pam.ingestion.stores.entity_relationship_store import EntityRelationshipVDBStore` followed by instantiation and `ensure_indices()` call |
| `entity_relationship_store.py` | `src/pam/ingestion/embedders/base.py` | `BaseEmbedder.embed_texts()` for batch embedding | WIRED | `embedder.embed_texts(texts_to_embed)` called at lines 209 and 297 within upsert methods. `BaseEmbedder` imported via `TYPE_CHECKING` guard at line 17 |
| `src/pam/agent/agent.py` | `entity_relationship_store.py` | `self.vdb_store.search_entities()` and `search_relationships()` | WIRED | Lines 459-469: `self.vdb_store.search_entities(query_embedding=es_query_embedding, ...)` and `self.vdb_store.search_relationships(query_embedding=graph_query_embedding, ...)` |
| `src/pam/agent/agent.py` | `src/pam/ingestion/embedders/base.py` | `self.embedder.embed_texts()` for query embedding reuse | WIRED | Line 433: `query_embeddings = await self.embedder.embed_texts([es_query, graph_query])` — single call reused for all 4 search coroutines |
| `src/pam/api/deps.py` | `src/pam/api/main.py` | `vdb_store` from `app.state` injected into agent | WIRED | Line 70: `vdb_store = getattr(request.app.state, "vdb_store", None)` passed to `RetrievalAgent` constructor at line 80 |

---

## Full Ingestion Chain Wiring

| Link | Status |
|------|--------|
| `lifespan` creates `EntityRelationshipVDBStore` and stores on `app.state.vdb_store` | VERIFIED (main.py lines 56-66) |
| `ingest.py` reads `vdb_store` from `app.state` via `getattr` | VERIFIED (ingest.py line 66) |
| `ingest.py` passes `vdb_store` to `spawn_ingestion_task()` | VERIFIED (ingest.py line 76) |
| `task_manager.py` accepts `vdb_store` parameter in `spawn_ingestion_task` and `run_ingestion_background` | VERIFIED (task_manager.py lines 71, 94) |
| `task_manager.py` passes `vdb_store` to `IngestionPipeline` constructor | VERIFIED (task_manager.py line 179) |
| `pipeline.py` has `vdb_store` field on `IngestionPipeline` dataclass | VERIFIED (pipeline.py line 58) |
| `pipeline.py` passes `vdb_store` and `embedder` to `extract_graph_for_document()` | VERIFIED (pipeline.py lines 176-177) |
| `extraction.py` accepts `vdb_store` and `embedder` and upserts after chunk loop | VERIFIED (extraction.py lines 52-53, 195-243) |

---

## Requirements Coverage

| Requirement | Plan | Status | Notes |
|-------------|------|--------|-------|
| VDB-01 | 13-01 | NOT IN REQUIREMENTS.MD | ID claimed in plan frontmatter but not defined in `.planning/REQUIREMENTS.md`. The implementation described (pam_entities index with dense_vector embedding) is fully implemented. This is a documentation gap — the requirement ID does not exist in the requirements registry. |
| VDB-02 | 13-01 | NOT IN REQUIREMENTS.MD | Same as VDB-01. The pam_relationships index implementation is complete. Documentation gap only. |
| VDB-03 | 13-01, 13-02 | NOT IN REQUIREMENTS.MD | Same as VDB-01. The smart_search 4-way integration is complete. Documentation gap only. |

**Assessment:** All three requirement IDs (VDB-01, VDB-02, VDB-03) are referenced in plan frontmatter but do not appear anywhere in `.planning/REQUIREMENTS.md`. The requirements file covers only v2.0 milestone requirements (INFRA-*, EXTRACT-*, GRAPH-*, DIFF-*, VIZ-*). These VDB-* IDs appear to be Phase 13-specific requirement labels created during planning that were never added to the requirements registry. The **implementation fully satisfies what the IDs describe** — this is a documentation registration gap, not a functional gap.

---

## Anti-Patterns Found

| File | Pattern | Severity | Assessment |
|------|---------|----------|-----------|
| `src/pam/api/routes/ingest.py` lines 192-202 | `sync_graph` endpoint calls `extract_graph_for_document` without `vdb_store` or `embedder` | INFO | The `sync-graph` endpoint (retry path for failed documents) does not pass `vdb_store` to the extraction function. Graph sync retries will not update entity/relationship VDB indices. This is consistent with the existing pattern (sync_graph was not modified in this phase) but means VDB indices won't be updated on graph sync retries — only on initial ingestion. Not a blocker for the phase goal, but a known limitation. |

No blocker anti-patterns found. No TODO/FIXME/placeholder comments in phase files. No stub implementations.

---

## Human Verification Required

### 1. VDB Index Creation on Server Start

**Test:** Start the FastAPI server (`uvicorn pam.api.main:app`) with a running Elasticsearch instance and verify that `pam_entities` and `pam_relationships` indices are created.
**Expected:** Server logs show `vdb_index_created` events for both indices (or `vdb_index_exists` if already present). Both indices visible in Kibana or `curl localhost:9200/_cat/indices`.
**Why human:** Requires live Elasticsearch instance; cannot verify index creation from code alone.

### 2. Entity/Relationship Embedding After Ingestion

**Test:** Ingest a markdown document with graph extraction enabled. After ingestion completes, query `curl localhost:9200/pam_entities/_search` and `curl localhost:9200/pam_relationships/_search`.
**Expected:** Entity records appear in `pam_entities` with `name`, `entity_type`, `description`, non-empty `embedding` (1536 floats), and `source_ids`. Relationship records appear in `pam_relationships` with `src_entity`, `tgt_entity`, `rel_type`, non-empty `embedding`.
**Why human:** Requires live Neo4j + Elasticsearch + OpenAI embedder; integration can only be confirmed end-to-end.

### 3. Semantic Entity Discovery via smart_search

**Test:** After ingesting documents, call `smart_search` with a query like "find teams working on deployment" where the exact team name is not known.
**Expected:** The `## Entity Matches` section returns relevant entities by semantic similarity, not just keyword match. The entities discovered are meaningfully related to the query concept.
**Why human:** Semantic relevance quality cannot be verified programmatically — requires judgment about whether retrieved entities are genuinely relevant.

### 4. Content Hash Skip-Re-Embedding

**Test:** Ingest the same document twice. On second ingestion, check server logs for `vdb_entities_all_unchanged` or `vdb_relationships_all_unchanged` log events.
**Expected:** No new embedding API calls for unchanged entities/relationships on re-ingestion. Log shows `skipped=N` equal to total entity count.
**Why human:** Requires observing live embedding API call counts across two ingestion runs.

---

## Commits Verified

| Commit | Description | Status |
|--------|-------------|--------|
| `76f2e6f` | feat(13-01): add EntityRelationshipVDBStore with ES index mappings and config | EXISTS |
| `91b0c84` | feat(13-01): integrate VDB upsert into graph extraction pipeline and wire lifespan | EXISTS |
| `4571268` | feat(13-02): add kNN search methods to VDB store and wire into agent | EXISTS |
| `281de3e` | feat(13-02): extend smart_search to 4-way concurrent search with VDB results | EXISTS |

---

## Test Results

```
tests/test_agent/test_smart_search_vdb.py - 13 passed in 1.52s
  TestConfigDefaults::test_entity_limit_default              PASSED
  TestConfigDefaults::test_relationship_limit_default         PASSED
  TestSmartSearchVDBIntegration::test_smart_search_without_vdb_store_still_works  PASSED
  TestSmartSearchVDBIntegration::test_smart_search_reuses_query_embeddings         PASSED
  TestSmartSearchVDBIntegration::test_smart_search_has_all_4_sections              PASSED
  TestSmartSearchVDBIntegration::test_smart_search_includes_entity_section         PASSED
  TestSmartSearchVDBIntegration::test_smart_search_vdb_failure_graceful            PASSED
  TestSmartSearchVDBIntegration::test_smart_search_includes_relationship_section   PASSED
  TestVDBStoreSearchMethods::test_search_entities_with_entity_type_filter          PASSED
  TestVDBStoreSearchMethods::test_search_entities_handles_missing_index            PASSED
  TestVDBStoreSearchMethods::test_search_relationships_handles_missing_index       PASSED
  TestVDBStoreSearchMethods::test_search_entities_returns_list                     PASSED
  TestVDBStoreSearchMethods::test_search_relationships_returns_list                PASSED
```

All files pass `python -m py_compile` and `ruff check`.

---

_Verified: 2026-02-24T15:55:00Z_
_Verifier: Claude (gsd-verifier)_
