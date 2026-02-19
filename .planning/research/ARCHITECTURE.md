# Architecture Patterns

**Domain:** Singleton refactoring and service lifecycle in async FastAPI
**Researched:** 2026-02-15
**Confidence:** HIGH (based on official FastAPI docs, existing codebase analysis, community consensus)

## Current Architecture: What Exists Today

PAM Context uses three distinct patterns for managing shared state, each with different tradeoffs and testability characteristics.

### Pattern 1: Proxy Singletons (config.py, database.py)

```
Module load                 First attribute access          Subsequent access
     |                             |                              |
  _SettingsProxy()          get_settings() -> Settings()     get_settings() (cached)
  _EngineProxy()            get_engine() -> AsyncEngine      get_engine() (cached)
  _SessionFactoryProxy()    get_session_factory()            get_session_factory() (cached)
```

`config.py` exposes `settings = _SettingsProxy()` at module level. The proxy delegates all attribute access to `get_settings()` which is `@lru_cache(maxsize=1)` -- creating the real `Settings()` on first access, not at import time. `database.py` follows the same pattern for engine and session factory, with `reset_database()` and `reset_settings()` to clear caches.

**Verdict:** This is actually a good pattern already. The proxy + lru_cache combination gives lazy initialization without import-time side effects. The `reset_*` functions enable test isolation. The main issue is that 15 modules import `settings` directly and read from it inside their constructors/methods, creating implicit coupling.

### Pattern 2: Double-Checked Locking (deps.py, cache.py)

```python
_embedder: OpenAIEmbedder | None = None
_embedder_lock = asyncio.Lock()

async def get_embedder() -> OpenAIEmbedder:
    global _embedder
    if _embedder is None:
        async with _embedder_lock:
            if _embedder is None:
                _embedder = OpenAIEmbedder()
    return _embedder
```

Used for: embedder, reranker, search_service, duckdb_service, redis_client. Each has a module-level `_instance` variable, an `asyncio.Lock`, and a getter function implementing double-checked locking.

**Verdict:** Functionally correct for async concurrency (asyncio.Lock guards creation in a single event loop). However, the module-level globals make testing painful -- there is no `reset_*` function for these, so tests cannot swap them without `monkeypatch`. The `_search_service` is particularly problematic because it captures `es_client` and `cache` from `request.app.state` at first access and never updates them.

### Pattern 3: Lifespan + app.state (main.py)

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.es_client = AsyncElasticsearch(settings.elasticsearch_url)
    app.state.redis_client = await get_redis()
    yield
    await close_redis()
    await app.state.es_client.close()
```

ES client and Redis client are created in the lifespan context manager and stored on `app.state`. Access is via `request.app.state` in dependency functions.

**Verdict:** This is the FastAPI-recommended pattern and the best one in the codebase. It supports proper async cleanup, test overrides via `dependency_overrides`, and clear lifecycle boundaries.

## Component Dependency Graph

```
                        Settings (config.py)
                       /    |    \       \
                      /     |     \       \
                     v      v      v       v
              Database   Cache   Agent   DuckDB
              (PG engine, (Redis) (Anthropic) (analytics)
               session)     |       |
                  |         v       v
                  |    CacheService  RetrievalAgent
                  |         |       /    |    \
                  v         v      v     v     v
               get_db()  get_cache  SearchSvc  Embedder  Reranker
                  |         |       |          |         |
                  v         v       v          v         v
              [per-request] [per-request] [singleton] [singleton] [singleton]
                                    |
                                    v
                             ES Client (app.state)
```

### Component Boundaries

| Component | Responsibility | Reads Settings | Communicates With | Lifecycle |
|-----------|---------------|----------------|-------------------|-----------|
| `config.py` | Application configuration | IS settings | Everything | Process-level singleton via lru_cache |
| `database.py` | SQLAlchemy engine + session factory | `settings.database_url` | `config.py` | Process-level singleton via lru_cache |
| `cache.py` | Redis client + CacheService | `settings.redis_url`, `settings.redis_*_ttl` | `config.py`, Redis | Redis client = process singleton; CacheService = per-request |
| `deps.py` | FastAPI DI wiring | 6 settings reads | Everything | Dependency functions, some caching singletons |
| `main.py` | App factory + lifespan | `settings.*` (6 reads) | ES, Redis, DB, logging | Application lifecycle |
| `agent.py` | Retrieval agent | `settings.anthropic_api_key`, `settings.agent_model` | SearchSvc, Embedder, DB, DuckDB | Per-request (good) |
| `hybrid_search.py` | ES hybrid search | `settings.elasticsearch_index` | ES client, CacheService, Reranker | Singleton via deps.py |
| `haystack_search.py` | Haystack search backend | `settings.elasticsearch_url`, `settings.elasticsearch_index`, `settings.rerank_model` | ES, CacheService | Singleton via deps.py |
| `openai_embedder.py` | Text embedding | `settings.openai_api_key`, `settings.embedding_model`, `settings.embedding_dims` | OpenAI API | Singleton via deps.py |
| `duckdb_service.py` | SQL analytics | `settings.duckdb_data_dir`, `settings.duckdb_max_rows` | Local DuckDB | Singleton via deps.py |
| `task_manager.py` | Background ingestion | None (uses session_factory directly) | DB, ES, Embedder, Redis | Background asyncio tasks |

### Where Settings Are Actually Read at Runtime

The 15 modules that import `settings` fall into three categories:

**Category A: Read in constructor (testable via constructor params).**
Already pass settings as constructor defaults with `or settings.X` fallback: `RetrievalAgent`, `OpenAIEmbedder`, `HybridSearchService`, `HaystackSearchService`, `DuckDBService`.

**Category B: Read at function call time (testable via proxy reset).**
Read settings inside methods or at dependency-resolution time: `deps.py` (reads `settings.rerank_enabled`, `settings.use_haystack_retrieval`, etc.), `main.py` lifespan, `cache.py` CacheService properties.

**Category C: Read at import/class-definition time (problematic).**
Currently none -- the proxy pattern already defers reads. This is a strength of the existing design.

## Recommended Architecture After Refactoring

### Principle: Push Settings to the Boundary

The target architecture should follow a clear rule: **settings are read once at the application boundary (lifespan + deps.py) and passed as explicit parameters to all services**. No service should import or read `settings` at runtime.

### Target Component Hierarchy

```
lifespan(app)                      # Reads settings, creates long-lived resources
  |-- app.state.es_client          # ES client (existing, good)
  |-- app.state.redis_client       # Redis client (existing, good)
  |-- app.state.engine             # NEW: move engine creation here
  |-- app.state.session_factory    # NEW: derived from engine
  |
  v
deps.py                            # Reads settings, wires dependencies
  |-- get_db()                     # Uses app.state.session_factory
  |-- get_es_client()              # Uses app.state.es_client (existing, good)
  |-- get_cache_service()          # Uses app.state.redis_client (existing, good)
  |-- get_embedder()               # NEW: created once, stored on app.state
  |-- get_reranker()               # NEW: created once, stored on app.state
  |-- get_search_service()         # NEW: created once, stored on app.state
  |-- get_duckdb_service()         # NEW: created once, stored on app.state
  |-- get_agent()                  # Per-request (existing, good)
  |
  v
Services (no settings imports)     # All config via constructor params
  |-- RetrievalAgent(search, embedder, api_key, model, ...)
  |-- HybridSearchService(es_client, index_name, cache, reranker)
  |-- OpenAIEmbedder(api_key, model, dims, ...)
  |-- CacheService(client, search_ttl, session_ttl)
  |-- DuckDBService(data_dir, max_rows)
```

### Pattern: app.state for Application-Scoped Singletons

Move the double-checked locking singletons from `deps.py` module-level globals into `app.state` via the lifespan context manager. This gives:

1. **Proper cleanup**: async resources disposed in lifespan shutdown
2. **Test overrides**: `app.dependency_overrides[get_X]` works cleanly
3. **No global mutation**: no `global _embedder` statements
4. **Explicit lifecycle**: created in lifespan, used in handlers, cleaned in shutdown

```python
# main.py lifespan (target state)
@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()

    # Infrastructure
    app.state.es_client = AsyncElasticsearch(s.elasticsearch_url)
    app.state.redis_client = await get_redis()
    app.state.engine = create_async_engine(s.database_url, pool_size=5, max_overflow=10)
    app.state.session_factory = async_sessionmaker(app.state.engine, ...)

    # Services (created once, used for app lifetime)
    app.state.embedder = OpenAIEmbedder(
        api_key=s.openai_api_key,
        model=s.embedding_model,
        dims=s.embedding_dims,
    )

    # ... ES index init, stale task recovery ...

    yield

    # Cleanup
    await app.state.engine.dispose()
    await close_redis()
    await app.state.es_client.close()
```

```python
# deps.py (target state -- no module-level globals)
def get_embedder(request: Request) -> OpenAIEmbedder:
    return request.app.state.embedder

def get_search_service(request: Request) -> HybridSearchService:
    return request.app.state.search_service

async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    factory = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
```

### Pattern: Keep Proxy + lru_cache for Settings

The current `_SettingsProxy` + `get_settings()` + `reset_settings()` pattern in `config.py` is solid. It should remain as-is because:

1. Settings are needed before lifespan starts (e.g., `create_app()` reads CORS origins for middleware)
2. The proxy avoids import-time env reads while providing a clean API
3. `reset_settings()` already enables test isolation
4. FastAPI's recommended `@lru_cache` + `Depends(get_settings)` pattern is essentially what this proxy achieves

The only change needed: services that currently import `settings` and read it in methods should instead receive config values via constructor parameters.

### Pattern: Explicit Constructor Parameters for Services

Every service should accept all configuration as constructor params with no hidden settings reads:

```python
# BEFORE (CacheService reads settings at property access time)
class CacheService:
    @property
    def search_ttl(self) -> int:
        return self._search_ttl if self._search_ttl is not None else settings.redis_search_ttl

# AFTER (CacheService is fully configured at construction)
class CacheService:
    def __init__(self, client: redis.Redis, search_ttl: int, session_ttl: int) -> None:
        self.client = client
        self.search_ttl = search_ttl
        self.session_ttl = session_ttl
```

This matters because:
- Tests can construct services with exact values, no env vars needed
- No hidden coupling to global state
- Constructor signature documents all dependencies

### The task_manager.py Problem

`task_manager.py` directly imports `async_session_factory` because background tasks run outside the request lifecycle and cannot use FastAPI's DI. After refactoring, it should receive the session factory as a parameter:

```python
def spawn_ingestion_task(
    task_id: uuid.UUID,
    folder_path: str,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,  # NEW: explicit param
) -> None:
    asyncio_task = asyncio.create_task(
        run_ingestion_background(task_id, folder_path, es_client, embedder, session_factory),
    )
```

The caller (ingest route handler) already has access to these via dependency injection.

## Anti-Patterns to Avoid

### Anti-Pattern 1: Module-Level Global + asyncio.Lock Without Reset

**What:** `_embedder: X | None = None` + `_embedder_lock = asyncio.Lock()` with no reset function.

**Why bad:** Tests cannot replace the singleton without monkeypatching module internals. If one test creates the embedder, all subsequent tests use that instance. The Lock is created at import time, meaning it is tied to the event loop that existed at import -- this can cause issues with pytest-asyncio which may create new loops per test.

**Instead:** Store on `app.state` in lifespan, override via `dependency_overrides` in tests.

### Anti-Pattern 2: Singleton Capturing Request-Scoped State

**What:** `get_search_service()` captures `es_client` and `cache` from the first request's `request.app.state` and never updates them.

```python
# Current problematic code
async def get_search_service(request: Request) -> HybridSearchService:
    global _search_service
    if _search_service is None:
        async with _search_service_lock:
            if _search_service is None:
                es_client = get_es_client(request)  # Captured once!
                cache = get_cache_service(request)   # Captured once!
                ...
```

**Why bad:** If `app.state.es_client` or `app.state.redis_client` changes (e.g., reconnection), the singleton still holds the old reference. In tests, if `dependency_overrides` replaces `get_es_client`, the search service still uses whatever was captured on first call.

**Instead:** Create search service in lifespan with explicit params, or re-resolve dependencies on each call.

### Anti-Pattern 3: Settings Reads Scattered Across Service Methods

**What:** A service imports `settings` and reads it inside methods, not just the constructor.

**Why bad:** Makes the service's behavior dependent on global mutable state. Tests that change env vars after service construction may or may not affect behavior depending on which code path is hit.

**Instead:** Read all settings at construction time and store as instance attributes.

## Patterns to Follow

### Pattern: Test Override via dependency_overrides (Existing, Keep)

The current test pattern in `tests/test_api/conftest.py` is excellent:

```python
@pytest.fixture
def app(mock_agent, mock_search_service, ...):
    application = create_app()
    application.dependency_overrides[get_agent] = lambda: mock_agent
    application.dependency_overrides[get_search_service] = lambda: mock_search_service
    ...
    return application
```

This pattern should remain the primary way to swap services in API tests. The refactoring makes it more reliable by ensuring singletons are not cached in module globals that bypass the override.

### Pattern: Async Cleanup in Lifespan

Resources that need async disposal (engine, ES client, Redis) must be created and destroyed in the lifespan context manager. This is already done for ES and Redis. After refactoring, the DB engine joins them:

```python
yield  # app runs here

# Cleanup (reverse order of creation)
await app.state.engine.dispose()
await close_redis()
await app.state.es_client.close()
```

### Pattern: Per-Request Services That Need Request-Scoped State

`RetrievalAgent` is per-request because it holds a DB session and mutable state (`_default_source_type`). This pattern is correct and should remain. Services that are stateless or hold only long-lived connections (embedder, search service) should be application-scoped singletons.

## Safe Refactoring Order

The refactoring has a specific dependency order. Changing components out of order will break the test suite.

### Phase 1: Settings Foundation (Low Risk)

**What:** Make `CacheService` fully configured via constructor. Remove the fallback `settings.redis_search_ttl` reads from properties.

**Why first:** CacheService is a leaf dependency (nothing depends on its constructor signature changing). Tests already construct it with explicit `client` param. Only need to add `search_ttl` and `session_ttl` as required params.

**Blast radius:** `cache.py` + `deps.py` (update CacheService construction) + `task_manager.py` (update CacheService construction) + cache tests.

**What changes:**
1. `CacheService.__init__` requires `search_ttl` and `session_ttl` (no Optional, no settings fallback)
2. `CacheService` no longer imports `settings`
3. `deps.py` `get_cache_service()` passes TTL values from `get_settings()`
4. `task_manager.py` passes TTL values when constructing CacheService

**Test impact:** ~5 tests in `test_cache.py` need updated construction calls.

### Phase 2: Database Engine to Lifespan (Medium Risk)

**What:** Move `create_async_engine` and `async_sessionmaker` from `database.py` lru_cache into `app.state` via lifespan.

**Why second:** The DB session factory is used in three places: `deps.py`, `main.py`, and `task_manager.py`. Moving it to app.state is straightforward but `task_manager.py` needs the factory passed as a parameter instead of importing it.

**Blast radius:** `database.py` + `main.py` + `deps.py` + `task_manager.py` + `ingest.py` route (passes factory to task_manager) + database tests + task_manager tests.

**What changes:**
1. `database.py` keeps `get_engine()` / `get_session_factory()` / `reset_database()` for backward compat, but `main.py` lifespan creates the canonical instances on `app.state`
2. `deps.py` `get_db()` uses `request.app.state.session_factory` instead of importing `async_session_factory`
3. `task_manager.py` functions accept `session_factory` as an explicit parameter
4. `ingest.py` route passes `request.app.state.session_factory` to task_manager

**Test impact:** ~10-15 tests across API and task_manager tests. Existing `dependency_overrides[get_db]` pattern continues working.

**Preserve backward compat:** Keep `database.py` proxy objects working for any code that imports them directly. They still work via lru_cache. The new path through app.state is additive.

### Phase 3: Service Singletons to app.state (Medium Risk)

**What:** Move embedder, reranker, search_service, and duckdb_service from `deps.py` module globals to `app.state`.

**Why third:** These depend on the patterns established in Phases 1-2 (settings passed explicitly, DB engine on app.state). The search service depends on ES client, cache, and reranker -- all of which need to be available before it is constructed.

**Blast radius:** `deps.py` (major rewrite of singleton getters) + `main.py` (lifespan creates services) + all API route tests that override these dependencies.

**What changes:**
1. Remove module-level `_embedder`, `_reranker`, `_search_service`, `_duckdb_service` and their locks from `deps.py`
2. `main.py` lifespan creates these services with explicit config:
   ```python
   app.state.embedder = OpenAIEmbedder(api_key=s.openai_api_key, ...)
   app.state.reranker = CrossEncoderReranker(model_name=s.rerank_model) if s.rerank_enabled else None
   app.state.search_service = HybridSearchService(app.state.es_client, ..., reranker=app.state.reranker)
   app.state.duckdb_service = DuckDBService(data_dir=s.duckdb_data_dir, ...) if s.duckdb_data_dir else None
   ```
3. `deps.py` getters become simple `request.app.state.X` lookups
4. Remove `from pam.common.config import settings` from `deps.py`

**Test impact:** ~5-10 tests. The existing `dependency_overrides` pattern already works for these -- the main change is that tests no longer need to worry about stale module-level singletons leaking across tests.

### Phase 4: Remove Settings Imports from Services (Low Risk)

**What:** Remove `from pam.common.config import settings` from service modules that already accept config via constructor params but still have fallback reads.

**Why last:** This is a cleanup pass after Phases 1-3 ensure all config is passed explicitly. Each service already has constructor params for its config values; we just need to remove the `or settings.X` fallbacks and make the params required.

**Blast radius:** Individual service files + their unit tests. Each can be done independently.

**Target modules and changes:**
| Module | Current `settings` Reads | Change |
|--------|------------------------|--------|
| `hybrid_search.py` | `settings.elasticsearch_index` in `__init__` fallback | Make `index_name` required (or keep default) |
| `haystack_search.py` | `settings.elasticsearch_url`, `settings.elasticsearch_index`, `settings.rerank_model` in `__init__` fallback | Make params required |
| `openai_embedder.py` | `settings.openai_api_key`, `settings.embedding_model`, `settings.embedding_dims` in `__init__` fallback | Make params required |
| `agent.py` | `settings.anthropic_api_key`, `settings.agent_model` in `__init__` fallback | Make params required |
| `duckdb_service.py` | `settings.duckdb_data_dir`, `settings.duckdb_max_rows` in `__init__` fallback | Make params required |
| `entity_extractor.py` | `settings.anthropic_api_key` | Pass via constructor |
| `hybrid_chunker.py` | `settings.chunk_size_tokens` | Pass via function param |
| `elasticsearch_store.py` | `settings.elasticsearch_index`, `settings.embedding_dims` | Pass via constructor |

**Test impact:** Minimal. Most unit tests already construct services with explicit params. Tests that relied on settings fallbacks need to pass values explicitly.

## Scalability Considerations

| Concern | Current (450 tests) | After Refactoring | At 1000+ tests |
|---------|---------------------|-------------------|----------------|
| Test isolation | Module globals leak across tests | app.state per test app instance | Clean isolation |
| Startup time | Lazy init on first request | Eager init in lifespan (slightly faster first request) | Predictable |
| Config override | `reset_settings()` + `monkeypatch` | `dependency_overrides` + explicit constructor params | Composable |
| Async safety | asyncio.Lock guards (correct but global) | No locks needed (lifespan is single-threaded) | Simpler |
| Resource cleanup | Partial (ES and Redis yes, engine no) | Full cleanup in lifespan shutdown | Reliable |

## Build Order for Roadmap

Based on the dependency analysis above, the recommended build order is:

1. **CacheService constructor cleanup** -- standalone, zero dependency on other changes
2. **Database engine to app.state** -- requires no other changes, unblocks task_manager cleanup
3. **Service singletons to app.state** -- requires DB engine on app.state (for search service wiring)
4. **Remove settings fallbacks from services** -- requires Phases 1-3 complete, can be done per-module

Each phase should include:
- The code change
- Updated unit tests
- Verification that all 450+ tests still pass
- No API contract changes

## Sources

- [FastAPI Settings and Environment Variables (official docs)](https://fastapi.tiangolo.com/advanced/settings/) -- HIGH confidence: recommended `@lru_cache` + `Depends` + `dependency_overrides` pattern
- [FastAPI Discussion #8054: Dependency Injection - Singleton?](https://github.com/fastapi/fastapi/discussions/8054) -- HIGH confidence: community consensus on `app.state` + lifespan for singletons
- [Python asyncio.Lock documentation](https://docs.python.org/3/library/asyncio-sync.html) -- HIGH confidence: asyncio.Lock is NOT thread-safe, only coroutine-safe within single event loop
- [FastAPI Discussion #8239: Storing object instances in the app context](https://github.com/fastapi/fastapi/discussions/8239) -- MEDIUM confidence: endorses `app.state` over globals
- Codebase analysis of `src/pam/` -- HIGH confidence: direct reading of source code
