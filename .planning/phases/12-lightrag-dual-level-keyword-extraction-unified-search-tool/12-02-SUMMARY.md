---
phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool
plan: 02
subsystem: agent
tags: [lightrag, smart-search, asyncio, concurrent-search, agent-tools]

# Dependency graph
requires:
  - phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool
    plan: 01
    provides: "extract_query_keywords(), SMART_SEARCH_TOOL definition, config limits"
  - phase: 08-agent-graph-tool-rest-graph-endpoints
    provides: "search_graph_relationships(), get_entity_history() graph query functions"
provides:
  - "_smart_search() handler in RetrievalAgent with concurrent ES + graph search"
  - "smart_search dispatch in _execute_tool"
  - "Updated SYSTEM_PROMPT listing 8 tools equally"
  - "9 integration smoke tests for smart_search wiring"
affects: [13-lightrag-entity-and-relationship-vector-indices]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "asyncio.gather with return_exceptions=True for concurrent multi-backend search"
    - "Partial failure resilience: return working backend results with warning field"
    - "Content hash dedup (SHA-256) favoring ES results for citation richness"
    - "Dual-section output format: Document Results + Graph Results with extracted keywords"

key-files:
  created:
    - tests/test_agent/test_smart_search.py
  modified:
    - src/pam/agent/agent.py

key-decisions:
  - "Keyword extraction failure returns error message to agent (not silent fallback) per user decision"
  - "Empty keyword list falls back to original query to avoid empty result pitfall"
  - "Graph results included as-is from search_graph_relationships (already formatted with relationship structure)"
  - "Backfill is informational only (no re-query): if one source underperforms, the other's full results compensate"

patterns-established:
  - "asyncio.gather pattern for concurrent search backend execution with per-result exception checking"
  - "Dual-section result formatting (Document Results / Graph Results) for smart_search output"

requirements-completed:
  - SMART-01
  - SMART-03

# Metrics
duration: 5min
completed: 2026-02-24
---

# Phase 12 Plan 02: Smart Search Handler Summary

**_smart_search() handler with asyncio.gather concurrent ES + graph search, content hash dedup, and 9 integration smoke tests**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-24T08:06:08Z
- **Completed:** 2026-02-24T08:11:18Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments
- Implemented _smart_search() method on RetrievalAgent with full keyword extraction, concurrent ES + graph search via asyncio.gather, and structured dual-section output
- Updated SYSTEM_PROMPT to list all 8 tools equally with smart_search as first search tool (no preference language)
- Added 9 integration smoke tests covering tool definition, keyword extraction, system prompt, and config defaults
- Partial failure handling: if ES or graph backend fails, return results from working backend with warning

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement _smart_search handler with concurrent search and result merging** - `15f8e8d` (feat)
2. **Task 2: Add integration smoke test for smart_search tool** - `1594fb0` (test)

## Files Created/Modified
- `src/pam/agent/agent.py` - Added _smart_search() method with asyncio.gather concurrent search, smart_search dispatch in _execute_tool, updated SYSTEM_PROMPT with 8 tools
- `tests/test_agent/test_smart_search.py` - 9 tests across 5 classes: tool definition (3), keyword extraction success (1), keyword extraction failure (1), system prompt (3), config defaults (1)

## Decisions Made
- Keyword extraction failure returns error to agent with suggestion to use individual tools, per user decision (not silent fallback)
- When keyword lists are empty, fall back to original query string for that backend (avoids empty result pitfall from research)
- Graph results passed through as-is from search_graph_relationships (already includes relationship structure with source/target entities)
- Backfill is best-effort/informational: no re-query when one source underperforms; the other source's full results compensate
- graph_limit config setting loaded but reserved for future re-query backfill implementation

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- smart_search tool fully wired and operational with the agent
- Existing search_knowledge and search_knowledge_graph tools preserved as fallbacks
- Ready for Phase 13 (Entity & Relationship Vector Indices) which may enhance graph search quality
- All 8 agent tools registered and dispatched correctly

## Self-Check: PASSED

All files verified present. All commit hashes verified in git log.

---
*Phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool*
*Completed: 2026-02-24*
