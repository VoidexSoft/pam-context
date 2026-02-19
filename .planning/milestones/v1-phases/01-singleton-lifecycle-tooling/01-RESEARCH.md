# Phase 1: Singleton Lifecycle + Tooling - Research

**Researched:** 2026-02-15
**Domain:** FastAPI singleton lifecycle, Python linting (ruff), static type checking (mypy)
**Confidence:** HIGH

## Summary

This phase refactors the PAM Context codebase to eliminate module-level singleton state from `deps.py`, migrate all service initialization into the FastAPI lifespan handler with `app.state` storage, make service constructors accept explicit config parameters, and expand linting/typing tooling. The codebase is well-structured for this refactor -- most services already accept dependencies via constructors, and the lifespan pattern is already partially in use (ES client, Redis).

The primary challenge is the 6 module-level globals in `deps.py` (`_embedder`, `_reranker`, `_search_service`, `_duckdb_service`, and their associated locks/flags) that create hidden shared state causing potential test-order dependency. The `task_manager.py` module directly imports `async_session_factory` and `get_redis()`, creating another hidden coupling. The `CacheService` falls back to `settings` for TTL values when not explicitly provided. The ES `INDEX_MAPPING` computes `settings.embedding_dims` at import time.

The tooling expansion is well-scoped: ruff needs 9 new rule categories (105 violations in `src/`, with FAST002 being the largest at 38 and B008 at 42 -- both FastAPI `Depends()` related), and mypy needs `check_untyped_defs`, `warn_unreachable`, and the Pydantic plugin (the SQLAlchemy mypy plugin is deprecated and should NOT be used).

**Primary recommendation:** Refactor in dependency order -- CacheService and config-accepting constructors first, then lifespan initialization, then deps.py cleanup, then task_manager, then tooling last (since it validates everything).

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | >=0.115 (installed) | Web framework with lifespan + app.state | Already in use; lifespan is the official pattern |
| ruff | 0.15.0 (installed) | Linting + formatting | Already in use; just expanding rule set |
| mypy | 1.19.1 (installed) | Static type checking | Already in use; adding plugins + stricter config |
| pydantic | >=2.0 (installed) | Data validation | Already in use; mypy plugin available |
| pydantic-settings | >=2.0 (installed) | Config via env vars | Already in use; Settings class |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-randomly | latest | Randomize test order | Install as dev dep; run with `pytest -p randomly` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pytest-randomly | pytest-random-order | pytest-randomly is more popular, better xdist support, hash-based ordering allows subset reproducibility |
| SQLAlchemy mypy plugin | None (don't use it) | Deprecated since SA 2.0, incompatible with mypy >=1.11; SA 2.x with `Mapped[]` annotations works natively |

**Installation:**
```bash
pip install pytest-randomly
```

Add to `pyproject.toml` dev dependencies:
```toml
dev = [
    # ... existing ...
    "pytest-randomly>=3.0",
]
```

## Architecture Patterns

### Pattern 1: FastAPI Lifespan + app.state for Singletons
**What:** All service singletons are created inside the `lifespan` async context manager and stored on `app.state`. Dependency functions read from `request.app.state`.
**When to use:** Any resource that should exist for the app lifetime (DB connections, service instances, ML models).

**Current state (deps.py has 6 module-level globals):**
```python
# BAD: Module-level globals with double-checked locking
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

**Target state:**
```python
# GOOD: lifespan creates, app.state stores, deps read
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # Database
    engine = create_async_engine(settings.database_url, pool_size=5, max_overflow=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.db_engine = engine
    app.state.session_factory = session_factory

    # Elasticsearch
    app.state.es_client = AsyncElasticsearch(settings.elasticsearch_url)

    # Embedder
    app.state.embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dims=settings.embedding_dims,
    )

    # Reranker (optional)
    reranker = None
    if settings.rerank_enabled:
        from pam.retrieval.rerankers.cross_encoder import CrossEncoderReranker
        reranker = CrossEncoderReranker(model_name=settings.rerank_model)
    app.state.reranker = reranker

    # Search service
    cache_service = None
    # Redis setup ...
    if settings.use_haystack_retrieval:
        app.state.search_service = HaystackSearchService(
            es_url=settings.elasticsearch_url,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            rerank_enabled=settings.rerank_enabled,
            rerank_model=settings.rerank_model,
        )
    else:
        app.state.search_service = HybridSearchService(
            app.state.es_client,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            reranker=reranker,
        )

    # DuckDB (optional)
    duckdb_service = None
    if settings.duckdb_data_dir:
        from pam.agent.duckdb_service import DuckDBService
        duckdb_service = DuckDBService(
            data_dir=settings.duckdb_data_dir,
            max_rows=settings.duckdb_max_rows,
        )
        duckdb_service.register_files()
    app.state.duckdb_service = duckdb_service

    yield

    # Shutdown
    await app.state.es_client.close()
    await engine.dispose()
```

```python
# deps.py becomes pure readers -- no globals, no locks
async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

def get_embedder(request: Request) -> OpenAIEmbedder:
    return request.app.state.embedder

def get_search_service(request: Request) -> HybridSearchService:
    return request.app.state.search_service

def get_reranker(request: Request) -> BaseReranker | None:
    return request.app.state.reranker

def get_duckdb_service(request: Request) -> DuckDBService | None:
    return request.app.state.duckdb_service
```

### Pattern 2: Explicit Config in Constructors (No Hidden settings Imports)
**What:** Service classes accept all configuration as constructor parameters. No fallback to `from pam.common.config import settings` inside service modules.
**When to use:** Every service class -- enables testability and makes dependencies visible.

**Current (hidden settings fallback):**
```python
class CacheService:
    def __init__(self, client, search_ttl=None, session_ttl=None):
        self._search_ttl = search_ttl  # Falls back to settings if None!

    @property
    def search_ttl(self) -> int:
        return self._search_ttl if self._search_ttl is not None else settings.redis_search_ttl
```

**Target (all config explicit, no fallback):**
```python
class CacheService:
    def __init__(self, client, search_ttl: int, session_ttl: int):
        self._search_ttl = search_ttl
        self._session_ttl = session_ttl

    @property
    def search_ttl(self) -> int:
        return self._search_ttl
```

### Pattern 3: Lazy INDEX_MAPPING Computation
**What:** ES INDEX_MAPPING uses `settings.embedding_dims` which forces settings evaluation at import time. Move to a function or class method.
**When to use:** Any module-level constant that depends on runtime configuration.

**Current (import-time evaluation):**
```python
INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "embedding": {
                "type": "dense_vector",
                "dims": settings.embedding_dims,  # Evaluated at import!
            },
        }
    }
}
```

**Target (lazy computation):**
```python
def get_index_mapping(embedding_dims: int) -> dict:
    return {
        "mappings": {
            "properties": {
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                # ... rest of mapping
            }
        }
    }

class ElasticsearchStore:
    def __init__(self, client, index_name: str, embedding_dims: int):
        self.client = client
        self.index_name = index_name
        self._embedding_dims = embedding_dims

    async def ensure_index(self) -> None:
        exists = await self.client.indices.exists(index=self.index_name)
        if not exists:
            mapping = get_index_mapping(self._embedding_dims)
            await self.client.indices.create(index=self.index_name, body=mapping)
```

### Pattern 4: task_manager Receives session_factory as Parameter
**What:** `task_manager.py` currently imports `async_session_factory` globally. Refactor `spawn_ingestion_task` and `run_ingestion_background` to accept `session_factory` as a parameter.
**When to use:** Any background task that needs DB access.

**Current:**
```python
from pam.common.database import async_session_factory

async def run_ingestion_background(task_id, folder_path, es_client, embedder):
    async with async_session_factory() as session:  # Hidden import!
        ...
```

**Target:**
```python
def spawn_ingestion_task(task_id, folder_path, es_client, embedder, session_factory):
    asyncio.create_task(
        run_ingestion_background(task_id, folder_path, es_client, embedder, session_factory)
    )

async def run_ingestion_background(task_id, folder_path, es_client, embedder, session_factory):
    async with session_factory() as session:
        ...
```

### Pattern 5: Ruff `extend-immutable-calls` for FastAPI Depends
**What:** B008 rule flags `Depends()` in default args. Use ruff's `extend-immutable-calls` to whitelist FastAPI dependency injection calls.
**When to use:** Always, when using B (bugbear) rules with FastAPI.

```toml
[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.Depends", "fastapi.Query", "fastapi.Path", "fastapi.Body", "fastapi.Header"]
```

### Anti-Patterns to Avoid
- **Module-level globals with asyncio.Lock for singletons:** Creates hidden state that leaks between tests. Use lifespan + app.state instead.
- **settings fallback in constructors:** `param or settings.value` hides a dependency. Pass all config explicitly.
- **Import-time settings access:** `INDEX_MAPPING = {"dims": settings.embedding_dims}` forces settings evaluation at import. Use functions or class methods.
- **Test setup/teardown that mutates module globals:** `deps_module._duckdb_service = None` is fragile. After refactor, tests should use `app.dependency_overrides` or fixture-based app construction.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Test randomization | Custom test shuffling | pytest-randomly | Hash-based ordering, seed reproducibility, xdist compatible |
| FastAPI DI pattern | Custom singleton factories | `app.state` + lifespan | Built into FastAPI, well-documented, no locks needed |
| Linting rules | Custom AST checks | ruff rule categories | 800+ rules, fast, actively maintained |
| Type checking plugins | Custom type stubs | pydantic.mypy plugin | Official Pydantic support for mypy |

**Key insight:** The current deps.py reimplements what FastAPI's lifespan already provides natively. Double-checked locking with asyncio.Lock adds complexity that `app.state` eliminates entirely.

## Common Pitfalls

### Pitfall 1: Breaking Test Fixtures That Override deps.py Functions
**What goes wrong:** After moving singletons to app.state, tests that use `app.dependency_overrides[get_embedder] = lambda: mock` may need signature changes since `get_embedder` now takes `request: Request`.
**Why it happens:** FastAPI DI resolves `Request` automatically, but `dependency_overrides` lambdas don't receive it.
**How to avoid:** Override functions with the correct signature, or use simple lambdas that ignore the request parameter. The override replaces the entire function, so the lambda just returns the mock. Existing pattern `lambda: mock_embedder` still works because FastAPI calls the override instead of the original.
**Warning signs:** Tests fail with "missing positional argument: request" errors.

### Pitfall 2: FAST002 Scope Explosion
**What goes wrong:** Enabling FAST002 flags 38 violations -- every `Depends()` call without `Annotated`. Fixing all of them is a large API refactor.
**Why it happens:** FAST002 enforces the modern `Annotated[Type, Depends(fn)]` pattern, but the codebase uses the older `param: Type = Depends(fn)` pattern consistently.
**How to avoid:** Either (a) ignore FAST002 for now and fix incrementally, or (b) include FAST002 but convert all route signatures. Option (a) is lower risk for this phase.
**Warning signs:** PR scope creep -- changing 38 route signatures is a separate task from singleton lifecycle.

### Pitfall 3: B008 False Positives with FastAPI
**What goes wrong:** B008 flags all `Depends()`, `Query()`, `Path()`, `Body()`, `Header()` calls in function defaults -- but these are intentional FastAPI DI patterns.
**Why it happens:** B008 (function-call-in-default-argument) doesn't know that FastAPI DI calls are safe.
**How to avoid:** Add `extend-immutable-calls` to ruff config:
```toml
[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = ["fastapi.Depends", "fastapi.Query", "fastapi.Path", "fastapi.Body", "fastapi.Header"]
```
**Warning signs:** 42 B008 violations all pointing at FastAPI route handlers.

### Pitfall 4: S101 (assert) in Test Files
**What goes wrong:** Enabling S (bandit) rules flags every `assert` statement in tests as a security issue.
**Why it happens:** S101 warns about assert usage since asserts can be stripped with `python -O`. This is valid for production code but not for tests.
**How to avoid:** Add per-path ignore in ruff config:
```toml
[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "S108", "S106", "ARG001", "ARG002"]
```
**Warning signs:** 859 S101 violations in test directory.

### Pitfall 5: SQLAlchemy Mypy Plugin is Deprecated
**What goes wrong:** Adding `sqlalchemy.ext.mypy.plugin` to mypy plugins causes errors with mypy >=1.11.
**Why it happens:** The SQLAlchemy mypy plugin is deprecated since SA 2.0 and incompatible with mypy 1.11+. The project uses mypy 1.19.1.
**How to avoid:** Do NOT add the SQLAlchemy mypy plugin. SQLAlchemy 2.x with `Mapped[]` annotations works natively with mypy. Only add `pydantic.mypy` plugin.
**Warning signs:** mypy crashes or reports internal errors related to SQLAlchemy plugin.

### Pitfall 6: Circular Import When Moving Lifespan Initialization
**What goes wrong:** Moving service creation into lifespan may trigger circular imports if lifespan imports service classes that import from modules that import from `api`.
**Why it happens:** Current lazy imports in deps.py (e.g., `from pam.agent.duckdb_service import DuckDBService`) exist specifically to avoid circular imports.
**How to avoid:** Keep lazy imports inside lifespan for heavy modules (DuckDBService, CrossEncoderReranker, HaystackSearchService). These are already conditionally imported.
**Warning signs:** ImportError at startup.

### Pitfall 7: Test Order Failures from Leaking Singleton State
**What goes wrong:** Tests that set `deps_module._duckdb_service = None` in setup/teardown can fail if another test modifies the global and teardown doesn't run (e.g., test error).
**Why it happens:** Module-level globals are shared across the entire test session. Setup/teardown is fragile -- errors can skip teardown.
**How to avoid:** After refactoring, deps.py has no module-level state. Tests create fresh app instances with overrides. Use pytest fixtures with `autouse=True` for cleanup if any global state remains.
**Warning signs:** Tests pass individually but fail when run together, especially with `pytest -p randomly`.

### Pitfall 8: DuckDB Stale Cache Not Invalidated
**What goes wrong:** DuckDB `_tables` dict is populated once via `register_files()` and never refreshed when data files change.
**Why it happens:** Current implementation calls `register_files()` once at initialization.
**How to avoid:** Add a mechanism to detect file changes (e.g., check mtime of data directory before queries, or add an explicit `refresh_tables()` method). The simplest approach: compare `data_dir.stat().st_mtime` before each query batch, or expose a refresh endpoint.
**Warning signs:** New CSV/Parquet files added to data dir aren't queryable until server restart.

## Code Examples

### Example 1: Complete Lifespan Handler
```python
# Source: FastAPI official docs + project-specific adaptation
from contextlib import asynccontextmanager
from fastapi import FastAPI
from pam.common.config import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # --- Startup ---
    configure_logging(settings.log_level)

    # Database engine + session factory
    engine = create_async_engine(
        settings.database_url, echo=False, pool_size=5, max_overflow=10,
    )
    app.state.db_engine = engine
    app.state.session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False,
    )

    # Elasticsearch client + index
    app.state.es_client = AsyncElasticsearch(settings.elasticsearch_url)
    es_store = ElasticsearchStore(
        app.state.es_client,
        index_name=settings.elasticsearch_index,
        embedding_dims=settings.embedding_dims,
    )
    await es_store.ensure_index()

    # Redis (optional)
    redis_client = None
    try:
        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        app.state.redis_client = redis_client
    except Exception:
        app.state.redis_client = None

    # CacheService (no settings fallback)
    cache_service = None
    if redis_client:
        cache_service = CacheService(
            redis_client,
            search_ttl=settings.redis_search_ttl,
            session_ttl=settings.redis_session_ttl,
        )
    app.state.cache_service = cache_service

    # Embedder
    app.state.embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dims=settings.embedding_dims,
    )

    # Reranker (conditional)
    reranker = None
    if settings.rerank_enabled:
        from pam.retrieval.rerankers.cross_encoder import CrossEncoderReranker
        reranker = CrossEncoderReranker(model_name=settings.rerank_model)
    app.state.reranker = reranker

    # Search service (haystack or legacy)
    if settings.use_haystack_retrieval:
        from pam.retrieval.haystack_search import HaystackSearchService
        app.state.search_service = HaystackSearchService(
            es_url=settings.elasticsearch_url,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            rerank_enabled=settings.rerank_enabled,
            rerank_model=settings.rerank_model,
        )
    else:
        app.state.search_service = HybridSearchService(
            app.state.es_client,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            reranker=reranker,
        )

    # DuckDB (conditional)
    duckdb_service = None
    if settings.duckdb_data_dir:
        from pam.agent.duckdb_service import DuckDBService
        duckdb_service = DuckDBService(
            data_dir=settings.duckdb_data_dir,
            max_rows=settings.duckdb_max_rows,
        )
        duckdb_service.register_files()
    app.state.duckdb_service = duckdb_service

    # Recover stale tasks
    async with app.state.session_factory() as session:
        # ... clean up orphaned tasks ...
        pass

    yield

    # --- Shutdown ---
    if redis_client:
        await redis_client.aclose()
    await app.state.es_client.close()
    await engine.dispose()
```

### Example 2: Clean deps.py (No Module State)
```python
# Source: Project-specific refactored pattern
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from collections.abc import AsyncGenerator

async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise

def get_es_client(request: Request) -> AsyncElasticsearch:
    return request.app.state.es_client

def get_embedder(request: Request) -> OpenAIEmbedder:
    return request.app.state.embedder

def get_search_service(request: Request) -> HybridSearchService:
    return request.app.state.search_service

def get_duckdb_service(request: Request) -> DuckDBService | None:
    return request.app.state.duckdb_service

def get_cache_service(request: Request) -> CacheService | None:
    return request.app.state.cache_service
```

### Example 3: Ruff Configuration Expansion
```toml
# pyproject.toml
[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "S", "SIM", "ARG", "PT", "RET", "PERF", "RUF"]
# Note: FAST omitted initially due to 38 FAST002 violations requiring Annotated migration

[tool.ruff.lint.flake8-bugbear]
extend-immutable-calls = [
    "fastapi.Depends",
    "fastapi.Query",
    "fastapi.Path",
    "fastapi.Body",
    "fastapi.Header",
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = [
    "S101",   # assert usage in tests is fine
    "S106",   # hardcoded passwords in test fixtures
    "S108",   # hardcoded temp file paths in tests
    "ARG001", # unused function args (pytest fixtures)
    "ARG002", # unused method args (pytest fixtures)
    "ARG005", # unused lambda args (dependency overrides)
    "PT019",  # pytest fixture param without value (existing pattern)
]
```

### Example 4: Mypy Configuration Expansion
```toml
# pyproject.toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
check_untyped_defs = true
warn_unreachable = true
plugins = ["pydantic.mypy"]
# NOTE: Do NOT add sqlalchemy.ext.mypy.plugin -- it is deprecated and
# incompatible with mypy >=1.11. SA 2.x Mapped[] annotations work natively.

[tool.pydantic-mypy]
init_forbid_extra = true
init_typed = true
warn_required_dynamic_aliases = true
```

### Example 5: DuckDB Stale Cache Invalidation
```python
class DuckDBService:
    def __init__(self, data_dir: str, max_rows: int) -> None:
        self.data_dir = Path(data_dir)
        self.max_rows = max_rows
        self._tables: dict[str, Path] = {}
        self._last_scan_mtime: float = 0.0

    def _needs_refresh(self) -> bool:
        """Check if data directory has been modified since last scan."""
        if not self.data_dir.is_dir():
            return False
        current_mtime = self.data_dir.stat().st_mtime
        return current_mtime > self._last_scan_mtime

    def register_files(self) -> None:
        if self.data_dir is None or not self.data_dir.is_dir():
            return
        self._tables.clear()
        for ext in ("*.csv", "*.parquet", "*.json"):
            for path in self.data_dir.glob(ext):
                table_name = path.stem.lower().replace("-", "_").replace(" ", "_")
                self._tables[table_name] = path
        self._last_scan_mtime = self.data_dir.stat().st_mtime

    def execute_query(self, sql: str) -> dict:
        if self._needs_refresh():
            self.register_files()
        # ... rest of query execution
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `@app.on_event("startup")` | `lifespan` async context manager | FastAPI 0.93+ (2023) | Cleaner startup/shutdown, no event decorator |
| Module-level globals + locks | `app.state` singletons via lifespan | FastAPI best practice since 0.100+ | Eliminates test leakage, simpler code |
| `sqlalchemy.ext.mypy.plugin` | Native `Mapped[]` annotations | SQLAlchemy 2.0 (2023) | Plugin deprecated, incompatible with mypy >=1.11 |
| `param: Type = Depends(fn)` | `param: Annotated[Type, Depends(fn)]` | FastAPI 0.95+ (2023) | More IDE-friendly, but both patterns still supported |
| flake8 + isort + black | ruff (lint + format) | 2023-2024 | Single tool, much faster |

**Deprecated/outdated:**
- `@app.on_event("startup")`/`@app.on_event("shutdown")`: Replaced by `lifespan` parameter. Already not used in this project.
- `sqlalchemy.ext.mypy.plugin`: Deprecated in SA 2.0, broken with mypy >=1.11. Do NOT add.

## Inventory of Changes Required

### Files Needing Singleton/Config Refactoring

| File | Current Issue | Required Change |
|------|--------------|-----------------|
| `src/pam/api/deps.py` | 6 module-level globals + locks | Remove all globals; read from `request.app.state` |
| `src/pam/api/main.py` | Partial lifespan (ES, Redis only) | Expand lifespan to create ALL singletons |
| `src/pam/common/cache.py` | `CacheService` TTL falls back to `settings` | Make `search_ttl` and `session_ttl` required params |
| `src/pam/common/cache.py` | Module-level `_redis_client` global | Move Redis client creation to lifespan |
| `src/pam/ingestion/task_manager.py` | Imports `async_session_factory` directly | Accept `session_factory` as parameter |
| `src/pam/ingestion/task_manager.py` | Imports `get_redis()` for cache invalidation | Accept `cache_service` as parameter |
| `src/pam/ingestion/stores/elasticsearch_store.py` | `INDEX_MAPPING` uses `settings.embedding_dims` at import | Make function, accept `embedding_dims` param |
| `src/pam/ingestion/stores/elasticsearch_store.py` | Constructor falls back to `settings.elasticsearch_index` | Make `index_name` required |
| `src/pam/retrieval/hybrid_search.py` | Constructor falls back to `settings.elasticsearch_index` | Make `index_name` required |
| `src/pam/retrieval/haystack_search.py` | Constructor falls back to `settings.*` for 3 params | Make all params required |
| `src/pam/agent/agent.py` | Constructor falls back to `settings.anthropic_api_key` + `settings.agent_model` | Make params required |
| `src/pam/agent/duckdb_service.py` | Constructor falls back to `settings.duckdb_data_dir` + `settings.duckdb_max_rows` | Make params required |
| `src/pam/ingestion/embedders/openai_embedder.py` | Constructor falls back to `settings.*` for 3 params | Make params required |
| `src/pam/ingestion/chunkers/hybrid_chunker.py` | `chunk_document()` falls back to `settings.chunk_size_tokens` | Accept as required param |

### Ruff Violation Counts (What to Fix)

| Rule | Count (src/) | Count (tests/) | Action |
|------|-------------|----------------|--------|
| B008 | 42 | 0 | `extend-immutable-calls` config (not code fixes) |
| FAST002 | 38 | 0 | **Ignore for now** or convert to Annotated (scope decision) |
| B905 | 6 | 0 | Add `strict=True` to `zip()` calls |
| PERF401 | 5 | 5 | Convert to list comprehensions |
| B904 | 4 | 0 | Add `from e` to `raise` in except blocks |
| ARG001 | 3 | 7 | Prefix unused args with `_` |
| S105 | 2 | 3 | Config-related, likely OK to ignore |
| RET505 | 2 | 0 | Remove superfluous else after return |
| ARG002 | 1 | 36 | Prefix unused method args with `_` (tests: ignore) |
| RET504 | 1 | 2 | Remove unnecessary assign before return |
| S608 | 1 | 0 | Hardcoded SQL (DuckDB service -- acceptable) |
| S101 | 0 | 859 | `per-file-ignores` for tests |
| PT019 | 0 | 17 | `per-file-ignores` for tests |
| PT011 | 0 | 2 | Narrow `pytest.raises()` match |

### Mypy Changes

| Setting | Current | Target | Impact |
|---------|---------|--------|--------|
| `check_untyped_defs` | false (default) | true | Only 1 existing violation (unreachable stmt in google_docs.py) |
| `warn_unreachable` | false (default) | true | Same 1 violation |
| `plugins` | none | `["pydantic.mypy"]` | Better Pydantic model checking |
| `[tool.pydantic-mypy]` | none | `init_forbid_extra`, `init_typed`, `warn_required_dynamic_aliases` | Stricter Pydantic validation |

## Open Questions

1. **FAST002 -- Convert to Annotated or Ignore?**
   - What we know: 38 violations in src/, all are `Depends()` without `Annotated`. The modern FastAPI pattern uses `Annotated`, but both are fully supported.
   - What's unclear: Whether the team wants to migrate to `Annotated` style in this phase or later.
   - Recommendation: **Ignore FAST002 in this phase** (add to `select` but also to `ignore`). It's a separate style migration that doesn't affect singleton lifecycle correctness. Can be a follow-up task.

2. **S608 (hardcoded SQL) in DuckDB service**
   - What we know: The DuckDB service constructs SQL strings by design (it's a SQL query executor). S608 will flag the SQL template strings.
   - What's unclear: Whether to suppress with `# noqa: S608` or per-file-ignore.
   - Recommendation: Add `# noqa: S608` to the specific lines, since the DuckDB service already has SQL injection guards.

3. **database.py and config.py Proxy Pattern**
   - What we know: Per prior decisions, `config.py` and `database.py` proxy patterns (lru_cache + reset_*()) are correct and should be kept.
   - What's unclear: After moving engine/session_factory creation to lifespan, should `database.py` proxies still exist or be removed?
   - Recommendation: Keep `database.py` functions (`get_engine`, `get_session_factory`) available for CLI/migration scripts that don't run through FastAPI. The lifespan creates its own instances; the proxies remain for non-API contexts.

4. **cache.py Module-Level Redis Globals**
   - What we know: `_redis_client` is a module-level global in `cache.py`, separate from `deps.py`. The `get_redis()` / `close_redis()` / `ping_redis()` functions use it.
   - What's unclear: Whether to refactor these free functions or just move Redis creation to lifespan and pass the client around.
   - Recommendation: Move Redis client creation to lifespan, store on `app.state.redis_client`. Keep the `ping_redis` function but have it accept a client parameter. `get_redis()` / `close_redis()` can be removed since lifespan manages the lifecycle.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** - Direct reading of deps.py, main.py, config.py, database.py, cache.py, task_manager.py, elasticsearch_store.py, duckdb_service.py, hybrid_search.py, haystack_search.py, agent.py, openai_embedder.py, hybrid_chunker.py
- **ruff 0.15.0 violation scan** - `ruff check src/ --select B,S,SIM,ARG,FAST,PT,RET,PERF,RUF --statistics` (105 src violations, 955 test violations)
- **mypy 1.19.1 scan** - `mypy --check-untyped-defs --warn-unreachable src/pam/` (1 violation: unreachable statement)
- [FastAPI Lifespan Events docs](https://fastapi.tiangolo.com/advanced/events/) - Official lifespan pattern
- [Ruff Rules reference](https://docs.astral.sh/ruff/rules/) - Rule category definitions
- [Pydantic mypy integration](https://docs.pydantic.dev/latest/integrations/mypy/) - Plugin configuration

### Secondary (MEDIUM confidence)
- [Ruff flake8-bugbear extend-immutable-calls](https://docs.astral.sh/ruff/settings/) - B008 + FastAPI Depends() solution
- [pytest-randomly](https://github.com/pytest-dev/pytest-randomly) - Test randomization plugin
- [SQLAlchemy mypy plugin deprecation](https://docs.sqlalchemy.org/en/20/orm/extensions/mypy.html) - SA mypy plugin deprecated, incompatible with mypy >=1.11

### Tertiary (LOW confidence)
- None. All findings verified via codebase analysis or official documentation.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All tools already in the project, just expanding configuration
- Architecture: HIGH - Pattern verified against FastAPI official docs and existing codebase structure
- Pitfalls: HIGH - Violation counts verified by running ruff/mypy; SQLAlchemy deprecation verified via official docs
- Inventory: HIGH - Every file inventoried by grepping `from pam.common.config import settings` and reading each module

**Research date:** 2026-02-15
**Valid until:** 2026-03-15 (30 days -- stable domain, no fast-moving dependencies)
