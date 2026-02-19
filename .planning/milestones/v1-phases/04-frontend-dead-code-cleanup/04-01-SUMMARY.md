---
phase: 04-frontend-dead-code-cleanup
plan: 01
subsystem: ui
tags: [react, typescript, accessibility, polling, fetch-api]

# Dependency graph
requires:
  - phase: 03-api-agent-hardening
    provides: "Paginated API responses, streaming SSE chat"
provides:
  - "Stable React message keys via crypto.randomUUID()"
  - "Smart scroll (auto-follow at bottom, preserve on scroll-up)"
  - "useCallback-stabilized SourceViewer onClose preventing effect churn"
  - "Chained setTimeout polling with exponential backoff in useIngestionTask"
  - "Conditional Content-Type header (POST-only) in API client"
  - "aria-label attributes on chat UI interactive elements"
affects: [04-02-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns: [smart-scroll, chained-setTimeout-polling, conditional-headers, stable-react-keys]

key-files:
  created: []
  modified:
    - web/src/api/client.ts
    - web/src/api/client.test.ts
    - web/src/hooks/useChat.ts
    - web/src/hooks/useChat.test.ts
    - web/src/components/ChatInterface.tsx
    - web/src/pages/ChatPage.tsx
    - web/src/hooks/useIngestionTask.ts

key-decisions:
  - "crypto.randomUUID() for message IDs: browser-native, no dependency, UUID v4"
  - "50px threshold for isAtBottom detection: matches Slack/Discord scroll behavior"
  - "Exponential backoff 1.5s base / 30s max: balances responsiveness with server load"
  - "Conditional Content-Type only when body present: correct HTTP semantics for GET"

patterns-established:
  - "Smart scroll: useRef(isAtBottom) + onScroll handler + conditional scrollIntoView"
  - "Chained setTimeout: poll() schedules next call after completion, not overlapping"

requirements-completed: [FE-01, FE-02, FE-03, FE-07, FE-09]

# Metrics
duration: 3min
completed: 2026-02-18
---

# Phase 4 Plan 01: Frontend React Fixes Summary

**Stable message keys via crypto.randomUUID(), smart scroll, chained setTimeout polling with exponential backoff, conditional Content-Type headers, and aria-labels on chat UI**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-18T02:35:04Z
- **Completed:** 2026-02-18T02:38:37Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Chat messages use stable UUID keys instead of array indexes, preventing unnecessary React remounts
- Smart scroll auto-follows at bottom but preserves scroll position when user scrolls up (Slack/Discord pattern)
- SourceViewer onClose wrapped in useCallback, eliminating effect re-attachment on every parent render
- Ingestion polling replaced setInterval with chained setTimeout + exponential backoff on errors (1.5s to 30s)
- GET requests no longer send Content-Type: application/json header; POST requests with body still do
- Chat input, send, stop, and new-conversation buttons all have aria-label attributes

## Task Commits

Each task was committed atomically:

1. **Task 1: Stable message keys, smart scroll, useCallback onClose, aria-labels** - `c9d4d97` (feat)
2. **Task 2: Chained setTimeout polling with backoff, Content-Type fix** - `58694cb` (fix)

## Files Created/Modified
- `web/src/api/client.ts` - Added id field to ChatMessage; conditional Content-Type on request()
- `web/src/api/client.test.ts` - Added test for GET without Content-Type; updated existing test description
- `web/src/hooks/useChat.ts` - Assign crypto.randomUUID() to all new ChatMessage objects
- `web/src/hooks/useChat.test.ts` - Updated toEqual to toMatchObject + UUID format assertion
- `web/src/components/ChatInterface.tsx` - msg.id as key, smart scroll refs, aria-labels on input/buttons
- `web/src/pages/ChatPage.tsx` - useCallback-wrapped handleCloseViewer, aria-label on new conversation
- `web/src/hooks/useIngestionTask.ts` - Chained setTimeout, errorCountRef, exponential backoff

## Decisions Made
- Used crypto.randomUUID() for message IDs: browser-native, no dependency needed, UUID v4 guaranteed unique
- 50px threshold for bottom detection: same threshold used by Slack/Discord, balances precision with UX
- Exponential backoff with 1.5s base and 30s cap: keeps polling responsive while protecting server on errors
- Conditional Content-Type: only set when body is present, follows HTTP specification correctly

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Updated useChat.test.ts for new id field**
- **Found during:** Task 1 (Stable message keys)
- **Issue:** Existing test used toEqual which failed because new id field was not expected
- **Fix:** Changed toEqual to toMatchObject and added UUID format assertion
- **Files modified:** web/src/hooks/useChat.test.ts
- **Verification:** All 29 tests pass
- **Committed in:** c9d4d97 (Task 1 commit)

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** Test assertion update necessary due to our intentional schema change. No scope creep.

## Issues Encountered
None - all changes applied cleanly and tests pass.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All React rendering inefficiencies in chat and polling are resolved
- Ready for Plan 02 (dead code cleanup / additional frontend improvements)
- Pre-existing e2e test failures (Playwright in Vitest context) are out of scope

## Self-Check: PASSED

All 7 modified files verified present. Both task commits (c9d4d97, 58694cb) found in git log. SUMMARY.md exists.

---
*Phase: 04-frontend-dead-code-cleanup*
*Completed: 2026-02-18*
