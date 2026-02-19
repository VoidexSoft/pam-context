---
phase: 05-audit-gap-closure
plan: 02
subsystem: ui
tags: [react, typescript, sse, chat, metrics, tailwind]

requires:
  - phase: 04-frontend-dead-code-cleanup
    provides: Frontend chat UI with streaming, stable message keys, useChat hook
provides:
  - Aligned ChatResponse and StreamEvent interfaces with backend contract
  - Metrics display (token_usage, latency_ms) on assistant messages
  - Clean client.ts with no dead functions
affects: []

tech-stack:
  added: []
  patterns:
    - Native HTML details/summary for expandable UI sections (no JS state)

key-files:
  created: []
  modified:
    - web/src/api/client.ts
    - web/src/hooks/useChat.ts
    - web/src/hooks/useChat.test.ts
    - web/src/api/client.test.ts
    - web/src/components/MessageBubble.tsx

key-decisions:
  - "ChatResponse aligned to backend shape: {response, citations, conversation_id, token_usage, latency_ms}"
  - "conversation_id moved to top-level StreamEvent field per backend SSE done event structure"
  - "Native <details>/<summary> for metrics display -- no React state, built-in accessibility"
  - "ChatResponse import removed from useChat.ts -- type inferred from apiSendMessage return"

patterns-established:
  - "Native HTML details/summary for collapsible sections in message bubbles"

requirements-completed: [TOOL-02, AGNT-04]

duration: 3min
completed: 2026-02-18
---

# Phase 05 Plan 02: Frontend API Alignment and Metrics Display Summary

**Removed dead client functions, aligned ChatResponse/StreamEvent with backend, wired metrics through streaming and fallback paths, added expandable token usage display**

## Performance

- **Duration:** 3 min
- **Started:** 2026-02-18T16:09:01Z
- **Completed:** 2026-02-18T16:11:57Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Deleted unused `getAuthStatus()` and `listTasks()` from client.ts (dead code removal)
- Aligned ChatResponse interface with backend: `{response, citations, conversation_id, token_usage, latency_ms}`
- Fixed non-streaming fallback to read `res.response` instead of `res.message` and map citation fields
- Fixed SSE done handler to read `event.conversation_id` (top-level) and attach metrics to last assistant message
- Added expandable metrics details section to MessageBubble with native `<details>/<summary>`

## Task Commits

Each task was committed atomically:

1. **Task 1: Remove dead functions, align interfaces, fix useChat** - `6114523` (fix)
2. **Task 2: Add expandable metrics details to MessageBubble** - `136dd06` (feat)

## Files Created/Modified
- `web/src/api/client.ts` - Removed dead functions, aligned ChatResponse/StreamEvent/ChatMessage interfaces
- `web/src/hooks/useChat.ts` - Fixed SSE done handler (top-level conversation_id, metrics attachment), fixed non-streaming fallback
- `web/src/hooks/useChat.test.ts` - Updated fallback mock to match new ChatResponse shape
- `web/src/api/client.test.ts` - Updated sendMessage mock to match new ChatResponse shape
- `web/src/components/MessageBubble.tsx` - Added expandable metrics details section

## Decisions Made
- ChatResponse aligned to backend shape: `{response, citations, conversation_id, token_usage, latency_ms}` -- backend is source of truth
- `conversation_id` moved to top-level StreamEvent field (out of metadata) per backend SSE done event structure
- Native `<details>/<summary>` for metrics display -- no React state, built-in accessibility, hidden by default
- Removed explicit `ChatResponse` import from useChat.ts since TypeScript infers it from `apiSendMessage` return type

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Removed unused ChatResponse import from useChat.ts**
- **Found during:** Task 2 (TypeScript compilation check)
- **Issue:** Plan instructed to add ChatResponse import, but TypeScript flagged TS6133 (declared but never read) since the type is inferred from apiSendMessage return
- **Fix:** Removed the explicit import; type inference handles it
- **Files modified:** web/src/hooks/useChat.ts
- **Verification:** `npx tsc --noEmit` passes clean
- **Committed in:** 136dd06 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Trivial fix -- import was unnecessary due to TypeScript inference. No scope creep.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- All frontend audit gaps from Phase 05 research are now closed
- Chat interface correctly handles both streaming and non-streaming response shapes
- Metrics are visible to users via expandable details section
- All frontend unit tests pass (29/29)

## Self-Check: PASSED

All files verified present. Both commit hashes confirmed in git log.

---
*Phase: 05-audit-gap-closure*
*Completed: 2026-02-18*
