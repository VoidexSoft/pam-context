---
phase: 03-api-agent-hardening
plan: 02
subsystem: api
tags: [pagination, cursor, openapi, response-model, fastapi, pydantic]

# Dependency graph
requires:
  - phase: 03-01
    provides: ASGI middleware, SSE streaming, SearchService protocol
provides:
  - Cursor-based pagination on all list endpoints (documents, users, tasks)
  - PaginatedResponse generic schema and encode/decode cursor utilities
  - response_model on all document, admin, and ingest endpoints for OpenAPI visibility
  - SegmentDetailResponse, StatsResponse, RoleAssignedResponse, MessageResponse schemas
  - get_me returns 501 when auth disabled (was 404)
  - revoke_role returns 404 when role assignment not found (was silent 204)
  - get_segment uses single JOIN query via selectinload (was 2 sequential queries)
  - Frontend PaginatedResponse<T> interface and list function unwrapping
affects: [04-frontend-cleanup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Cursor-based keyset pagination with (sort_field DESC, id DESC) ordering"
    - "PaginatedResponse[T] generic envelope: {items, total, cursor}"
    - "Base64-encoded JSON cursor containing last item id and sort value"
    - "Fetch limit+1 rows to detect next page without extra query"
    - "Frontend unwrap pattern: response.items for backward compatibility"

key-files:
  created:
    - src/pam/api/pagination.py
    - tests/test_api/test_pagination.py
  modified:
    - src/pam/api/routes/documents.py
    - src/pam/api/routes/admin.py
    - src/pam/api/routes/auth.py
    - src/pam/api/routes/ingest.py
    - src/pam/common/models.py
    - web/src/api/client.ts

key-decisions:
  - "Keyset pagination over OFFSET-based: O(1) seek vs O(N) skip, stable under concurrent writes"
  - "Base64 JSON cursor instead of opaque token: debuggable, stateless, no server-side cursor storage"
  - "Count query on every request: tables are small, always show total for UI"
  - "Frontend unwrap pattern: list functions return items[] for backward compatibility, hooks unchanged"
  - "501 Not Implemented for get_me when auth disabled: semantically correct per HTTP spec"

patterns-established:
  - "Cursor pagination: all list endpoints accept cursor/limit query params, return PaginatedResponse envelope"
  - "Response schemas: every endpoint has response_model for OpenAPI documentation"

# Metrics
duration: 8min
completed: 2026-02-16
---

# Phase 3 Plan 2: API Pagination + OpenAPI + Edge-Case Fixes Summary

**Cursor-based keyset pagination on all list endpoints with PaginatedResponse envelope, response_model on all endpoints for OpenAPI visibility, and edge-case fixes (revoke_role 404, get_me 501, get_segment JOIN)**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-16T07:50:43Z
- **Completed:** 2026-02-16T07:58:43Z
- **Tasks:** 2
- **Files modified:** 12

## Accomplishments
- Created pagination.py module with PaginatedResponse[T] generic, encode_cursor/decode_cursor, DEFAULT_PAGE_SIZE
- Implemented keyset cursor pagination on GET /documents, GET /admin/users, GET /ingest/tasks
- Added response_model to all document, admin, and ingest endpoints -- full OpenAPI /docs visibility
- Added SegmentDetailResponse, StatsResponse, RoleAssignedResponse, MessageResponse Pydantic schemas
- Fixed get_me to return 501 (Not Implemented) when auth is disabled
- Fixed revoke_role to return 404 when role assignment does not exist
- Optimized get_segment to use single JOIN query via selectinload instead of 2 sequential queries
- Added PaginatedResponse<T> TypeScript interface and updated listDocuments/listTasks to unwrap .items
- 12 new pagination tests covering cursor roundtrip, traversal, empty cursor, invalid cursor

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pagination module, add response schemas, and add response_model to all endpoints** - `f98d30d` (feat)
2. **Task 2: Implement cursor pagination on all list endpoints and add frontend adapter** - `d082333` (feat)

## Files Created/Modified
- `src/pam/api/pagination.py` - NEW: PaginatedResponse generic, encode_cursor, decode_cursor, DEFAULT_PAGE_SIZE
- `src/pam/common/models.py` - Added SegmentDetailResponse, StatsResponse, RoleAssignedResponse, MessageResponse schemas
- `src/pam/api/routes/documents.py` - Cursor pagination on /documents, JOIN-based get_segment, response_model on all endpoints
- `src/pam/api/routes/admin.py` - Cursor pagination on /admin/users, revoke_role 404, response_model on all endpoints
- `src/pam/api/routes/auth.py` - get_me returns 501 when auth disabled
- `src/pam/api/routes/ingest.py` - Cursor pagination on /ingest/tasks, response_model on list endpoint
- `web/src/api/client.ts` - PaginatedResponse<T> interface, listDocuments/listTasks unwrap .items
- `tests/test_api/test_pagination.py` - NEW: 12 tests for pagination utilities and endpoint behavior
- `tests/test_api/test_documents.py` - Updated for paginated envelope shape
- `tests/test_api/test_admin.py` - Updated for paginated envelope shape
- `tests/test_api/test_auth.py` - Updated get_me test to expect 501, documents test for paginated shape
- `tests/test_api/test_ingest.py` - Updated for paginated envelope shape and direct DB query

## Decisions Made
- Keyset pagination over OFFSET-based: O(1) seek performance, stable under concurrent writes
- Base64 JSON cursor: debuggable, stateless, no server-side storage needed
- Always include total count: tables are small, UI needs total for display
- Frontend backward compatibility: unwrap response.items so hooks remain unchanged
- 501 Not Implemented for get_me when auth disabled: correct HTTP semantics

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All list endpoints now return cursor-paginated envelopes -- Phase 4 frontend can adopt full pagination UI
- All endpoints have response_model -- OpenAPI schema complete for documentation/client generation
- Edge cases (revoke_role 404, get_me 501) provide predictable API behavior
- 489 tests passing across full test suite

## Self-Check: PASSED

All 8 key files verified on disk. Both task commits (f98d30d, d082333) found in git log.

---
*Phase: 03-api-agent-hardening*
*Completed: 2026-02-16*
