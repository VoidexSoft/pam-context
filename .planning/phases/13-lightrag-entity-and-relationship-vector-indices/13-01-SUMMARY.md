---
phase: 13-lightrag-entity-and-relationship-vector-indices
plan: 01
subsystem: ingestion
tags: [elasticsearch, vector-db, embeddings, lightrag, entity-extraction]

# Dependency graph
requires:
  - phase: 07-ingestion-pipeline-extension-diff-engine
    provides: graph extraction pipeline with entity/relationship accumulation
  - phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool
    provides: smart_search infrastructure and config patterns
provides:
  - EntityRelationshipVDBStore with ES index mappings for pam_entities and pam_relationships
  - Content-hash skip-re-embedding optimization for entity/relationship embeddings
  - VDB upsert integration in graph extraction pipeline
  - Full ingestion chain wiring (lifespan -> app.state -> route -> task_manager -> pipeline -> extraction)
affects: [13-02, 14-lightrag-graph-aware-context-assembly, 15-lightrag-retrieval-mode-router]

# Tech tracking
tech-stack:
  added: []
  patterns: [content-hash skip-re-embedding, LightRAG embedding text formats, non-blocking VDB upsert]

key-files:
  created:
    - src/pam/ingestion/stores/entity_relationship_store.py
  modified:
    - src/pam/common/config.py
    - src/pam/graph/extraction.py
    - src/pam/api/main.py
    - src/pam/ingestion/pipeline.py
    - src/pam/ingestion/task_manager.py
    - src/pam/api/routes/ingest.py

key-decisions:
  - "LightRAG embedding text format: entities use 'name\\ndescription', relationships use 'keywords\\tsrc\\ntgt\\ndescription'"
  - "Content hash comparison via SHA-256 on embedding text to skip re-embedding unchanged entities/relationships"
  - "VDB upsert is non-blocking (try/except) consistent with existing graph extraction fault isolation pattern"
  - "make_relationship_doc_id sorts entity names alphabetically for undirected relationship dedup"

patterns-established:
  - "VDB store follows same optional wiring pattern as graph_service through full ingestion chain"
  - "Entity/relationship accumulation across chunks via uuid_to_name map and all_edges dict"

requirements-completed:
  - VDB-01
  - VDB-02
  - VDB-03

# Metrics
duration: 4min
completed: 2026-02-24
---

# Phase 13 Plan 01: Entity & Relationship Vector Indices Summary

**EntityRelationshipVDBStore with ES pam_entities/pam_relationships indices, content-hash skip-re-embedding, and full ingestion chain integration**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-24T15:31:56Z
- **Completed:** 2026-02-24T15:36:00Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- EntityRelationshipVDBStore class with index mappings, ensure_indices, and batch upsert methods
- Content-hash-based skip-re-embedding optimization avoiding redundant embedding API calls
- Full VDB upsert integration into graph extraction pipeline with uuid-to-name resolution for edge endpoints
- Complete ingestion chain wiring from lifespan through to extraction function

## Task Commits

Each task was committed atomically:

1. **Task 1: Create EntityRelationshipVDBStore with index mappings, upsert methods, and config settings** - `76f2e6f` (feat)
2. **Task 2: Integrate VDB upsert into graph extraction pipeline and wire lifespan** - `91b0c84` (feat)

## Files Created/Modified
- `src/pam/ingestion/stores/entity_relationship_store.py` - EntityRelationshipVDBStore with full upsert pipeline (270 lines)
- `src/pam/common/config.py` - entity_index, relationship_index, smart_search_entity/relationship_limit settings
- `src/pam/graph/extraction.py` - VDB upsert integration after chunk loop, uuid_to_name map, edge accumulation
- `src/pam/api/main.py` - VDB store creation in lifespan with ensure_indices
- `src/pam/ingestion/pipeline.py` - vdb_store field on IngestionPipeline, passed to extraction
- `src/pam/ingestion/task_manager.py` - vdb_store parameter threaded through spawn/run functions
- `src/pam/api/routes/ingest.py` - vdb_store read from app.state and passed to spawn_ingestion_task

## Decisions Made
- LightRAG embedding text format: entities use "name\ndescription", relationships use "keywords\tsrc\ntgt\ndescription"
- Content hash comparison via SHA-256 on embedding text to skip re-embedding unchanged entities/relationships
- VDB upsert is non-blocking (try/except) consistent with existing graph extraction fault isolation pattern
- make_relationship_doc_id sorts entity names alphabetically for undirected relationship dedup
- Relationship weight derived from episode count (number of chunks mentioning the relationship)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Entity and relationship VDB indices are ready for semantic search in Plan 02
- Plan 02 can implement entity/relationship vector search using the pam_entities and pam_relationships indices
- smart_search_entity_limit and smart_search_relationship_limit config settings ready for search integration

## Self-Check: PASSED

All 7 files verified present. Both task commits (76f2e6f, 91b0c84) verified in git log.

---
*Phase: 13-lightrag-entity-and-relationship-vector-indices*
*Completed: 2026-02-24*
