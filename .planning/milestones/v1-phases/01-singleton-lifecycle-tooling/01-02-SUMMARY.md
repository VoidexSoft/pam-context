---
phase: 01-singleton-lifecycle-tooling
plan: 02
subsystem: api
tags: [fastapi, lifespan, dependency-injection, redis, elasticsearch, singleton]

requires:
  - phase: 01-01
    provides: All service constructors accept explicit config params (no settings fallback)
provides:
  - Stateless deps.py with zero module-level globals
  - Complete lifespan handler creating all 9 singletons on app.state
  - task_manager with injected session_factory and cache_service
  - cache.py with no module-level Redis client globals
affects: [02-database-integrity]

tech-stack:
  added: []
  patterns: [lifespan-singleton-creation, app-state-dependency-injection, stateless-deps]

key-files:
  created: []
  modified:
    - src/pam/api/main.py
    - src/pam/api/deps.py
    - src/pam/common/cache.py
    - src/pam/ingestion/task_manager.py
    - src/pam/api/routes/ingest.py
    - tests/test_api/conftest.py
    - tests/test_api/test_deps.py
    - tests/test_api/test_health.py
    - tests/test_common/test_cache.py
    - tests/test_ingestion/test_task_manager.py

key-decisions:
  - "Store anthropic_api_key and agent_model on app.state for deps.py agent creation (avoids settings import in deps.py)"
  - "ping_redis() now accepts client parameter instead of calling get_redis() internally"
  - "Health endpoint reads redis_client directly from request.app.state (no ping_redis wrapper)"

patterns-established:
  - "Lifespan singleton: all services created in async lifespan context manager and stored on app.state"
  - "Stateless deps: dependency functions are pure reads from request.app.state, no globals, no locks"
  - "Injected background deps: background tasks receive session_factory and cache_service as explicit parameters"

duration: 7min
completed: 2026-02-15
---

# Plan 01-02: Lifespan + Stateless Deps Migration Summary

**Migrated all service singletons from deps.py module-level globals to FastAPI lifespan + app.state, making deps.py fully stateless and task_manager dependency-injected**

## Performance

- **Duration:** 7 min
- **Started:** 2026-02-15T17:14:40Z
- **Completed:** 2026-02-15T17:22:00Z
- **Tasks:** 2
- **Files modified:** 10

## Accomplishments
- Expanded FastAPI lifespan to create all 9 singletons: db_engine, session_factory, es_client, redis_client, cache_service, embedder, reranker, search_service, duckdb_service
- Rewrote deps.py to be fully stateless: zero module-level globals, zero locks, all functions read from request.app.state
- Removed get_redis(), close_redis(), _redis_client, _redis_lock from cache.py
- Refactored task_manager to accept session_factory and cache_service as explicit parameters
- Updated ingest.py route to pass dependencies from app.state to spawn_ingestion_task
- All 464 tests passing including with randomized ordering (pytest-randomly seeds 12345 and 67890)

## Task Commits

Each task was committed atomically:

1. **Task 1: Expand lifespan, rewrite deps.py stateless, clean cache.py** - `1565912` (refactor)
2. **Task 2: Refactor task_manager with injected deps, update tests** - `3bbbd13` (refactor)

## Files Created/Modified
- `src/pam/api/main.py` - Complete lifespan handler creating all singletons, health endpoint reads redis from app.state
- `src/pam/api/deps.py` - Fully stateless: 9 dependency functions reading from request.app.state
- `src/pam/common/cache.py` - Removed module-level Redis globals; ping_redis accepts client param
- `src/pam/ingestion/task_manager.py` - spawn/run_ingestion_background accept session_factory + cache_service
- `src/pam/api/routes/ingest.py` - Passes session_factory and cache_service from app.state to task_manager
- `tests/test_api/conftest.py` - Sets app.state attributes for test fixtures
- `tests/test_api/test_deps.py` - Rewritten for stateless deps pattern (9 tests covering all dep functions)
- `tests/test_api/test_health.py` - Updated to set redis_client on app.state instead of patching ping_redis
- `tests/test_common/test_cache.py` - Removed TestGetRedisLock; updated TestPingRedis for new signature
- `tests/test_ingestion/test_task_manager.py` - Pass session_factory as parameter instead of patching global

## Decisions Made
- Stored anthropic_api_key and agent_model on app.state to avoid importing settings in deps.py
- Changed ping_redis() to accept a client parameter (instead of calling removed get_redis())
- Health endpoint reads redis_client directly from request.app.state (simpler than wrapper function)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed task_manager.py broken import in Task 1**
- **Found during:** Task 1 (cache.py cleanup)
- **Issue:** Removing get_redis() from cache.py broke task_manager.py import at module load time
- **Fix:** Removed get_redis import from task_manager.py; cache invalidation temporarily commented out (fully restored in Task 2 with cache_service injection)
- **Files modified:** src/pam/ingestion/task_manager.py
- **Verification:** pytest passes after fix
- **Committed in:** 1565912 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Necessary to keep tests passing after each task commit. No scope creep.

## Issues Encountered
None beyond the import fix documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 1 (Singleton Lifecycle + Tooling) is now complete
- All service singletons managed via lifespan, all deps stateless
- 464 tests passing with randomized ordering
- Ready for Phase 2: Database Integrity

---
*Phase: 01-singleton-lifecycle-tooling*
*Completed: 2026-02-15*
