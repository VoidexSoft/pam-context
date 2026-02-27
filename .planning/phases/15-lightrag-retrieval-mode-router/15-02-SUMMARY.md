---
phase: 15-lightrag-retrieval-mode-router
plan: 02
subsystem: agent
tags: [retrieval-routing, mode-conditioned-search, noop-coroutine, structlog, sse-metadata]

# Dependency graph
requires:
  - phase: 15-lightrag-retrieval-mode-router
    plan: 01
    provides: "classify_query_mode() with RetrievalMode enum and ClassificationResult"
  - phase: 14-lightrag-graph-aware-context-assembly-with-token-budgets
    provides: "assemble_context with token budgets for structured output"
  - phase: 13-lightrag-entity-and-relationship-vector-indices
    provides: "EntityRelationshipVDBStore for VDB searches"
provides:
  - "Mode-conditioned smart_search that skips irrelevant retrieval paths via noop coroutines"
  - "SMART_SEARCH_TOOL with optional 'mode' parameter for forced retrieval mode"
  - "AgentResponse with retrieval_mode and mode_confidence metadata fields"
  - "ChatResponse with retrieval_mode and mode_confidence for API consumers"
  - "SSE streaming done event with mode metadata"
  - "structlog observability for every mode classification"
affects: [frontend-metrics-display, api-consumers, evaluation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Noop coroutine pattern for hard-skip in asyncio.gather (zero compute for skipped paths)"
    - "Mode-conditioned coroutine assignment before gather for clean branching"
    - "Instance state _last_classification for metadata propagation across method boundaries"

key-files:
  created:
    - tests/test_agent/test_mode_routing.py
  modified:
    - src/pam/agent/tools.py
    - src/pam/agent/agent.py
    - src/pam/api/routes/chat.py

key-decisions:
  - "Noop coroutines defined as local functions inside _smart_search to keep scope contained"
  - "MagicMock name= kwarg sets repr not attribute; used SimpleNamespace for tool_use block mocks"
  - "Mode metadata propagated via self._last_classification instance state (safe: agents are per-request)"
  - "All 3 AgentResponse return paths in answer() include mode fields for consistency"

patterns-established:
  - "Noop coroutine pattern: async def _noop_list() -> list: return [] for hard skip in gather"
  - "SimpleNamespace for tool_use content block mocks (avoids MagicMock name= pitfall)"

requirements-completed:
  - MODE-02
  - MODE-03

# Metrics
duration: 8min
completed: 2026-02-27
---

# Phase 15 Plan 02: Mode-Conditioned Smart Search Summary

**Mode-conditioned smart_search with noop coroutine hard skips, SMART_SEARCH_TOOL mode parameter, AgentResponse/ChatResponse/SSE metadata, and 12 integration tests**

## Performance

- **Duration:** 8 min
- **Started:** 2026-02-27T15:48:23Z
- **Completed:** 2026-02-27T15:56:02Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Wired classify_query_mode into _smart_search with mode-conditioned coroutine selection and noop hard skips
- Added optional 'mode' parameter to SMART_SEARCH_TOOL for agent-forced retrieval mode override
- Extended AgentResponse, ChatResponse, and SSE done event with retrieval_mode and mode_confidence metadata
- Added structlog observability logging for every mode classification decision
- Created 12 integration tests across 3 test classes covering all modes, metadata propagation, and logging

## Task Commits

Each task was committed atomically:

1. **Task 1: Wire mode classifier + extend AgentResponse/ChatResponse + observability** - `2dfd504` (feat)
2. **Task 2: Add integration tests for mode-based routing** - `a6f57e3` (test)

## Files Created/Modified
- `src/pam/agent/tools.py` - Added optional 'mode' parameter (5 enum values) to SMART_SEARCH_TOOL input_schema
- `src/pam/agent/agent.py` - Integrated classify_query_mode, added mode-conditioned search with noop coroutines, extended AgentResponse, propagated metadata to answer()/answer_streaming()
- `src/pam/api/routes/chat.py` - Added retrieval_mode and mode_confidence fields to ChatResponse, propagated from AgentResponse in chat() endpoint
- `tests/test_agent/test_mode_routing.py` - 12 integration tests: TestModeRouting (7), TestModeMetadataPropagation (4), TestModeLogging (1)

## Decisions Made
- Noop coroutines (`_noop_list`, `_noop_str`) defined as local functions inside `_smart_search()` to keep scope contained (not module-level)
- Used `SimpleNamespace` for tool_use content block mocks in tests because `MagicMock(name=...)` sets the mock's repr name, not an attribute (discovered during test debugging)
- Mode metadata propagated via `self._last_classification` instance state, safe because agents are instantiated per-request
- All 3 AgentResponse return paths in `answer()` include retrieval_mode/mode_confidence for consistency

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed tool_use block mock using SimpleNamespace**
- **Found during:** Task 2 (test_streaming_done_event_has_mode_metadata)
- **Issue:** `MagicMock(name="smart_search")` sets the mock's repr name, not a `.name` attribute. The streaming test's tool dispatch never matched "smart_search", so `_smart_search` was never called and `_last_classification` stayed None.
- **Fix:** Created `_tool_use_block()` helper using `SimpleNamespace(type="tool_use", id=..., name=..., input=...)` for correct attribute access.
- **Files modified:** tests/test_agent/test_mode_routing.py
- **Verification:** All 12 tests pass including streaming metadata test.
- **Committed in:** a6f57e3 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** Test mock pattern fix; no scope creep.

## Issues Encountered
None beyond the mock attribute issue documented above.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 15 (LightRAG Retrieval Mode Router) is now complete
- v3.0 milestone (LightRAG-Inspired Smart Retrieval) is fully implemented
- Mode classification + routing is live: factual queries skip 3 of 4 paths, entity queries skip 2
- All 58 tests pass (12 new + 46 existing backward-compatible)

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 15-lightrag-retrieval-mode-router*
*Completed: 2026-02-27*
