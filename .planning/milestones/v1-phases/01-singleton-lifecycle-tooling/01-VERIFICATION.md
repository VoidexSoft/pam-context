---
phase: 01-singleton-lifecycle-tooling
verified: 2026-02-16T00:00:00Z
status: gaps_found
score: 4/5
gaps:
  - truth: "Ruff and mypy run with expanded rule sets and the codebase passes cleanly"
    status: failed
    reason: "mypy reports 6 no-any-return errors in deps.py from accessing request.app.state attributes (typed as Any)"
    artifacts:
      - path: "src/pam/api/deps.py"
        issue: "All dependency functions that read from request.app.state trigger no-any-return warnings"
    missing:
      - "Add type annotations to app.state attributes or add # type: ignore[no-any-return] comments to deps.py"
---

# Phase 1: Singleton Lifecycle + Tooling Verification Report

**Phase Goal:** Services initialize reliably via FastAPI lifespan, tests run in full isolation, and expanded linting catches bug patterns across the codebase

**Verified:** 2026-02-16T00:00:00Z
**Status:** gaps_found
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth                                                                                                                                                    | Status      | Evidence                                                                                                                  |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1   | All service singletons live on app.state and are created in FastAPI lifespan -- no module-level globals remain in deps.py                               | ✓ VERIFIED  | main.py lifespan creates all 9 singletons; deps.py has zero module-level globals (verified via grep)                     |
| 2   | deps.py dependency functions read exclusively from request.app.state with zero module-level singleton state                                             | ✓ VERIFIED  | All 9 dependency functions read from request.app.state (9 occurrences confirmed); zero module-level state                |
| 3   | CacheService, task_manager, and all service constructors accept config as explicit parameters with no hidden settings imports                           | ✓ VERIFIED  | All 8 service modules have no settings imports; CacheService and task_manager accept explicit params                     |
| 4   | Running `pytest -p randomly` passes all 450+ tests with no order-dependent failures                                                                     | ✓ VERIFIED  | 464 tests pass with seeds 12345 and 67890; no order-dependent failures                                                    |
| 5   | Ruff and mypy run with expanded rule sets (B, S, SIM, ARG, PT, RET, PERF, RUF for Ruff; check_untyped_defs, plugins for mypy) and the codebase passes cleanly | ✗ FAILED    | Ruff passes with all rules enabled; mypy reports 6 no-any-return errors in deps.py from accessing request.app.state      |

**Score:** 4/5 truths verified

### Required Artifacts

| Artifact                                  | Expected                                              | Status      | Details                                                                                       |
| ----------------------------------------- | ----------------------------------------------------- | ----------- | --------------------------------------------------------------------------------------------- |
| `pyproject.toml`                          | Expanded ruff and mypy configuration                  | ✓ VERIFIED  | Ruff: B, S, SIM, ARG, PT, RET, PERF, RUF enabled; mypy: check_untyped_defs, plugins added    |
| `src/pam/api/main.py`                     | Complete lifespan handler creating all singletons     | ✓ VERIFIED  | Creates 9 singletons: db_engine, session_factory, es_client, redis_client, cache_service, embedder, reranker, search_service, duckdb_service |
| `src/pam/api/deps.py`                     | Stateless dependency functions reading from app.state | ✓ VERIFIED  | 9 dependency functions, zero module-level globals, all read from request.app.state           |
| `src/pam/common/cache.py`                 | CacheService with required TTL params                 | ✓ VERIFIED  | TTL params are required; no settings fallback; no module-level Redis globals                  |
| `src/pam/ingestion/stores/elasticsearch_store.py` | Lazy INDEX_MAPPING via function                       | ✓ VERIFIED  | get_index_mapping(embedding_dims) function defined and used in ensure_index                   |
| `src/pam/agent/duckdb_service.py`         | Stale cache invalidation + explicit config            | ✓ VERIFIED  | _needs_refresh() method checks mtime; used in execute_query and list_tables                   |
| `src/pam/ingestion/task_manager.py`       | Task manager with injected dependencies               | ✓ VERIFIED  | spawn_ingestion_task accepts session_factory and cache_service parameters                     |

### Key Link Verification

| From                               | To                                    | Via                                              | Status     | Details                                                                         |
| ---------------------------------- | ------------------------------------- | ------------------------------------------------ | ---------- | ------------------------------------------------------------------------------- |
| `src/pam/api/deps.py`              | `request.app.state`                   | All dependency functions read from app.state    | ✓ WIRED    | 9 occurrences of request.app.state in deps.py                                   |
| `src/pam/api/main.py`              | `app.state` assignments               | Lifespan creates and stores all singletons       | ✓ WIRED    | 17 occurrences of app.state in main.py (9 assignments + cleanup)               |
| `src/pam/ingestion/task_manager.py`| `session_factory` parameter           | spawn/run accept session_factory                 | ✓ WIRED    | Both functions accept session_factory, used in 5 async with blocks             |
| `src/pam/api/routes/ingest.py`     | `src/pam/ingestion/task_manager.py`   | Passes session_factory from app.state            | ✓ WIRED    | spawn_ingestion_task called with request.app.state.session_factory             |
| `elasticsearch_store.py`           | `get_index_mapping` function          | ensure_index calls get_index_mapping             | ✓ WIRED    | ensure_index() calls get_index_mapping(self._embedding_dims)                    |
| `duckdb_service.py`                | `_needs_refresh` mtime check          | Called before queries                            | ✓ WIRED    | _needs_refresh() called in execute_query and list_tables                        |

### Requirements Coverage

Phase 1 addresses requirements SING-01 through SING-08 and TOOL-01, TOOL-02 from REQUIREMENTS.md (not verified - REQUIREMENTS.md not provided).

### Anti-Patterns Found

**None found.** All modified files clean:
- No TODO/FIXME/HACK/PLACEHOLDER comments
- No empty implementations (return null/empty)
- No console.log-only functions
- All service constructors are substantive implementations

### Human Verification Required

**None required.** All verification can be done programmatically via:
- Static analysis (grep for globals, settings imports)
- Linting (ruff, mypy)
- Test execution (pytest with randomization)

### Gaps Summary

**Truth 5 (mypy passes cleanly) has ONE gap:**

The refactored deps.py reads from `request.app.state.*` which is typed as `Any` in FastAPI's State class. This triggers 6 `no-any-return` mypy errors:
- `get_es_client` returns `request.app.state.es_client` (typed as Any)
- `get_embedder` returns `request.app.state.embedder` (typed as Any)
- `get_search_service` returns `request.app.state.search_service` (typed as Any)
- `get_reranker` returns `request.app.state.reranker` (typed as Any)
- `get_duckdb_service` returns `request.app.state.duckdb_service` (typed as Any)
- `get_cache_service` returns `request.app.state.cache_service` (typed as Any)

**Root cause:** FastAPI's `app.state` is an instance of `starlette.datastructures.State` which uses `__setattr__` and `__getattr__` magic methods, making all attribute access return `Any`.

**Impact:** Mypy cannot verify type safety of values returned from dependency functions. This reduces type safety downstream but does not affect runtime behavior.

**Fix options:**
1. Add `# type: ignore[no-any-return]` to each return statement in deps.py (6 lines)
2. Create a typed wrapper class for app.state with proper type annotations
3. Use `cast()` to explicitly type each `request.app.state.*` access

**Recommendation:** Option 1 (type ignore) is the standard FastAPI pattern. Option 2 would require significant refactoring. Option 3 is verbose but maintains type safety.

**All other aspects verified:**
- ✓ All singletons created in lifespan
- ✓ deps.py fully stateless (zero globals)
- ✓ All service constructors accept explicit config
- ✓ 464 tests pass with random ordering
- ✓ Ruff passes with expanded rule set (B, S, SIM, ARG, PT, RET, PERF, RUF)
- ✓ INDEX_MAPPING lazily computed
- ✓ DuckDB stale cache detection working
- ✓ task_manager accepts injected dependencies
- ✓ No anti-patterns found

**Gap is minor and has standard fix.** Phase goal substantially achieved.

---

_Verified: 2026-02-16T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
