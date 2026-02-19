# Technology Stack: Code Quality & Cleanup Milestone

**Project:** PAM Context
**Researched:** 2026-02-15
**Focus:** Tooling and patterns for safe refactoring of an existing Python/FastAPI + React codebase

---

## Current Stack Baseline

Already in place -- these are not being changed, only cleaned up:

| Layer | Technology | Version |
|-------|-----------|---------|
| Runtime | Python 3.12 | 3.12+ |
| API | FastAPI | >=0.115 |
| ORM | SQLAlchemy (async) | >=2.0 |
| Migrations | Alembic | >=1.13 |
| Validation | Pydantic v2 + pydantic-settings | >=2.0 |
| Database | PostgreSQL 16, Elasticsearch 8.x | - |
| Frontend | React 18, TypeScript 5.6, Vite 6, Tailwind 4 | - |
| Tests | pytest 8 + pytest-asyncio, Vitest 4 (frontend) | - |
| Linting | Ruff 0.14.11 (installed), pre-commit | - |
| Type Checking | mypy 1.16.1 (installed) | - |

---

## Recommended Tooling for This Milestone

### 1. Ruff -- Expand Rule Coverage

**Confidence:** HIGH (official docs verified)

The project currently uses a narrow rule set: `select = ["E", "F", "I", "N", "W", "UP"]`. This misses several rule categories that directly catch the exact issues found in the 7 open GitHub issues.

**Recommended expanded configuration:**

```toml
[tool.ruff.lint]
select = [
    # Currently enabled
    "E",     # pycodestyle errors
    "F",     # Pyflakes
    "I",     # isort
    "N",     # pep8-naming
    "W",     # pycodestyle warnings
    "UP",    # pyupgrade

    # Add for this milestone
    "B",     # flake8-bugbear -- catches common bugs (unused loop vars, mutable defaults)
    "S",     # flake8-bandit -- security issues (bare except, hardcoded passwords)
    "SIM",   # flake8-simplify -- simplifiable code patterns
    "C4",    # flake8-comprehensions -- dict/list comprehension improvements
    "RET",   # flake8-return -- return statement best practices
    "PT",    # flake8-pytest-style -- pytest patterns
    "ARG",   # flake8-unused-arguments -- catches unused function args (Issue #36 item 5)
    "PERF",  # Perflint -- performance anti-patterns
    "FAST",  # FastAPI-specific -- redundant response_model, non-Annotated deps, unused path params
    "RUF",   # Ruff-specific -- catch-all for Ruff's own rules
]

# Suppress rules that conflict with existing patterns
ignore = [
    "S101",  # assert usage OK in tests
    "B008",  # Depends() in function args is a FastAPI pattern, not a bug
]

[tool.ruff.lint.per-file-ignores]
"tests/**" = ["S101", "ARG001", "ARG002"]  # asserts and fixtures use unused args
"alembic/**" = ["E501"]  # migration files can have long lines
```

**Why each addition matters for the open issues:**

| Rule | Catches | Relevant Issue |
|------|---------|----------------|
| `B` (bugbear) | Bare except, mutable default args, unused loop vars | #36 (unused `orig_idx`), #43 (bare except) |
| `S` (bandit) | Hardcoded credentials, bare except blocks | #43 (swallowed exceptions) |
| `SIM` | Simplifiable conditionals, unnecessary nesting | General cleanup |
| `ARG` | Unused function arguments | #36 (unused `orig_idx`) |
| `FAST` | FastAPI-specific: redundant response_model, non-Annotated deps | #43 (missing response_model) |
| `PT` | Pytest style issues (fixture scope, parametrize patterns) | #39 (test improvements) |
| `RET` | Unnecessary else after return, implicit returns | General cleanup |
| `PERF` | Unnecessary list() in iteration, dict copy patterns | General cleanup |

**Version:** Keep ruff >=0.14 (installed 0.14.11). Ruff 0.15.0 introduces the 2026 style guide which changes formatting; adopt that only if ready for a formatting diff across the codebase. Not required for this milestone.

**Source:** [Ruff Rules Documentation](https://docs.astral.sh/ruff/rules/), [Ruff Configuration](https://docs.astral.sh/ruff/configuration/)


### 2. mypy -- Tighten Configuration

**Confidence:** HIGH (official docs + installed version verified)

The current mypy config is minimal:

```toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
```

**Recommended expansion for this milestone:**

```toml
[tool.mypy]
python_version = "3.12"
warn_return_any = true
warn_unused_configs = true
warn_unreachable = true
disallow_any_generics = true
check_untyped_defs = true
no_implicit_reexport = true

# Plugin support for SQLAlchemy and Pydantic
plugins = ["pydantic.mypy", "sqlalchemy.ext.mypy.plugin"]

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false  # tests don't need full typing

[[tool.mypy.overrides]]
module = "alembic.*"
ignore_errors = true
```

**Why:** The current config does not enable `check_untyped_defs`, meaning functions without type annotations are silently skipped. Several issues (#43 item 1 -- missing response_model, #32 -- singleton typing) would surface with these settings.

**Do NOT enable `strict = true`** for this milestone. That would require adding type annotations to every function signature across the entire codebase -- a much larger effort. The settings above add meaningful safety without requiring a full annotation pass.

**Source:** [mypy Configuration](https://mypy.readthedocs.io/en/stable/config_file.html)


### 3. Alembic -- Index Migration Strategy

**Confidence:** HIGH (official SQLAlchemy/Alembic docs verified)

Issue #39 identifies missing database indexes on `Document.content_hash`, `Document.source_type+source_id` (composite), and `Segment.document_id`.

**Pattern: Define indexes in SQLAlchemy models, generate migration with autogenerate.**

For single-column indexes, use `index=True` on the column:

```python
content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
document_id: Mapped[uuid.UUID] = mapped_column(
    UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), index=True
)
```

For composite indexes, use `__table_args__`:

```python
__table_args__ = (
    UniqueConstraint("source_type", "source_id", name="uq_documents_source"),
    Index("ix_documents_source_lookup", "source_type", "source_id"),
    {"comment": "Source document registry"},
)
```

Then generate: `alembic revision --autogenerate -m "add_missing_indexes"`

**Important:** The `UniqueConstraint` on `(source_type, source_id)` already exists. A unique constraint implicitly creates an index in PostgreSQL, so the composite lookup index already exists. Only `content_hash` and `Segment.document_id` actually need new indexes.

**Use `CREATE INDEX CONCURRENTLY`** in the migration to avoid table locks on production data. Alembic migration:

```python
from alembic import op

def upgrade():
    # CONCURRENTLY requires autocommit
    op.execute("COMMIT")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_documents_content_hash ON documents (content_hash)")
    op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_segments_document_id ON segments (document_id)")
```

**Source:** [SQLAlchemy 2.0 Constraints and Indexes](https://docs.sqlalchemy.org/en/20/core/constraints.html), [Alembic Autogenerate](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)


### 4. FastAPI Dependency Injection -- Singleton Refactoring Pattern

**Confidence:** HIGH (FastAPI official docs + community consensus)

Issue #32 (the only "important" issue) concerns module-level singletons in `deps.py` using global variables with asyncio locks. This is the most impactful change in the milestone.

**Recommended pattern: FastAPI lifespan + app.state**

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create singletons once
    app.state.embedder = OpenAIEmbedder()
    app.state.search_service = await create_search_service(app.state.es_client)
    app.state.duckdb_service = create_duckdb_service()
    yield
    # Shutdown: cleanup
    await app.state.es_client.close()

app = FastAPI(lifespan=lifespan)
```

Then in deps.py, replace globals with `request.app.state`:

```python
def get_embedder(request: Request) -> OpenAIEmbedder:
    return request.app.state.embedder
```

**Why lifespan over globals:**
- Testability: Override `app.state` in test fixtures without monkeypatching globals
- Lifecycle management: Clean startup/shutdown guarantees
- No asyncio.Lock complexity: Initialization happens once before first request
- Already partially used: `es_client` and `redis_client` already use `app.state`

**What to preserve:** The existing `config.py` lazy proxy pattern (`_SettingsProxy`) and `database.py` lazy pattern (`_EngineProxy`) are fine. They use `lru_cache` correctly and have `reset_*()` functions for testing. Issue #32 is specifically about the _deps.py_ globals, not these.

**Source:** [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/), [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)


### 5. Pure ASGI Middleware -- Replace BaseHTTPMiddleware

**Confidence:** HIGH (Starlette official docs + well-documented issue)

Issue #43 item 8 flags that `BaseHTTPMiddleware` buffers streaming responses, which breaks SSE streaming used by the chat endpoint.

**Replace with pure ASGI middleware:**

```python
class CorrelationIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        cid = headers.get(b"x-correlation-id", b"").decode() or None
        cid = set_correlation_id(cid)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-correlation-id", cid.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_wrapper)
```

**Why:** BaseHTTPMiddleware reads the entire response body into memory before returning. For SSE streaming (chat endpoint), this means the client receives nothing until the entire response is complete, defeating the purpose of streaming. Pure ASGI middleware passes through chunks as they arrive.

**Source:** [Starlette Middleware Docs](https://starlette.dev/middleware/), [BaseHTTPMiddleware Deprecation Discussion](https://github.com/Kludex/starlette/discussions/2160)


### 6. Pydantic Response Models -- API Cleanup

**Confidence:** HIGH (FastAPI official docs)

Issue #43 item 1 identifies several endpoints returning plain dicts without `response_model`. This prevents OpenAPI documentation generation and response validation.

**Pattern: Use `response_model` parameter or return type annotations (FastAPI supports both since 0.95+):**

```python
# Preferred: return type annotation (cleaner, validated same as response_model)
@router.get("/documents")
async def list_documents(db: AsyncSession = Depends(get_db)) -> list[DocumentResponse]:
    ...

# Alternative: response_model parameter (use when return type differs from response)
@router.get("/documents/{id}", response_model=DocumentResponse)
async def get_document(id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    ...
```

**Naming convention for new schemas:**
- Response schemas: `*Response` (e.g., `StatsResponse`, `SegmentDetailResponse`)
- All schemas in `src/pam/common/models.py` (where existing schemas live)

**Source:** [FastAPI Response Model](https://fastapi.tiangolo.com/tutorial/response-model/)


### 7. Dead Code Detection -- vulture

**Confidence:** MEDIUM (multiple sources, well-established tool)

Issue #40 item 3 identifies `CitationLink.tsx` as dead code. For systematic dead code detection across the Python codebase:

**Use vulture** for a one-time sweep:

```bash
pip install vulture
vulture src/pam/ --min-confidence 80
```

**Why vulture over alternatives:**
- Well-established (10+ years), low false positive rate at 80% confidence
- Does not require runtime execution (unlike coverage-based approaches)
- Single-purpose: find dead code, not a framework
- Alternative `deadcode` offers `--fix` flag but is newer and less battle-tested

**Do NOT add vulture to CI** -- it has false positives with dynamic dispatch (FastAPI route handlers, SQLAlchemy event listeners). Use it as a one-time sweep, verify findings manually, then remove confirmed dead code.

For the React frontend, TypeScript's `noUnusedLocals` is already enabled in tsconfig.json. Adding ESLint would help but is outside this milestone's Python-focused scope.

**Source:** [vulture on GitHub](https://github.com/jendrikseipp/vulture)


### 8. complexipy -- Cognitive Complexity Analysis

**Confidence:** MEDIUM (well-documented, but not in Context7)

Use `complexipy` for identifying functions that need refactoring before touching them:

```bash
pip install complexipy
complexipy src/pam/ --max-complexity 15
```

**Why:** Cognitive complexity (not cyclomatic complexity) measures how hard code is to _understand_. Functions above 15 are candidates for extraction/simplification. Run before refactoring to prioritize which functions to break apart.

**Do NOT add to CI** for this milestone. Use as a diagnostic tool to guide refactoring priorities.

**Source:** [complexipy on PyPI](https://pypi.org/project/complexipy/)


### 9. pytest-cov -- Coverage Safety Net

**Confidence:** HIGH (already installed, just needs enforcing)

The project already has pytest-cov configured with `fail_under = 80`. Before any refactoring:

```bash
pytest --cov=src/pam --cov-report=html --cov-report=term-missing
```

**Rule for this milestone:** Run coverage before AND after each refactoring step. Coverage must not decrease. The project has 450+ tests -- this is the safety net.

**Source:** [pytest-cov on PyPI](https://pypi.org/project/pytest-cov/)

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Linting | Ruff (expand rules) | Pylint | Ruff already installed, 100x faster, covers same rules via B/SIM/RET |
| Type checking | mypy (tighten config) | pyright/pytype | mypy already installed with 1.16.1, mature SQLAlchemy plugin support |
| Dead code | vulture (one-time) | deadcode, Skylos | vulture is battle-tested; deadcode's `--fix` is tempting but riskier for existing code |
| Complexity | complexipy (diagnostic) | radon, wily | complexipy uses cognitive complexity (better metric), written in Rust (fast) |
| Formatting | Ruff formatter (keep current) | Black | Ruff replaces Black, already configured |
| Security | Ruff S rules | standalone bandit | Ruff's S rules are the same checks, integrated, faster |
| Middleware | Pure ASGI | Keep BaseHTTPMiddleware | BaseHTTPMiddleware buffers streaming -- confirmed issue with SSE |
| DI pattern | lifespan + app.state | dependency-injector library | Adds unnecessary complexity; FastAPI's built-in DI is sufficient |
| Frontend lint | TypeScript strict (already on) | Add ESLint | ESLint is valuable but scope creep for a Python-focused cleanup milestone |

---

## What NOT to Do

### Do NOT upgrade to Ruff 0.15+ during this milestone
Ruff 0.15.0 (released 2026-02-03) introduces the "2026 style guide" which changes formatting. This would produce a massive formatting diff across every file. Do formatting upgrades in a separate, dedicated PR.

### Do NOT enable mypy `strict = true`
Strict mode requires type annotations on every function, including all test helpers. This is a large separate effort. The targeted settings above add safety without the annotation burden.

### Do NOT refactor config.py or database.py proxy patterns
Issue #32 mentions these, but they already use `lru_cache` with `reset_*()` functions. The proxy pattern is fine. The real problem is the module-level globals in `deps.py`.

### Do NOT add ESLint to the frontend in this milestone
The open frontend issues (#40) are specific fixes (array keys, useCallback, dead component). They don't require new tooling -- just code changes guided by React best practices.

### Do NOT run vulture in CI
False positives with FastAPI route decorators, SQLAlchemy event listeners, and Pydantic model fields. Use as a one-time diagnostic only.

### Do NOT change test runner or framework
pytest + pytest-asyncio + pytest-cov is the correct stack. Don't switch to anything else.

---

## Installation

```bash
# Already installed (just update ruff config in pyproject.toml):
# ruff, mypy, pytest, pytest-cov, pytest-asyncio, pre-commit

# One-time diagnostic tools (NOT added to dependencies):
pip install vulture complexipy

# Pre-commit hooks (already configured, no changes needed):
# .pre-commit-config.yaml already has ruff + ruff-format
```

No new production dependencies. No new dev dependencies in pyproject.toml. The expanded ruff rules and mypy config are pure configuration changes.

---

## Sources

- [Ruff Rules Reference](https://docs.astral.sh/ruff/rules/) -- HIGH confidence
- [Ruff Configuration Guide](https://docs.astral.sh/ruff/configuration/) -- HIGH confidence
- [Ruff v0.15.0 Blog Post](https://astral.sh/blog/ruff-v0.15.0) -- HIGH confidence
- [mypy Configuration File](https://mypy.readthedocs.io/en/stable/config_file.html) -- HIGH confidence
- [SQLAlchemy 2.0 Constraints and Indexes](https://docs.sqlalchemy.org/en/20/core/constraints.html) -- HIGH confidence
- [Alembic Autogenerate Docs](https://alembic.sqlalchemy.org/en/latest/autogenerate.html) -- HIGH confidence
- [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/) -- HIGH confidence
- [FastAPI Response Model](https://fastapi.tiangolo.com/tutorial/response-model/) -- HIGH confidence
- [Starlette Middleware](https://starlette.dev/middleware/) -- HIGH confidence
- [BaseHTTPMiddleware Deprecation Discussion](https://github.com/Kludex/starlette/discussions/2160) -- MEDIUM confidence
- [vulture on GitHub](https://github.com/jendrikseipp/vulture) -- MEDIUM confidence
- [complexipy on PyPI](https://pypi.org/project/complexipy/) -- MEDIUM confidence
- [Python Typing Survey 2025 (Meta)](https://engineering.fb.com/2025/12/22/developer-tools/python-typing-survey-2025-code-quality-flexibility-typing-adoption/) -- MEDIUM confidence
- [How to configure recommended Ruff defaults](https://pydevtools.com/handbook/how-to/how-to-configure-recommended-ruff-defaults/) -- MEDIUM confidence
