# Pitfalls Research

**Domain:** Code cleanup/refactoring of Python/FastAPI + React knowledge retrieval system
**Researched:** 2026-02-15
**Confidence:** HIGH (based on direct codebase analysis + established patterns in SQLAlchemy, FastAPI, React, Alembic ecosystems)

---

## Critical Pitfalls

### Pitfall 1: Singleton Reset Leaks Between Tests

**What goes wrong:**
The codebase has 7+ module-level singletons spread across `deps.py`, `cache.py`, `database.py`, and `config.py`. Refactoring these to lazy initialization (lru_cache + proxy pattern, which `config.py` and `database.py` already use) is the right direction. But the critical mistake is failing to reset ALL singletons between tests. Currently `deps.py` uses raw `global` variables (`_embedder`, `_reranker`, `_search_service`, `_duckdb_service`) with no reset function. If one test initializes a singleton with a mock and another test expects a different configuration, the stale singleton leaks across test boundaries.

**Why it happens:**
When converting from `global` + `asyncio.Lock()` (current pattern in `deps.py`) to `lru_cache` (current pattern in `database.py` and `config.py`), developers add `lru_cache` but forget to expose a `reset_*()` function. Or they expose it but don't call it in test fixtures. With 450+ tests, a leaked singleton may only manifest as a flaky test that depends on execution order.

**How to avoid:**
1. Every module that holds a singleton MUST export a `reset_*()` function (follow the pattern already in `database.py:reset_database()` and `config.py:reset_settings()`).
2. Create a single `conftest.py` fixture that calls ALL reset functions as teardown. Example:
   ```python
   @pytest.fixture(autouse=True)
   def _reset_singletons():
       yield
       reset_settings()
       reset_database()
       reset_deps()  # new: resets embedder, reranker, search_service, duckdb
       reset_redis()  # new: clears _redis_client
   ```
3. Run the full test suite with `pytest --randomly-seed=...` after the refactor to catch ordering-dependent failures.

**Warning signs:**
- Tests pass individually but fail when run in a specific order
- `pytest -x` passes but `pytest` (full run) has failures
- Test output shows unexpected config values (e.g., wrong `database_url`)

**Phase to address:**
Phase 1 (Singleton Refactoring) -- this is the first thing to fix because all subsequent phases depend on test reliability.

---

### Pitfall 2: Alembic Migration Locks Production Tables During Index Creation

**What goes wrong:**
Adding indexes to existing PostgreSQL tables (content_hash on documents, document_id FK on segments, source_type+source_id composite) via a standard Alembic migration uses `CREATE INDEX`, which takes an `ACCESS EXCLUSIVE` lock on the table for the duration of index building. On a table with thousands of segments, this blocks all reads and writes for seconds to minutes. In production with active users, this causes request timeouts and 500 errors.

**Why it happens:**
Alembic's `op.create_index()` generates a standard `CREATE INDEX` statement by default. Developers test migrations on empty or small databases where it completes instantly, never noticing the lock. The segments table is the largest (one document can generate hundreds of segments), making it the most dangerous table to index.

**How to avoid:**
1. Use `CREATE INDEX CONCURRENTLY` for all index additions on existing tables. In Alembic, this requires special handling:
   ```python
   from alembic import op

   def upgrade() -> None:
       # CONCURRENTLY cannot run inside a transaction
       op.execute("COMMIT")
       op.create_index(
           "idx_documents_content_hash",
           "documents",
           ["content_hash"],
           postgresql_concurrently=True,
       )
   ```
2. Alternatively, set `transaction_per_migration=False` in `env.py` for this specific migration.
3. Check which indexes already exist before creating (the initial migration `001_initial_schema.py` already created `idx_segments_document_id`, `idx_segments_content_hash`, and `idx_documents_source`). Creating a duplicate index will error.
4. Test the migration against a database with realistic data volume, not just an empty schema.

**Warning signs:**
- Migration takes more than 1 second on development database
- `alembic upgrade head` hangs when other connections are active
- Duplicate index errors (some indexes may already exist from `001_initial_schema.py`)

**Phase to address:**
Phase 2 (Database Indexes) -- must check existing indexes in `001_initial_schema.py` before writing new migration. Some "needed" indexes may already exist.

---

### Pitfall 3: Breaking the Proxy Pattern Contract During Singleton Refactoring

**What goes wrong:**
The codebase already uses a proxy pattern for `settings` (`_SettingsProxy`) and `engine`/`async_session_factory` (`_EngineProxy`, `_SessionFactoryProxy`). These proxies are imported at module level throughout the codebase (`from pam.common.config import settings`, `from pam.common.database import async_session_factory`). Refactoring the underlying `lru_cache` functions can silently break the proxy if the reset function doesn't also clear the proxy's cached state, or if the proxy's `__getattr__` stops delegating correctly after a reset.

**Why it happens:**
The proxy objects themselves are module-level constants. Calling `reset_settings()` clears the `lru_cache`, but existing code that already evaluated `settings.database_url` at import time (not through the proxy, but by storing the value) will retain the stale value. This is subtle: `from pam.common.config import settings` is fine (imports the proxy), but `DB_URL = settings.database_url` at module level captures the value eagerly.

**How to avoid:**
1. Grep for any module-level attribute access on `settings` or `engine` that captures a value: `grep -rn "= settings\." src/pam/` -- these are the dangerous patterns.
2. Ensure no module stores `settings.X` in a module-level variable. All access must go through the proxy at call time.
3. After refactoring, verify that `reset_settings()` followed by attribute access returns new values:
   ```python
   def test_settings_reset():
       old_url = settings.database_url
       os.environ["DATABASE_URL"] = "postgresql+psycopg://new:new@localhost/new"
       reset_settings()
       assert settings.database_url != old_url
   ```

**Warning signs:**
- Tests that set environment variables and call `reset_settings()` still see old config
- `_SettingsProxy.__getattr__` raises `AttributeError` for valid settings
- Circular import errors when adding new proxy classes

**Phase to address:**
Phase 1 (Singleton Refactoring) -- verify before and after refactoring each module.

---

### Pitfall 4: SSE Streaming Endpoint Swallows Errors Silently

**What goes wrong:**
The `/chat/stream` endpoint in `chat.py` wraps an async generator in `StreamingResponse`. If the generator raises an exception mid-stream (e.g., Anthropic API error, DB connection dropped), FastAPI/Starlette has already sent the 200 status code and headers. The client receives a truncated SSE stream with no error indication. The frontend's `useChat.ts` hook shows a partial response that looks like a complete answer -- the user never knows the response was cut short.

**Why it happens:**
HTTP streaming inherently cannot change the status code after the first byte is sent. The current `event_generator()` in `chat.py` has no try/except around the `agent.answer_streaming()` call. The frontend `useChat.ts` does handle an `"error"` event type, but the backend never sends one when an exception occurs mid-stream -- the connection just drops.

**How to avoid:**
1. Wrap the streaming generator in try/except and yield an SSE error event before closing:
   ```python
   async def event_generator():
       try:
           async for chunk in agent.answer_streaming(...):
               yield f"data: {json.dumps(chunk)}\n\n"
       except Exception as exc:
           logger.exception("stream_error")
           error_event = {"type": "error", "message": str(exc)}
           yield f"data: {json.dumps(error_event)}\n\n"
   ```
2. The frontend already handles the `"error"` event type in `useChat.ts` lines 114-128, so the backend fix is sufficient.
3. Add a `"done"` sentinel event at the end of successful streams so the frontend can distinguish "stream ended normally" from "stream dropped."

**Warning signs:**
- Users report truncated answers that look complete
- No error logs when users experience partial responses
- The frontend's catch block in `useChat.ts` (line 131-158) fires more often than expected (indicates stream failures falling through to non-streaming fallback)

**Phase to address:**
Phase 3 (API Route Improvements) -- fix before any response_model or pagination work since streaming is the primary user-facing endpoint.

---

### Pitfall 5: React Array Index Keys Cause Stale State on Message List Updates

**What goes wrong:**
`ChatInterface.tsx` line 68 uses `key={i}` (array index) for `MessageBubble` components. During streaming, the messages array is updated frequently (every token). When a new message is added at the end, React may incorrectly reuse DOM elements from the previous render because the key for the last element changes. This manifests as: (1) the streaming message briefly flashing the previous message's content, (2) `isStreaming` prop being applied to the wrong message after edits/deletions, and (3) broken scroll-to-bottom behavior.

**Why it happens:**
Array index keys work fine for static lists but break when items are added, removed, or reordered. In a chat interface where messages are appended frequently (every streaming token triggers a state update), the index-based key means React cannot distinguish between "message at position 5 changed content" and "a new message was inserted at position 5."

**How to avoid:**
1. Add a stable `id` field to the `ChatMessage` type. Generate it client-side when creating messages:
   ```typescript
   const userMsg: ChatMessage = {
     id: crypto.randomUUID(),
     role: "user",
     content
   };
   ```
2. Use `key={msg.id}` instead of `key={i}` in the `.map()` call.
3. Do NOT use `content` as a key -- streaming messages start empty and change every token.
4. Also check `DocumentList.tsx` -- it correctly uses `key={doc.id}` (line 46), so that one is fine.

**Warning signs:**
- Flickering during message streaming
- Wrong message gets the streaming indicator
- React DevTools shows unexpected component remounts during streaming

**Phase to address:**
Phase 4 (React Component Fixes) -- low effort, high impact fix.

---

### Pitfall 6: Refactoring Global Singletons in deps.py Breaks FastAPI Dependency Injection Graph

**What goes wrong:**
`deps.py` has 4 separate global+lock patterns (`_embedder`, `_reranker`, `_search_service`, `_duckdb_service`). The natural refactoring is to move these into app.state (set during lifespan) or use `lru_cache`. But `get_search_service` depends on `get_es_client(request)` and `get_cache_service(request)` which both require the `Request` object. You cannot use `lru_cache` for a function that takes `Request` as an argument -- the cache key would be the request object itself, which is different for every request, making the cache useless.

**Why it happens:**
The dependency chain is: `get_agent` -> `get_search_service` -> `get_es_client(request)` + `get_cache_service(request)`. The `request` dependency means these cannot be simple cached functions. Moving to `app.state` is the right pattern (already used for `es_client` and `redis_client`), but it requires restructuring how `HybridSearchService` is initialized.

**How to avoid:**
1. Initialize services in the `lifespan` handler and store on `app.state`, following the existing pattern for `es_client` and `redis_client`.
2. For services that need other services (like `HybridSearchService` needs `es_client`), initialize them in order during lifespan startup.
3. Change dependency functions to pull from `request.app.state.search_service` (like `get_es_client` already does).
4. For testing, override via `app.dependency_overrides[get_search_service] = lambda: mock_service`.
5. Do NOT try to use `@lru_cache` on functions that accept `Request` -- it will either cache the first request forever (if you strip `Request` from the key) or cache nothing (if you include it).

**Warning signs:**
- `lru_cache` decorated function with `Request` parameter
- Service initialized once with first request's state, then serves stale config for subsequent requests
- Test overrides via `app.dependency_overrides` stop working after refactoring

**Phase to address:**
Phase 1 (Singleton Refactoring) -- plan the target architecture before starting. Not all singletons should use the same pattern.

---

## Moderate Pitfalls

### Pitfall 7: Adding response_model to Existing Endpoints Breaks Clients

**What goes wrong:**
Three endpoints in `documents.py` (`/documents`, `/segments/{segment_id}`, `/stats`) return raw dicts without a `response_model`. Adding a Pydantic `response_model` retroactively can change the response shape -- Pydantic validation filters out extra fields, converts types, and may reject data that the raw dict endpoint was happily returning. For example, the `/stats` endpoint returns a manually constructed dict with nested structures. If the Pydantic model doesn't exactly match, fields get silently dropped.

**How to avoid:**
1. First, snapshot the current response for each endpoint (run the endpoint, save the JSON).
2. Build the Pydantic model to match the CURRENT response shape exactly.
3. Diff the before/after responses to catch any field name mismatches or type coercions.
4. The `model_config = {"from_attributes": True}` pattern (already used in `DocumentResponse`) is needed for ORM objects but not for dict responses.

**Phase to address:**
Phase 3 (API Route Improvements).

---

### Pitfall 8: useCallback Dependencies Cause Stale Closures or Infinite Re-renders

**What goes wrong:**
Adding `useCallback` to optimize React event handlers is a common cleanup task. But incorrect dependency arrays cause either stale closures (missing deps) or infinite re-render loops (including objects/arrays that are recreated every render). In `useChat.ts`, `sendMessage` correctly includes `[conversationId, filters]` as dependencies, but `filters` is an object -- if `setFilters` creates a new object reference each time, `sendMessage` gets a new identity every render, causing any `useEffect` that depends on it to fire repeatedly.

**How to avoid:**
1. When wrapping callbacks with `useCallback`, audit every dependency:
   - Primitives (strings, numbers, booleans) -- safe
   - Objects/arrays -- must be stable references (use `useMemo` or ensure state setter produces same reference when value hasn't changed)
2. For `useChat.ts`, the current `filters` state is an object. Changes to unrelated state should NOT recreate the `sendMessage` callback. Verify that `filters` only changes when `setFilters` is called.
3. Test: open React DevTools Profiler, interact with the chat, verify that `ChatInterface` doesn't re-render when it shouldn't.
4. Do NOT add `useCallback` to every function "just because" -- only wrap callbacks passed as props to child components or used as `useEffect` dependencies.

**Phase to address:**
Phase 4 (React Component Fixes).

---

### Pitfall 9: Concurrent Alembic Migrations in CI/CD

**What goes wrong:**
If multiple CI jobs or deployment processes run `alembic upgrade head` simultaneously against the same database, Alembic's `alembic_version` table can get into a corrupt state or deadlock. This is especially risky with `CREATE INDEX CONCURRENTLY` which cannot run inside a transaction.

**How to avoid:**
1. Use PostgreSQL advisory locks in the Alembic `env.py` to serialize migrations:
   ```python
   connection.execute(text("SELECT pg_advisory_lock(1234567)"))
   ```
2. In CI, run migrations as a separate job that completes before deployment starts.
3. Never run `alembic upgrade head` from multiple app instances on startup.

**Phase to address:**
Phase 2 (Database Indexes) -- if the migration uses `CONCURRENTLY`, it's especially important to handle this.

---

### Pitfall 10: Polling Timer Leak When Component Unmounts During Ingestion

**What goes wrong:**
`useIngestionTask.ts` uses `setInterval` for polling and cleans up on unmount (line 44-49). However, if the user navigates away from the documents page while an ingestion is running, the poll stops. When they navigate back, `useIngestionTask` reinitializes with `task: null` and the user sees no progress. The ingestion is still running in the backend but the frontend lost track of it.

**How to avoid:**
1. Store the active `task_id` in a parent component or context that persists across route changes.
2. On the DocumentsPage mount, check if there are any active tasks via `GET /api/ingest/tasks?limit=1` and resume polling.
3. This is a UX improvement, not a bug -- but users will perceive it as "ingestion stopped" when it didn't.

**Phase to address:**
Phase 4 (React Component Fixes) -- lower priority, but good to address with the other React work.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Raw dicts as API responses (current in `/documents`, `/segments`, `/stats`) | Fast to implement, flexible | No validation, no OpenAPI schema, client-side type guessing | Never in a mature API -- should always have response_model |
| Global + asyncio.Lock in deps.py | Works, thread-safe-ish | Untestable, no reset path, leaks between tests | During prototyping only. Current codebase has outgrown this. |
| `key={i}` in React lists | Quick, stops React warnings | Broken reconciliation on dynamic lists | Only for truly static lists that never change |
| Missing `response_model` on streaming endpoint | Streaming responses can't use response_model | No OpenAPI documentation for SSE events | Acceptable (FastAPI doesn't support SSE response models), but document the event schema manually |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Alembic + existing indexes | Creating an index that `001_initial_schema.py` already created, causing migration failure | Run `SELECT indexname FROM pg_indexes WHERE tablename = 'segments'` to check existing indexes before writing migration |
| SQLAlchemy async + lru_cache | Using `lru_cache` on async functions (it caches the coroutine, not the result) | Use `lru_cache` on sync factory functions that return the engine/session-factory (as `database.py` already correctly does), not on async functions |
| pytest-asyncio `auto` mode + global state | `asyncio_mode = "auto"` means each test gets its own event loop by default (pytest-asyncio 0.23+). `asyncio.Lock()` objects created in one event loop are invalid in another | Create locks lazily or use the `lru_cache` pattern which avoids locks entirely |
| FastAPI `app.dependency_overrides` + global singletons | Overriding a dep function doesn't reset the global singleton it already cached | Either override at the singleton level, or ensure deps read from `app.state` which IS per-app-instance |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Missing index on `documents.content_hash` for dedup lookups | Slow ingestion pipeline (full table scan on every document) | Already indexed in `001_initial_schema.py` as `idx_segments_content_hash` on segments, but documents.content_hash is NOT indexed | At 10k+ documents |
| `list_documents()` with no pagination | Response payload grows linearly with document count, slowing page load | Add `limit`/`offset` parameters to `/api/documents`, return total count in headers | At 500+ documents |
| `setMessages(prev => [...prev, ...])` on every streaming token | Creates a new array on every token (50-100 times per response), triggering React reconciliation each time | Throttle state updates (e.g., batch tokens every 50ms via `requestAnimationFrame`) or use `useRef` for accumulation with periodic state flush | Noticeable lag at 1000+ tokens in a single response |
| Full-table scan in `/stats` endpoint | Multiple `SELECT count(*)` across 3 tables on every dashboard load | Add server-side caching (Redis) or materialized counts. Current implementation does 4 queries per `/stats` call | At 100k+ segments |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Streaming endpoint has no error detail sanitization | Internal error messages (DB connection strings, file paths) could leak via SSE error events | Catch exceptions in the generator, log the full error server-side, send only a generic message to the client |
| `/stats` endpoint exposes system internals | Folder paths from ingestion tasks visible to all authenticated users | Check if `recent_tasks` should be restricted to admin users only (currently uses `get_current_user` not `require_admin`) |
| Index migration may expose timing attack surface | If `content_hash` index improves lookup speed, it could theoretically be used to check if a specific hash exists faster | Low risk for this application, but note it |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No loading state for `/documents` list when over 100 items | Page appears frozen while fetching large document lists | Add skeleton loading state, implement pagination |
| Ingestion progress lost on navigation | User thinks ingestion failed when they navigate away and back | Persist active task ID, resume polling on mount |
| Streaming error shows as partial response | User believes truncated answer is complete | Add visual "error" indicator on incomplete streaming responses |
| No document count in page title/header | User can't quickly see how many documents are in the system | Show count in header: "All documents (47)" |

## "Looks Done But Isn't" Checklist

- [ ] **Singleton refactoring:** Often missing reset functions for test isolation -- verify every singleton has a `reset_*()` function AND it's called in conftest.py teardown
- [ ] **Index migration:** Often creates indexes that already exist from initial migration -- verify by checking `001_initial_schema.py` and running `\di` in psql
- [ ] **response_model addition:** Often silently drops fields -- verify by comparing raw dict response before vs. Pydantic-validated response after
- [ ] **useCallback wrapping:** Often introduces stale closures -- verify by testing with React StrictMode (double-renders catch stale closure bugs)
- [ ] **Streaming error handling:** Often only tested on happy path -- verify by killing the LLM API mid-stream and checking client behavior
- [ ] **Pagination:** Often missing total count -- verify that paginated endpoints return total count in headers or response body for the UI to show "page X of Y"
- [ ] **Test suite stability:** Often passes once but flakes -- verify by running `pytest --count=3` (pytest-repeat) or `pytest -p randomly` after ALL changes

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Singleton leak breaks 50+ tests | MEDIUM | Add `autouse` fixture that resets all singletons. Run `pytest --randomly-seed=12345` to verify. May need to fix test-specific setup that relied on leaked state. |
| Migration locks table in production | HIGH | Cannot easily roll back `CREATE INDEX` mid-execution. Kill the migration process, then run the index creation with `CONCURRENTLY` flag during off-hours. |
| response_model breaks API clients | LOW | Revert the response_model, fix the Pydantic model to match actual response shape, redeploy. Frontend won't need changes if the model matches the original dict. |
| React key issues cause UI bugs | LOW | Replace `key={i}` with `key={msg.id}`. Add `id` field to ChatMessage type. Single PR, no backend changes needed. |
| Streaming error swallowed | LOW | Add try/except to generator function. Frontend already handles error events. Single backend change. |
| Stale closure from useCallback | MEDIUM | Identify which callbacks have wrong deps. Fix by adding missing deps or stabilizing object references with useMemo. Requires careful testing. |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Singleton reset leaks (Pitfall 1) | Phase 1: Singleton Refactoring | `pytest -p randomly --randomly-seed=42` passes, all singletons have reset functions |
| Proxy pattern breaks (Pitfall 3) | Phase 1: Singleton Refactoring | Test that `reset_settings()` + re-access returns new values; grep for module-level `= settings.X` captures |
| deps.py DI graph break (Pitfall 6) | Phase 1: Singleton Refactoring | `app.dependency_overrides` works in all test files; no `lru_cache` on Request-accepting functions |
| Migration locks tables (Pitfall 2) | Phase 2: Database Indexes | Migration uses `CONCURRENTLY`; tested against populated database; no duplicate indexes |
| Concurrent migrations (Pitfall 9) | Phase 2: Database Indexes | Advisory lock in env.py; CI runs migration as separate step |
| response_model breaks clients (Pitfall 7) | Phase 3: API Improvements | Before/after response snapshots match; OpenAPI schema generates correctly |
| Streaming swallows errors (Pitfall 4) | Phase 3: API Improvements | Kill LLM API mid-stream; frontend shows error indicator |
| React key issues (Pitfall 5) | Phase 4: React Fixes | Messages have stable IDs; no flickering during streaming; React DevTools shows stable keys |
| useCallback stale closures (Pitfall 8) | Phase 4: React Fixes | React StrictMode enabled; Profiler shows expected re-render count |
| Polling timer leak (Pitfall 10) | Phase 4: React Fixes | Navigate away during ingestion, navigate back, progress resumes |

## Sources

- Direct codebase analysis of `/Users/datnguyen/Projects/AI-Projects/pam-context/src/pam/` (HIGH confidence)
- SQLAlchemy 2.0 async engine documentation -- `lru_cache` pattern for engine/session factory is the documented approach (HIGH confidence)
- Alembic documentation on `CREATE INDEX CONCURRENTLY` requiring non-transactional context (HIGH confidence)
- PostgreSQL documentation on `ACCESS EXCLUSIVE` lock during `CREATE INDEX` (HIGH confidence)
- React documentation on keys and reconciliation (HIGH confidence)
- FastAPI documentation on `StreamingResponse` -- status code sent before body, cannot change mid-stream (HIGH confidence)
- pytest-asyncio 0.23+ documentation on event loop scope and `asyncio_mode = "auto"` (HIGH confidence)
- Existing migration file `alembic/versions/001_initial_schema.py` lines 74-78 confirming indexes `idx_segments_document_id`, `idx_segments_content_hash`, `idx_documents_source` already exist (HIGH confidence -- direct code evidence)

---
*Pitfalls research for: PAM Context code cleanup/refactoring milestone*
*Researched: 2026-02-15*
