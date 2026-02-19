# Project Research Summary

**Project:** PAM Context
**Domain:** Code quality cleanup and refactoring of an existing Python/FastAPI + React knowledge retrieval system
**Researched:** 2026-02-15
**Confidence:** HIGH

## Executive Summary

PAM Context is an operational knowledge retrieval system (Python 3.12, FastAPI, SQLAlchemy async, Elasticsearch 8.x, React 18) with 7 open GitHub issues totaling ~40 findings spanning database integrity, API correctness, singleton lifecycle management, streaming reliability, and frontend code quality. This is not a greenfield build -- it is a stabilization milestone against a working codebase with 450+ tests. The research unanimously points to a targeted, phased cleanup using the existing toolchain (Ruff, mypy, Alembic, pytest) with expanded configurations rather than introducing new frameworks or dependencies.

The recommended approach is a four-phase refactoring ordered by dependency depth: (1) fix singleton lifecycle management in `deps.py` by migrating module-level globals to FastAPI's `app.state` via the lifespan pattern, (2) add missing database indexes via a carefully written Alembic migration using `CREATE INDEX CONCURRENTLY`, (3) harden API routes with response models, pagination, and streaming error handling, and (4) fix frontend React issues (array keys, useCallback, polling). Each phase is designed to be independently shippable and testable. The architecture research confirms that the existing proxy pattern in `config.py` and `database.py` is sound and should be preserved -- the refactoring targets only the `deps.py` globals.

The primary risks are: singleton reset leaks breaking the 450+ test suite (mitigate by adding `reset_*()` functions and running tests with randomized ordering after each phase), Alembic migrations locking production tables (mitigate with `CONCURRENTLY` and checking existing indexes from `001_initial_schema.py`), and `response_model` additions silently dropping fields from existing API responses (mitigate by snapshotting current responses before adding Pydantic models). All three risks have straightforward prevention strategies documented in the pitfalls research.

## Key Findings

### Recommended Stack

No new production dependencies are needed. The entire milestone is configuration changes and code refactoring using existing tools. See [STACK.md](./STACK.md) for full details.

**Core tooling changes:**
- **Ruff (expand rule set):** Add `B`, `S`, `SIM`, `ARG`, `FAST`, `PT`, `RET`, `PERF`, `RUF` rules to catch the exact bug patterns found in open issues. Stay on 0.14.x -- do NOT upgrade to 0.15+ (new 2026 formatting style creates massive diffs).
- **mypy (tighten config):** Enable `check_untyped_defs`, `warn_unreachable`, `disallow_any_generics`, and add `pydantic.mypy` + `sqlalchemy.ext.mypy.plugin` plugins. Do NOT enable `strict = true`.
- **Alembic (index migration):** Use `CREATE INDEX CONCURRENTLY` with `op.execute("COMMIT")` for non-transactional context. Check `001_initial_schema.py` first -- some indexes already exist.
- **vulture + complexipy (one-time diagnostic):** Run once to identify dead code and high-complexity functions. Do NOT add to CI.
- **Pure ASGI middleware:** Replace `BaseHTTPMiddleware` to fix SSE streaming buffering. No third-party framework needed.

### Expected Features

See [FEATURES.md](./FEATURES.md) for the full feature landscape with 40+ items.

**Must have (table stakes):**
- Database indexes on `Segment.document_id` and `Document.content_hash` -- highest-impact single fix
- `response_model` on 5+ endpoints missing OpenAPI schema and validation
- Pagination on `list_documents` -- currently returns ALL documents
- Pure ASGI middleware replacing `BaseHTTPMiddleware` -- fixes broken SSE streaming
- `required` fields on agent tool schemas -- prevents silent failures
- Streaming error handling -- SSE errors sent as structured events, not silent drops
- Fix `INDEX_MAPPING` import-time settings read in `elasticsearch_store.py`
- Fix stale DuckDB table cache and stale Redis reference in search service singleton

**Should have (differentiators):**
- `Protocol` interface for search services (type-safe polymorphism)
- React key, useCallback, and polling fixes
- Dead code removal (CitationLink.tsx, require_auth, unused variables)
- Accessibility labels on interactive elements
- Test coverage for `configure_logging()`, `close_redis()` edge cases, empty chunk list

**Defer:**
- Comprehensive frontend test coverage (hooks, components)
- Eval module improvements (division by zero, keyword overlap heuristic)
- ESLint for frontend
- Redis Sentinel/Cluster support
- Full type annotation pass (`mypy strict = true`)

### Architecture Approach

The codebase uses three singleton patterns: (1) proxy + `lru_cache` for settings and database (good, keep), (2) module-level globals with `asyncio.Lock` for service singletons in `deps.py` (problematic, refactor), and (3) lifespan + `app.state` for ES and Redis clients (ideal, expand). The refactoring consolidates everything onto pattern 3 for service singletons while preserving pattern 1 for settings. See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full dependency graph and target state.

**Major components and refactoring scope:**
1. **`main.py` lifespan** -- becomes the single point of service creation (embedder, reranker, search service, DuckDB, DB engine)
2. **`deps.py`** -- transforms from global-holding module to thin `request.app.state.X` lookups with no module-level state
3. **`config.py` / `database.py`** -- preserved as-is (proxy + lru_cache pattern is already correct)
4. **Service constructors** -- all config passed as explicit parameters, no hidden `settings` reads
5. **`task_manager.py`** -- receives `session_factory` as explicit parameter instead of importing it

### Critical Pitfalls

See [PITFALLS.md](./PITFALLS.md) for 10 pitfalls with detailed prevention strategies.

1. **Singleton reset leaks between tests** -- every singleton must have a `reset_*()` function called in an `autouse` fixture. Run `pytest -p randomly` after each phase. This is the single highest-risk pitfall because it can silently break dozens of tests.
2. **Alembic migration locks production tables** -- use `CREATE INDEX CONCURRENTLY` and verify which indexes already exist in `001_initial_schema.py`. The segments table is the largest and most dangerous to lock.
3. **Breaking the proxy pattern contract** -- grep for module-level `= settings.X` captures before refactoring. All settings access must go through the proxy at call time, never captured eagerly.
4. **SSE streaming swallows errors silently** -- wrap generators in try/except and yield structured error events. The frontend already handles error event types.
5. **deps.py DI graph breaks with lru_cache on Request-accepting functions** -- do NOT use `lru_cache` on functions that take `Request`. Use `app.state` via lifespan instead. This is the most subtle architectural pitfall.

## Implications for Roadmap

Based on combined research, the milestone should be structured as 4 phases ordered by dependency depth and risk profile. The architecture research provides a precise refactoring order that avoids breaking the test suite.

### Phase 1: Singleton Lifecycle and Tooling Configuration
**Rationale:** Everything else depends on a stable test foundation. Singleton refactoring is the riskiest change (touches deps.py which is imported by every route), so it should be done first when the codebase is cleanest. Ruff/mypy config expansion runs in parallel as a zero-risk change that catches issues in subsequent phases.
**Delivers:** Service singletons on `app.state`, expanded linting catching bug patterns, tighter type checking, reliable test isolation.
**Addresses:** Issue #32 (singleton lifecycle), #36 (ES INDEX_MAPPING import-time), #43 (stale Redis reference). Ruff expansion catches patterns from #36, #39, #43.
**Avoids:** Pitfall 1 (singleton reset leaks), Pitfall 3 (proxy pattern breaks), Pitfall 6 (DI graph breaks).
**Architecture phases covered:** Architecture Phase 1 (CacheService constructor), Phase 2 (DB engine to app.state), Phase 3 (service singletons to app.state), Phase 4 (remove settings fallbacks).

### Phase 2: Database Integrity
**Rationale:** Indexes are the highest-impact single fix (every document view and delete hits the un-indexed FK). Independent of API changes. Should be done early because index creation on a growing dataset gets slower over time.
**Delivers:** Missing database indexes via Alembic migration, CHECK constraint on UserProjectRole.role.
**Addresses:** Issue #39 (missing indexes, CHECK constraint).
**Avoids:** Pitfall 2 (migration locks tables), Pitfall 9 (concurrent migrations in CI).
**Key check:** Verify existing indexes in `001_initial_schema.py` before writing migration. The `idx_segments_document_id` index may already exist.

### Phase 3: API Hardening and Streaming
**Rationale:** Depends on Phase 1 (middleware refactoring requires stable app startup). Groups all API-layer changes together for a coherent review. Streaming fixes should precede response_model changes because streaming is the primary user-facing endpoint.
**Delivers:** Pure ASGI middleware (fixes SSE), response models on 5+ endpoints, pagination on list_documents, streaming error handling, small API bug fixes (revoke_role 404, get_me semantics, get_stats error indicator, get_segment JOIN).
**Addresses:** Issues #43 (middleware, response_model, pagination, bug fixes), #37 (tool schema required fields, chunk_text spacing).
**Avoids:** Pitfall 4 (SSE error swallowing), Pitfall 7 (response_model breaks clients).

### Phase 4: Frontend Fixes and Cleanup
**Rationale:** Frontend changes are independent of backend and lowest risk. Grouped last because they require manual visual verification. Dead code removal across the full codebase is a clean final pass.
**Delivers:** Stable React keys, useCallback optimization, polling fix, dead code removal (CitationLink.tsx, require_auth, unused variables), accessibility labels.
**Addresses:** Issue #40 (all frontend items), #36 (unused orig_idx), #43 (dead require_auth).
**Avoids:** Pitfall 5 (React array key issues), Pitfall 8 (useCallback stale closures), Pitfall 10 (polling timer leak).

### Phase Ordering Rationale

- **Phase 1 before Phase 3** because the ASGI middleware conversion and response_model changes depend on a stable app startup flow. If singletons are still using module-level globals during middleware refactoring, test isolation becomes unreliable.
- **Phase 2 is independent** and could theoretically run in parallel with Phase 1, but keeping them sequential reduces blast radius and simplifies debugging if tests break.
- **Phase 3 groups all API changes** because response_model additions, pagination, and streaming fixes all touch the routes layer. A single review pass catches cross-cutting issues.
- **Phase 4 is last** because frontend fixes have zero backend dependencies and benefit from all backend fixes being stable.
- **Test coverage gaps are addressed opportunistically** within each phase, not as a separate phase. When touching a file, add missing tests for that file.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** The singleton-to-app.state migration has a precise 4-step order documented in ARCHITECTURE.md. Follow it exactly. The `task_manager.py` change (passing session_factory explicitly) needs careful attention because background tasks run outside the request lifecycle.
- **Phase 3:** Response model additions require snapshotting current responses before adding Pydantic models. The streaming error handling needs testing with a killed LLM API mid-stream.

Phases with standard patterns (skip research-phase):
- **Phase 2:** Database index creation via Alembic is well-documented. The only nuance is checking existing indexes and using `CONCURRENTLY`. No further research needed.
- **Phase 4:** React key fixes, useCallback, and dead code removal are standard patterns. No research needed.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All recommendations are configuration changes to already-installed tools. Official docs verified for Ruff, mypy, Alembic, FastAPI. No new dependencies. |
| Features | HIGH | All 40+ items verified against actual source code and 7 open GitHub issues. Feature dependencies mapped. |
| Architecture | HIGH | Based on direct codebase analysis of all singleton patterns, dependency graphs, and existing test patterns. Target architecture follows FastAPI's officially recommended patterns. |
| Pitfalls | HIGH | All 10 pitfalls verified against codebase. Recovery strategies included. Phase-to-pitfall mapping is explicit. |

**Overall confidence:** HIGH

### Gaps to Address

- **Existing index verification:** The pitfalls research flags that `001_initial_schema.py` already creates `idx_segments_document_id`, `idx_segments_content_hash`, and `idx_documents_source`. Before writing the Phase 2 migration, run `\di` in psql to confirm which indexes actually exist. Some "missing" indexes from Issue #39 may already be present, making the migration a partial no-op.
- **Streaming error reproduction:** No automated test currently kills the LLM API mid-stream. Phase 3 should include a test that mocks an Anthropic API failure during streaming to verify the error event path.
- **Frontend test infrastructure:** The research defers comprehensive frontend testing, but the React fixes in Phase 4 should be manually verified with React DevTools Profiler and StrictMode. If the project later needs frontend CI, ESLint and React Testing Library would be the additions.
- **CostTracker pricing accuracy:** The hardcoded pricing in CostTracker is flagged as stale but marked low priority. Consider making it configurable or adding a warning log for unknown models during Phase 3.

## Sources

### Primary (HIGH confidence)
- [Ruff Rules Reference](https://docs.astral.sh/ruff/rules/) -- rule categories, FastAPI-specific rules
- [Ruff Configuration Guide](https://docs.astral.sh/ruff/configuration/) -- per-file ignores, select syntax
- [mypy Configuration File](https://mypy.readthedocs.io/en/stable/config_file.html) -- plugin support, per-module overrides
- [SQLAlchemy 2.0 Constraints and Indexes](https://docs.sqlalchemy.org/en/20/core/constraints.html) -- mapped_column index=True, __table_args__
- [Alembic Autogenerate Docs](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) -- index migration patterns
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) -- app.state singleton pattern
- [FastAPI Response Model](https://fastapi.tiangolo.com/tutorial/response-model/) -- return type annotations vs response_model
- [FastAPI Settings and Environment Variables](https://fastapi.tiangolo.com/advanced/settings/) -- lru_cache + Depends pattern
- [Starlette Middleware](https://starlette.dev/middleware/) -- pure ASGI middleware pattern
- [PostgreSQL CREATE INDEX documentation](https://www.postgresql.org/docs/16/sql-createindex.html) -- CONCURRENTLY option, lock behavior
- [React documentation on keys and reconciliation](https://react.dev/learn/rendering-lists#rules-of-keys) -- stable key requirements
- Direct codebase analysis of `src/pam/` -- all findings verified against source

### Secondary (MEDIUM confidence)
- [FastAPI Discussion #8054: DI Singleton](https://github.com/fastapi/fastapi/discussions/8054) -- community consensus on app.state
- [BaseHTTPMiddleware Deprecation Discussion](https://github.com/Kludex/starlette/discussions/2160) -- streaming buffering issue
- [vulture on GitHub](https://github.com/jendrikseipp/vulture) -- dead code detection
- [complexipy on PyPI](https://pypi.org/project/complexipy/) -- cognitive complexity analysis
- [CYBERTEC: Index your Foreign Key](https://www.cybertec-postgresql.com/en/index-your-foreign-key/) -- PostgreSQL FK indexing behavior

---
*Research completed: 2026-02-15*
*Ready for roadmap: yes*
