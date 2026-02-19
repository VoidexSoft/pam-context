# Phase 3: API + Agent Hardening - Context

**Gathered:** 2026-02-16
**Status:** Ready for planning

<domain>
## Phase Boundary

Harden API endpoints with proper response models, pagination, and SSE streaming error handling. Fix agent tool schemas, chunk text artifacts, and cost tracking. Replace BaseHTTPMiddleware with pure ASGI middleware. No new features or endpoints — this is about correctness, reliability, and OpenAPI completeness.

</domain>

<decisions>
## Implementation Decisions

### SSE streaming & error handling
- When LLM API fails mid-stream, send BOTH a structured `event: error` with JSON payload {type, message} AND human-readable text — UI can choose how to display
- No retry on transient errors — fail fast, send error event immediately, let user retry from UI
- Stream lifecycle (done event after error vs immediate close) — Claude's discretion based on existing frontend SSE handling

### ASGI middleware
- Replace BaseHTTPMiddleware with pure ASGI middleware to fix SSE streaming buffering
- Scope of replacement (same as current vs adding request timing) — Claude's discretion based on what's minimal and useful

### Pagination design
- **Cursor-based pagination** (Nakama-style), NOT offset/limit
- Opaque base64-encoded cursor encoding last item's ID + sort field
- Empty string cursor = no more pages
- Response envelope: `{"items": [...], "total": N, "cursor": "base64..."}`
- Default page size: **50 items**
- Apply pagination to **all list endpoints**, not just GET /documents

### Error response patterns
- Error format (consistent envelope vs FastAPI default) — Claude's discretion based on what frontend expects
- 404 detail level for revoke_role — Claude's discretion
- get_me when auth disabled: return **501 Not Implemented**
- get_stats partial failure behavior — Claude's discretion

### Agent tool hardening
- CostTracker warning must include the model name: `"Unknown model 'claude-4-opus': using default cost estimate"`
- Search service interface (Protocol vs ABC) — Claude's discretion based on existing patterns
- Cache key hash length (full SHA-256 vs truncated) — Claude's discretion
- Chunk text leading space fix approach — Claude's discretion (investigate actual bug first)

### Claude's Discretion
- Stream lifecycle after error event (done then close, or just close)
- ASGI middleware scope (same as current or add request timing)
- Error response envelope format
- 404 message detail level
- get_stats partial failure handling
- Protocol vs ABC for search service interface
- Cache key hash length
- Chunk text whitespace fix approach

</decisions>

<specifics>
## Specific Ideas

- Pagination modeled after [Nakama game server](https://github.com/heroiclabs/nakama) — opaque base64 cursor encoding position state, cursor field empty when no more results
- Cursor encodes last item's ID + sort field (like Nakama encodes key + user_id + permission)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 03-api-agent-hardening*
*Context gathered: 2026-02-16*
