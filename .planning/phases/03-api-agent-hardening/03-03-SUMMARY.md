---
phase: 03-api-agent-hardening
plan: 03
subsystem: agent, retrieval, api
tags: [protocol, structlog, sha256, tool-schema, type-safety]

# Dependency graph
requires:
  - phase: 01-singleton-lifecycle-tooling
    provides: Service singletons on app.state, deps.py injection pattern
provides:
  - Corrected QUERY_DATABASE_TOOL schema with empty required
  - CostTracker unknown model warning log
  - Full SHA-256 cache key hashing (collision-resistant)
  - SearchService Protocol for type-safe search backend polymorphism
  - Post-rerank logging in hybrid_search.py
affects: [api, agent, retrieval]

# Tech tracking
tech-stack:
  added: []
  patterns: [typing.Protocol for structural subtyping, runtime_checkable Protocol]

key-files:
  created:
    - src/pam/retrieval/search_protocol.py
  modified:
    - src/pam/agent/tools.py
    - src/pam/common/logging.py
    - src/pam/common/cache.py
    - src/pam/retrieval/hybrid_search.py
    - src/pam/api/deps.py

key-decisions:
  - "Protocol over ABC for SearchService: structural subtyping without inheritance changes"
  - "runtime_checkable enables isinstance() checks at runtime"
  - "Empty required list (not missing key) for QUERY_DATABASE_TOOL to be explicit"

patterns-established:
  - "Protocol for service interfaces: use typing.Protocol with @runtime_checkable for polymorphic services"

# Metrics
duration: 2min
completed: 2026-02-16
---

# Phase 03 Plan 03: Agent & Retrieval Correctness Fixes Summary

**Fixed tool schemas, CostTracker unknown-model warning, full SHA-256 cache keys, post-rerank logging, and SearchService Protocol for type-safe search backend polymorphism**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-16T07:44:22Z
- **Completed:** 2026-02-16T07:47:13Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- QUERY_DATABASE_TOOL required field fixed from `["sql"]` to `[]` so Claude can call `list_tables` without providing SQL
- CostTracker now logs a warning with the model name when encountering unknown models instead of silently falling back
- Cache key hash uses full 64-character SHA-256 digest instead of truncated 16 characters
- SearchService Protocol enables type-safe polymorphism between HybridSearchService and HaystackSearchService
- hybrid_search.py log emitted after reranking so result count reflects final results
- deps.py get_search_service returns SearchService type (correct for both backends)

## Task Commits

Each task was committed atomically:

1. **Task 1: Fix tool schemas, CostTracker warning, and cache key hash** - `996d3d2` (fix)
2. **Task 2: Define SearchService Protocol, move hybrid_search log, update deps.py types** - `e333617` (feat)

## Files Created/Modified
- `src/pam/agent/tools.py` - QUERY_DATABASE_TOOL required changed to empty list
- `src/pam/common/logging.py` - CostTracker._estimate_cost warns on unknown model
- `src/pam/common/cache.py` - _make_search_key uses full SHA-256 hexdigest
- `src/pam/retrieval/search_protocol.py` - New SearchService Protocol with runtime_checkable
- `src/pam/retrieval/hybrid_search.py` - Log moved after reranker block
- `src/pam/api/deps.py` - Return type changed to SearchService, removed HybridSearchService import

## Decisions Made
- Used Protocol (not ABC) for SearchService: both search services already share the same shape without inheritance, and Protocol captures this via structural subtyping
- Used @runtime_checkable to enable isinstance() checks if needed downstream
- Set QUERY_DATABASE_TOOL required to `[]` (explicit empty list) rather than removing the key entirely, matching the pattern of being explicit

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All agent/retrieval correctness fixes complete
- Phase 03 plans ready for independent execution (wave 1, no dependencies between plans)
- Full test suite (469 tests) passes

## Self-Check: PASSED

All 6 files verified present. Both commit hashes (996d3d2, e333617) verified in git log.

---
*Phase: 03-api-agent-hardening*
*Completed: 2026-02-16*
