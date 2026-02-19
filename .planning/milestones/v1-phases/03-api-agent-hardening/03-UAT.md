---
status: testing
phase: 03-api-agent-hardening
source: 03-01-SUMMARY.md, 03-02-SUMMARY.md, 03-03-SUMMARY.md
started: 2026-02-17T09:30:00Z
updated: 2026-02-17T09:30:00Z
---

## Current Test

number: 1
name: Full test suite passes
expected: |
  Running `pytest` completes with all tests passing (469+ tests). No failures or errors.
awaiting: user response

## Tests

### 1. Full test suite passes
expected: Running `pytest` completes with all tests passing (469+ tests). No failures or errors.
result: [pending]

### 2. SSE streaming unbuffered
expected: Chat tokens stream in real-time during agent response -- no delay-then-burst pattern. Each word appears progressively as the LLM generates it.
result: [pending]

### 3. Paginated document list
expected: GET /documents returns a JSON envelope with `items` (array of documents), `total` (integer count), and `cursor` (string or null). Not a bare array.
result: [pending]

### 4. Paginated user list
expected: GET /admin/users returns the same paginated envelope shape: `{items, total, cursor}`.
result: [pending]

### 5. OpenAPI docs show response schemas
expected: Visiting /docs shows response schemas for all endpoints. Document, admin, ingest, and auth routes all display their response model types (not just "Successful Response").
result: [pending]

### 6. get_me returns 501 when auth disabled
expected: GET /auth/me returns HTTP 501 Not Implemented with a message indicating the feature is not available (auth is disabled in Phase 1).
result: [pending]

### 7. revoke_role returns 404 for missing assignment
expected: DELETE /admin/projects/{id}/users/{id}/roles/{role} returns 404 when the role assignment doesn't exist (not a silent 204).
result: [pending]

### 8. No leading-space artifacts in streamed text
expected: During chat streaming, words are separated cleanly. No extra leading spaces at the start of SSE token chunks (e.g., "Hello world" not "Hello  world" or " world").
result: [pending]

### 9. Agent can call list_tables without SQL
expected: When the agent decides to discover database tables, the `list_tables` tool call works without requiring a SQL parameter. The QUERY_DATABASE_TOOL schema has an empty required list.
result: [pending]

### 10. CostTracker warns on unknown models
expected: If an unknown model name is used, CostTracker logs a warning with the model name instead of silently falling back to zero cost.
result: [pending]

## Summary

total: 10
passed: 0
issues: 0
pending: 10
skipped: 0

## Gaps

[none yet]
