---
phase: 01-singleton-lifecycle-tooling
plan: 01
subsystem: infra
tags: [ruff, mypy, pydantic, fastapi, duckdb, elasticsearch]

requires: []
provides:
  - Expanded ruff rule set (B, S, SIM, ARG, PT, RET, PERF, RUF)
  - Expanded mypy configuration (check_untyped_defs, warn_unreachable, pydantic.mypy)
  - All 8 service constructors accept explicit config (no settings fallback)
  - Lazy get_index_mapping() function replacing module-level INDEX_MAPPING constant
  - DuckDB stale cache detection via _needs_refresh() mtime check
affects: [01-02-PLAN]

tech-stack:
  added: [pytest-randomly]
  patterns: [explicit-config-injection, lazy-initialization]

key-files:
  created: []
  modified:
    - pyproject.toml
    - src/pam/ingestion/stores/elasticsearch_store.py
    - src/pam/agent/duckdb_service.py
    - src/pam/common/cache.py
    - src/pam/ingestion/embedders/openai_embedder.py
    - src/pam/ingestion/chunkers/hybrid_chunker.py
    - src/pam/retrieval/hybrid_search.py
    - src/pam/retrieval/haystack_search.py
    - src/pam/agent/agent.py

key-decisions:
  - "Excluded FAST rule category from ruff (38 Annotated migration violations deferred)"
  - "Kept settings import in cache.py only for get_redis() (addressed in Plan 02)"

patterns-established:
  - "Explicit config injection: all service constructors take required config params, no settings fallback"
  - "Lazy initialization: INDEX_MAPPING computed via get_index_mapping(dims) function call"

duration: 18min
completed: 2026-02-15
---

# Plan 01-01: Linting Expansion + Explicit Config Summary

**Expanded ruff/mypy rule sets across codebase and eliminated hidden settings dependencies from all 8 service constructors**

## Performance

- **Duration:** 18 min
- **Tasks:** 2
- **Files modified:** 29 (Task 1) + 22 (Task 2)

## Accomplishments
- Ruff expanded with B, S, SIM, ARG, PT, RET, PERF, RUF rules — all violations fixed
- mypy configured with check_untyped_defs, warn_unreachable, pydantic.mypy plugin — passes cleanly
- All 8 service modules (CacheService, ElasticsearchStore, OpenAIEmbedder, HybridChunker, HybridSearchService, HaystackSearchService, RetrievalAgent, DuckDBService) now accept explicit config params
- INDEX_MAPPING converted to lazy get_index_mapping(embedding_dims) function
- DuckDB _needs_refresh() mtime-based stale cache detection added
- All 458 tests passing

## Task Commits

1. **Task 1: Expand ruff and mypy configuration** - `44a9029` (chore)
2. **Task 2: Make all service constructors accept explicit config** - `249f2b0` (refactor)

## Decisions Made
- Excluded FAST ruff category (38 violations requiring Annotated migration — deferred)
- Kept `settings` import in cache.py for `get_redis()` — removed in Plan 02
- Added `# noqa: S608` to DuckDB SQL construction (intentional with guards)

## Deviations from Plan
None significant — executor missed a few test call sites which were fixed during spot-check.

## Issues Encountered
- Several test files needed manual fixup for updated constructor signatures (DuckDBService missing max_rows, RetrievalAgent missing api_key/model, chunk_document missing max_tokens)
- Cost tracking test assertion adjusted for low-cost embedding model

## Next Phase Readiness
- All service constructors ready for lifespan-based initialization (Plan 01-02)
- No blockers

---
*Phase: 01-singleton-lifecycle-tooling*
*Completed: 2026-02-15*
