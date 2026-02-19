# Phase 2: Database Integrity - Research

**Researched:** 2026-02-16
**Domain:** PostgreSQL indexes, CHECK constraints, Alembic migrations, Pydantic validation
**Confidence:** HIGH

## Summary

Phase 2 is a focused database-hardening phase with six concrete requirements. The work involves adding missing indexes (DB-01, DB-02), a CHECK constraint (DB-03), using non-locking migration strategy (DB-04), improving Pydantic validation (TOOL-03), and fixing a test isolation issue (TOOL-04).

Critical finding: Migration 001 **already creates** `idx_segments_document_id` on `segments.document_id` and `idx_segments_content_hash` on `segments.content_hash`. The requirements DB-01 (index on `Segment.document_id`) and DB-02 (index on `Document.content_hash`) need careful interpretation:
- DB-01 may be satisfied already, OR the requirement intends to verify/ensure the index exists at the ORM model level (it is not declared in `models.py`, only in the migration)
- DB-02 targets `Document.content_hash` (not `Segment.content_hash` which already has an index). The `documents.content_hash` column has **no index** currently.

**Primary recommendation:** Create a single new Alembic migration (005) that adds the missing `Document.content_hash` index and `UserProjectRole.role` CHECK constraint using `CREATE INDEX CONCURRENTLY` via `autocommit_block()`. Update `AssignRoleRequest.role` to use `Literal` type. Fix `test_env_override` to use `clear=True`.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | 2.0.46 | ORM with `mapped_column`, `Mapped[]` typing | Already in use, mature PostgreSQL dialect |
| Alembic | 1.18.3 | Schema migrations | Already in use, supports `autocommit_block()` |
| Pydantic | 2.x | Request/response validation | Already in use with `BaseModel` |
| pydantic-settings | 2.x | Environment-based configuration | Already in use for `Settings` class |
| psycopg | 3.x | PostgreSQL driver | Already in use (sync for migrations, async for app) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest | 8.x | Test framework | Existing test suite uses it |
| pytest-asyncio | 0.23+ | Async test support | `asyncio_mode = "auto"` in pyproject.toml |

### Alternatives Considered
None needed -- this phase uses only existing dependencies.

## Architecture Patterns

### Current Migration Pattern
```
alembic/
├── env.py                          # Reads DATABASE_URL from env, uses sync engine
├── versions/
│   ├── 001_initial_schema.py       # Creates projects, documents, segments, sync_log + indexes
│   ├── 002_add_ingestion_tasks.py  # Creates ingestion_tasks + indexes
│   ├── 003_add_users_and_roles.py  # Creates users, user_project_roles
│   └── 004_add_extracted_entities.py  # Creates extracted_entities + indexes
```

Migration naming convention: sequential `00N_descriptive_name.py` with string revision IDs (`"001"`, `"002"`, etc.).

### Pattern 1: CREATE INDEX CONCURRENTLY in Alembic
**What:** Creating indexes without locking the table for writes
**When to use:** Any index creation on tables that may contain production data
**Example:**
```python
# Source: Alembic official docs - MigrationContext.autocommit_block()
from alembic import op

def upgrade() -> None:
    # autocommit_block COMMITS any preceding transaction, then runs in autocommit mode
    with op.get_context().autocommit_block():
        op.create_index(
            "idx_documents_content_hash",
            "documents",
            ["content_hash"],
            postgresql_concurrently=True,
        )
```

**Critical details:**
1. `CREATE INDEX CONCURRENTLY` **cannot run inside a transaction** -- PostgreSQL will reject it
2. `autocommit_block()` commits any pending transaction, then switches to autocommit
3. Downgrade must also use `autocommit_block()` with `postgresql_concurrently=True` for `drop_index`
4. `if_not_exists=True` is recommended alongside `postgresql_concurrently=True` for idempotency (if the migration is interrupted, re-running won't fail on an already-created index)

### Pattern 2: CHECK Constraint via Alembic
**What:** Database-level enforcement of valid values for `UserProjectRole.role`
**When to use:** When domain values are a fixed, small set and must be enforced at DB level
**Example:**
```python
from alembic import op

def upgrade() -> None:
    op.create_check_constraint(
        "ck_user_project_roles_role",
        "user_project_roles",
        "role IN ('viewer', 'editor', 'admin')",
    )

def downgrade() -> None:
    op.drop_constraint("ck_user_project_roles_role", "user_project_roles")
```

**Note:** CHECK constraints are lightweight DDL and do NOT need `CONCURRENTLY` -- they acquire a brief `ACCESS EXCLUSIVE` lock but execute nearly instantly on small tables. They CAN run inside a transaction.

### Pattern 3: SQLAlchemy Model-Level Index Declaration
**What:** Declaring indexes in `__table_args__` or via `mapped_column(index=True)` so the ORM model is the source of truth
**When to use:** To keep models.py synchronized with the actual database schema
**Example:**
```python
from sqlalchemy import Index

class Document(Base):
    __tablename__ = "documents"
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # OR equivalently in __table_args__:
    # __table_args__ = (
    #     Index("idx_documents_content_hash", "content_hash"),
    #     ...
    # )
```

### Pattern 4: Pydantic Literal Type for Fixed Value Sets
**What:** Using `Literal["viewer", "editor", "admin"]` instead of `Field(pattern=...)`
**When to use:** When the valid values are a fixed set of strings
**Example:**
```python
from typing import Literal

class AssignRoleRequest(BaseModel):
    user_id: uuid.UUID
    project_id: uuid.UUID
    role: Literal["viewer", "editor", "admin"]
```

**Advantages over `Field(pattern=r"^(viewer|editor|admin)$")`:**
- mypy and type checkers understand the valid values
- Pydantic generates a cleaner OpenAPI `enum` schema instead of `pattern`
- Error messages are more user-friendly ("Input should be 'viewer', 'editor' or 'admin'" vs regex match failure)
- No regex to maintain

### Anti-Patterns to Avoid
- **Adding indexes inside a transaction:** PostgreSQL will error on `CREATE INDEX CONCURRENTLY` inside a transaction block. Always use `autocommit_block()`.
- **Splitting CONCURRENTLY indexes and transactional DDL in the same migration without care:** `autocommit_block()` commits all preceding work. If you have CHECK constraint + CONCURRENT index in one migration, put the CHECK constraint FIRST (it runs in the transaction), then `autocommit_block()` for the index (which commits everything before it).
- **Forgetting `if_not_exists`:** A `CREATE INDEX CONCURRENTLY` that fails midway leaves a partial/invalid index. Using `if_not_exists=True` prevents errors on re-run.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Concurrent index creation | Raw SQL `op.execute()` | `op.create_index(..., postgresql_concurrently=True)` | Alembic/SQLAlchemy handle the dialect-specific DDL generation |
| Role validation | Custom validator function | `Literal["viewer", "editor", "admin"]` | Built into Python typing + Pydantic |
| Non-transactional DDL | Manual `COMMIT` statements | `op.get_context().autocommit_block()` | Alembic manages connection state correctly |

**Key insight:** Every requirement in this phase has a well-supported, standard solution. No custom code is needed beyond wiring together existing library features.

## Common Pitfalls

### Pitfall 1: CONCURRENTLY Inside a Transaction
**What goes wrong:** PostgreSQL raises `CREATE INDEX CONCURRENTLY cannot run inside a transaction block`
**Why it happens:** Alembic wraps migrations in a transaction by default
**How to avoid:** Use `op.get_context().autocommit_block()` context manager
**Warning signs:** Migration fails with explicit error about transaction block

### Pitfall 2: Ordering Within autocommit_block Migrations
**What goes wrong:** CHECK constraint or other transactional DDL gets committed prematurely or fails to roll back on error
**Why it happens:** `autocommit_block()` unconditionally commits the preceding transaction
**How to avoid:** Put all transactional DDL (CHECK constraints) BEFORE the `autocommit_block()`. The order should be: (1) transactional DDL, (2) autocommit_block with CONCURRENT indexes. OR split into separate migrations.
**Warning signs:** Partial migration state after failure

### Pitfall 3: Duplicate Index on Segment.document_id
**What goes wrong:** Creating a second index on `segments.document_id` when `idx_segments_document_id` already exists (from migration 001)
**Why it happens:** DB-01 requirement says "Index added on Segment.document_id FK column" but it already exists in the database
**How to avoid:** Verify existing indexes before creating new ones. The requirement may refer to ensuring the index declaration exists in `models.py` (it currently does NOT have `index=True` on the column) while the migration already creates it.
**Warning signs:** Migration error about duplicate index name

### Pitfall 4: test_env_override CI Leaks
**What goes wrong:** Tests pass locally but fail in CI because CI has env vars like `DATABASE_URL` set that leak into the `Settings()` constructor
**Why it happens:** `test_env_override` uses `clear=False` in `patch.dict(os.environ, ...)`, so CI environment variables are inherited
**How to avoid:** Change to `clear=True` so only the explicitly defined env vars are visible during the test
**Warning signs:** Tests that pass locally but fail in CI with unexpected config values

### Pitfall 5: Forgetting the Model-Migration Sync
**What goes wrong:** Alembic autogenerate sees a diff between models.py and the database, generating unwanted migrations
**Why it happens:** Index/constraint exists in migration but not declared in the ORM model, or vice versa
**How to avoid:** When adding indexes/constraints via migration, also update `models.py` to reflect them (using `index=True` on `mapped_column` or `Index()` / `CheckConstraint()` in `__table_args__`)

## Code Examples

### Migration 005: Add Document.content_hash Index + UserProjectRole CHECK Constraint
```python
"""Add index on documents.content_hash and CHECK constraint on user_project_roles.role.

Revision ID: 005
Revises: 004
Create Date: 2026-02-16 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. CHECK constraint runs inside the transaction (fast, safe)
    op.create_check_constraint(
        "ck_user_project_roles_role",
        "user_project_roles",
        "role IN ('viewer', 'editor', 'admin')",
    )

    # 2. CONCURRENT index must run outside a transaction
    with op.get_context().autocommit_block():
        op.create_index(
            "idx_documents_content_hash",
            "documents",
            ["content_hash"],
            if_not_exists=True,
            postgresql_concurrently=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "idx_documents_content_hash",
            table_name="documents",
            postgresql_concurrently=True,
            if_exists=True,
        )
    op.drop_constraint("ck_user_project_roles_role", "user_project_roles")
```

### Updated AssignRoleRequest (TOOL-03)
```python
from typing import Literal

class AssignRoleRequest(BaseModel):
    user_id: uuid.UUID
    project_id: uuid.UUID
    role: Literal["viewer", "editor", "admin"]
```

### Updated test_env_override (TOOL-04)
```python
def test_env_override(self):
    """Settings should be overridable via environment variables."""
    env = {
        "DATABASE_URL": "postgresql+psycopg://other:other@db:5432/other",
        "ELASTICSEARCH_URL": "http://es:9200",
        "ELASTICSEARCH_INDEX": "custom_index",
        "EMBEDDING_DIMS": "768",
        "CHUNK_SIZE_TOKENS": "256",
        "LOG_LEVEL": "DEBUG",
        "OPENAI_API_KEY": "sk-test",
        "ANTHROPIC_API_KEY": "ant-test",
    }
    with patch.dict(os.environ, env, clear=True):
        s = Settings(_env_file=None)
        assert s.database_url == "postgresql+psycopg://other:other@db:5432/other"
        # ... remaining assertions
```

### Updated models.py Index Declarations
```python
class Document(Base):
    __tablename__ = "documents"
    # ...
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    # ...

class Segment(Base):
    __tablename__ = "segments"
    # ...
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("documents.id", ondelete="CASCADE"),
        index=True,  # Explicit: migration 001 creates idx_segments_document_id
    )
    # ...

class UserProjectRole(Base):
    __tablename__ = "user_project_roles"
    # ...
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    # ...
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="ix_user_project_roles_unique"),
        CheckConstraint("role IN ('viewer', 'editor', 'admin')", name="ck_user_project_roles_role"),
        {"comment": "RBAC: user-project role assignments"},
    )
```

## Existing State Analysis

### Current Indexes (from migrations)
| Table | Index | Columns | Created In |
|-------|-------|---------|------------|
| documents | `idx_documents_source` | source_type, source_id | 001 |
| documents | `uq_documents_source` (unique) | source_type, source_id | 001 |
| segments | `idx_segments_document_id` | document_id | 001 |
| segments | `idx_segments_content_hash` | content_hash | 001 |
| sync_log | `idx_sync_log_document_id` | document_id | 001 |
| ingestion_tasks | `idx_ingestion_tasks_status` | status | 002 |
| ingestion_tasks | `idx_ingestion_tasks_created_at` | created_at | 002 |
| users | `ix_users_email` | email | 003 |
| user_project_roles | `ix_user_project_roles_unique` (unique) | user_id, project_id | 003 |
| extracted_entities | `ix_extracted_entities_type` | entity_type | 004 |
| extracted_entities | `ix_extracted_entities_segment` | source_segment_id | 004 |

### Missing Indexes (to be added)
| Table | Column | Needed For | Query Evidence |
|-------|--------|-----------|----------------|
| documents | content_hash | DB-02: dedup lookups | `pipeline.py:64` compares hash after fetching by source, but direct hash lookups are needed for change detection at scale |

### Existing Index That Satisfies DB-01
`idx_segments_document_id` on `segments.document_id` was created in migration 001. However, `models.py` does NOT declare `index=True` on the `document_id` column of `Segment`. The requirement may mean: ensure the ORM model reflects this index declaration.

### Queries Using These Columns
| File | Line | Query Pattern | Index Used |
|------|------|---------------|------------|
| `postgres_store.py` | 62 | `delete(Segment).where(Segment.document_id == document_id)` | `idx_segments_document_id` |
| `postgres_store.py` | 100 | `select(Document).where(Document.source_type == ..., Document.source_id == ...)` | `idx_documents_source` |
| `pipeline.py` | 64 | `existing_doc.content_hash == new_hash` (Python-side comparison, not SQL WHERE) | N/A |
| `documents.py` | 42 | `select(Document).where(Document.id == segment.document_id)` | PK index |

### Current Role Validation
- `AssignRoleRequest.role`: uses `Field(pattern=r"^(viewer|editor|admin)$")` -- works but not type-safe
- `UserProjectRole.role`: no CHECK constraint in DB -- any string accepted at database level
- `models.py` line 103: comment says `# viewer, editor, admin` but not enforced

### Current Test Issue (TOOL-04)
- `test_env_override` at `tests/test_common/test_config.py:46` uses `clear=False`
- `test_default_values` at line 13 correctly uses `clear=True`
- The inconsistency means `test_env_override` inherits CI env vars, potentially causing false passes/failures

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `Field(regex=...)` | `Field(pattern=...)` | Pydantic v2 (2023) | Already using `pattern`, but `Literal` is better for enums |
| `op.execute("CREATE INDEX CONCURRENTLY ...")` | `op.create_index(..., postgresql_concurrently=True)` | SQLAlchemy 1.x+ | Type-safe, dialect-aware DDL generation |
| Manual `COMMIT` in migrations | `op.get_context().autocommit_block()` | Alembic 1.11+ | Proper connection state management |

## Open Questions

1. **Should DB-01 create a new index or just update models.py?**
   - What we know: `idx_segments_document_id` already exists in migration 001 and in the database
   - What's unclear: Does DB-01 require a NEW migration adding this index, or just ensuring the model declares it?
   - Recommendation: Update `models.py` to add `index=True` on `Segment.document_id`. Do NOT create a duplicate index in migration 005. The requirement is satisfied by the existing index; the gap is only in the ORM model declaration.

2. **Should the CHECK constraint migration be separate from the index migration?**
   - What we know: CHECK constraint is transactional; CONCURRENT index is not
   - What's unclear: Whether to put both in one migration or split
   - Recommendation: Single migration (005) with CHECK first, then `autocommit_block()` for the index. This keeps the phase as one atomic migration version.

## Sources

### Primary (HIGH confidence)
- **Codebase inspection** - `src/pam/common/models.py`, all 4 existing Alembic migrations, `src/pam/ingestion/stores/postgres_store.py`, `src/pam/ingestion/pipeline.py`, `src/pam/api/routes/admin.py`, `tests/test_common/test_config.py`
- **Alembic 1.18.3 installed** - Verified `MigrationContext.autocommit_block()` exists via `hasattr()` check
- **SQLAlchemy 2.0.46** - `create_index` accepts `**kw` which passes through to PostgreSQL dialect (`postgresql_concurrently=True`)

### Secondary (MEDIUM confidence)
- [Alembic official docs - MigrationContext.autocommit_block()](https://alembic.sqlalchemy.org/en/latest/api/runtime.html) - Confirmed autocommit_block pattern for non-transactional DDL
- [Alembic GitHub Issue #277](https://github.com/sqlalchemy/alembic/issues/277) - Original discussion of CONCURRENTLY support
- [Squawk PostgreSQL linter](https://squawkhq.com/docs/require-concurrent-index-creation) - Best practice: always use CONCURRENTLY for production index creation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - all libraries already in use, versions verified
- Architecture: HIGH - patterns verified against installed library code and official docs
- Pitfalls: HIGH - based on direct codebase inspection and known PostgreSQL behavior

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (stable domain, no expected breaking changes)
