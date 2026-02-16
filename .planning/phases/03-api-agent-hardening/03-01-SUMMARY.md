---
phase: 03-api-agent-hardening
plan: 01
subsystem: api
tags: [asgi, middleware, sse, streaming, error-handling]

# Dependency graph
requires:
  - phase: 01-singleton-lifecycle-tooling
    provides: FastAPI app factory with middleware registration
provides:
  - Pure ASGI CorrelationIdMiddleware (unbuffered SSE passthrough)
  - Pure ASGI RequestLoggingMiddleware with latency_ms
  - Structured SSE error events with {type, data, message} payload
  - Fixed _chunk_text with trailing-space word separation
affects: [04-frontend-dead-code-cleanup]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Pure ASGI middleware pattern: __init__(app) + __call__(scope, receive, send)"
    - "Inner send wrapper for header injection and status capture"
    - "Trailing-space chunking for SSE token events"

key-files:
  created: []
  modified:
    - src/pam/api/middleware.py
    - src/pam/agent/agent.py
    - tests/test_api/test_middleware.py
    - tests/test_agent/test_agent.py

key-decisions:
  - "Pure ASGI over BaseHTTPMiddleware to eliminate SSE buffering"
  - "Structured SSE error events include both machine-readable data and human-readable message"
  - "No done event after error -- frontend handles cleanup in finally block"
  - "Trailing-space chunking instead of leading-space to fix token display artifacts"

patterns-established:
  - "Pure ASGI middleware: __call__(scope, receive, send) with scope type guard"
  - "SSE error event format: {type: 'error', data: {type, message}, message}"

# Metrics
duration: 4min
completed: 2026-02-16
---

# Phase 3 Plan 1: SSE Streaming Fix Summary

**Pure ASGI middleware replacing BaseHTTPMiddleware for unbuffered SSE streaming, structured error events, and trailing-space chunk text fix**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-16T07:44:35Z
- **Completed:** 2026-02-16T07:48:22Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Replaced BaseHTTPMiddleware with pure ASGI middleware, eliminating SSE streaming buffering
- Added structured SSE error events with machine-readable data and human-readable message fields
- Fixed _chunk_text leading-space artifact so non-first SSE token events render cleanly
- Added 14 new tests covering ASGI interface, error events, and chunk text behavior

## Task Commits

Each task was committed atomically:

1. **Task 1: Replace BaseHTTPMiddleware with pure ASGI middleware** - `5553b59` (feat)
2. **Task 2: Add structured SSE error events and fix _chunk_text** - `84839c6` (fix)

## Files Created/Modified

- `src/pam/api/middleware.py` - Pure ASGI CorrelationIdMiddleware and RequestLoggingMiddleware
- `src/pam/agent/agent.py` - Structured SSE error events and trailing-space _chunk_text
- `tests/test_api/test_middleware.py` - ASGI-level tests for both middleware classes
- `tests/test_agent/test_agent.py` - TestChunkText and TestStreamingErrorEvent classes

## Decisions Made

- Used `MutableHeaders(scope=message)` from starlette.datastructures for header injection in pure ASGI
- SSE error event includes both `data` (machine-readable: type + message) and `message` (human-readable) fields
- No `done` event after `error` event per research recommendation -- frontend handles cleanup in `finally`
- Trailing-space pattern for _chunk_text: `["hello world ", "is great ", "today"]` instead of leading-space `[" is great", " today"]`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused Callable import in middleware.py**
- **Found during:** Post-task verification
- **Issue:** `from collections.abc import Callable` was imported but unused after rewrite
- **Fix:** Removed the unused import
- **Files modified:** src/pam/api/middleware.py
- **Verification:** All 10 middleware tests still pass
- **Committed in:** docs commit (trivial cleanup)

---

**Total deviations:** 1 auto-fixed (1 bug/lint)
**Impact on plan:** Trivial cleanup, no scope creep.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- SSE streaming now unbuffered and ready for frontend consumption
- Structured error events provide a consistent contract for frontend error handling
- Plans 03-02 and 03-03 can proceed with the hardened API/agent foundation

## Self-Check: PASSED

All files exist. All commit hashes verified.

---
*Phase: 03-api-agent-hardening*
*Completed: 2026-02-16*
