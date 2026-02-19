---
phase: 02-database-integrity
plan: 01
subsystem: database
tags: [postgresql, alembic, sqlalchemy, pydantic, index, check-constraint, literal-type]

# Dependency graph
requires:
  - phase: 01-singleton-lifecycle
    provides: "Clean models.py and service lifecycle"
provides:
  - "Migration 005: content_hash index + role CHECK constraint"
  - "ORM model declarations synced with database schema (index=True, CheckConstraint)"
  - "AssignRoleRequest.role validated via Literal type with enum schema"
  - "Test environment isolation via clear=True in all patch.dict calls"
affects: [03-api-agent-hardening, 04-frontend-dead-code]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "CREATE INDEX CONCURRENTLY via autocommit_block() for non-locking migrations"
    - "CheckConstraint in __table_args__ for DB-level enum enforcement"
    - "Literal type for Pydantic enum fields (replaces Field(pattern=...))"
    - "clear=True in patch.dict for hermetic test isolation"

key-files:
  created:
    - "alembic/versions/005_add_content_hash_index_and_role_constraint.py"
  modified:
    - "src/pam/common/models.py"
    - "tests/test_common/test_config.py"

key-decisions:
  - "Single migration 005 for both CHECK constraint and CONCURRENT index (constraint first, then autocommit_block)"
  - "Literal type over Field(pattern=...) for role validation (better mypy support, cleaner OpenAPI enum)"
  - "ORM index=True declarations to sync models.py with existing database indexes"

patterns-established:
  - "autocommit_block pattern: transactional DDL first, then CONCURRENT index inside autocommit_block"
  - "Literal type for fixed value sets in Pydantic schemas"

# Metrics
duration: 3min
completed: 2026-02-16
---

# Phase 2 Plan 1: Database Integrity Summary

**Content_hash index (CONCURRENTLY), role CHECK constraint, Literal enum validation, and test isolation fix**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-15T20:54:14Z
- **Completed:** 2026-02-15T20:57:23Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created Alembic migration 005 with CHECK constraint on user_project_roles.role and CONCURRENT index on documents.content_hash
- Synced ORM model declarations with database schema (index=True on Segment.document_id and Document.content_hash, CheckConstraint on UserProjectRole)
- Replaced regex-based role validation with Literal type for proper OpenAPI enum schema and mypy support
- Fixed test environment isolation by switching all patch.dict calls to clear=True

## Task Commits

Each task was committed atomically:

1. **Task 1: Create Alembic migration 005 and update ORM model declarations** - `1cb1682` (feat)
2. **Task 2: Switch AssignRoleRequest.role to Literal type and fix test_env_override isolation** - `1a7e89e` (fix)

## Files Created/Modified
- `alembic/versions/005_add_content_hash_index_and_role_constraint.py` - Migration adding content_hash index (CONCURRENTLY) and role CHECK constraint
- `src/pam/common/models.py` - Added CheckConstraint import, index=True on document_id/content_hash, CheckConstraint in __table_args__, Literal type for AssignRoleRequest.role
- `tests/test_common/test_config.py` - Changed clear=False to clear=True in test_env_override and test_cors_origins_list

## Decisions Made
- Single migration 005 for both CHECK constraint and CONCURRENT index, with CHECK first (committed by autocommit_block) then index in autocommit mode
- Used Literal["viewer", "editor", "admin"] instead of Field(pattern=...) for cleaner OpenAPI enum, better mypy inference, and user-friendly error messages
- Added index=True to Segment.document_id even though the DB index already exists from migration 001 -- keeps ORM model as source of truth

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed ruff linting violations in migration file**
- **Found during:** Task 1 (migration creation)
- **Issue:** Migration file used old-style `from typing import Sequence, Union` and `Union[str, None]` which ruff flags as UP035/UP007
- **Fix:** Changed to `from collections.abc import Sequence` and `str | None` syntax
- **Files modified:** alembic/versions/005_add_content_hash_index_and_role_constraint.py
- **Verification:** ruff check passes
- **Committed in:** 1cb1682 (Task 1 commit)

**2. [Rule 1 - Bug] Fixed line length violation on Segment.document_id**
- **Found during:** Task 1 (models.py update)
- **Issue:** Adding `index=True` to the existing single-line mapped_column exceeded 120 char line limit
- **Fix:** Wrapped the mapped_column call across multiple lines
- **Files modified:** src/pam/common/models.py
- **Verification:** ruff check passes
- **Committed in:** 1cb1682 (Task 1 commit)

---

**Total deviations:** 2 auto-fixed (2 Rule 1 - bugs/linting)
**Impact on plan:** Both fixes were necessary for linting compliance. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Database integrity constraints are in place at both ORM and migration level
- AssignRoleRequest now provides proper enum schema for API consumers
- Test isolation is consistent across all config tests
- Ready for Phase 3 (API + Agent Hardening)

---
*Phase: 02-database-integrity*
*Completed: 2026-02-16*
