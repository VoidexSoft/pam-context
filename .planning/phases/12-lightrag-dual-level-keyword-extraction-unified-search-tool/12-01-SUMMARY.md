---
phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool
plan: 01
subsystem: agent
tags: [lightrag, keyword-extraction, anthropic, haiku, smart-search, tools]

# Dependency graph
requires:
  - phase: 08-agent-graph-tool-rest-graph-endpoints
    provides: "agent tool definitions (tools.py, ALL_TOOLS list)"
provides:
  - "extract_query_keywords() async function for dual-level keyword extraction"
  - "QueryKeywords dataclass with high_level_keywords and low_level_keywords"
  - "KEYWORD_EXTRACTION_PROMPT with 3 LightRAG-adapted few-shot examples"
  - "SMART_SEARCH_TOOL definition in ALL_TOOLS (8 total tools)"
  - "smart_search_es_limit and smart_search_graph_limit config settings"
affects: [12-02-PLAN]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Dual-level keyword extraction via lightweight Claude Haiku call (~50 output tokens)"
    - "Dataclass for structured LLM output parsing with .get() empty-list defaults"

key-files:
  created:
    - src/pam/agent/keyword_extractor.py
  modified:
    - src/pam/common/config.py
    - src/pam/agent/tools.py

key-decisions:
  - "Hardcoded claude-3-5-haiku-20241022 as default extraction model (configurable via function param, not env var)"
  - "Re-raise on extraction failure (per user decision: return error to agent, not silent fallback)"
  - "15s timeout for keyword extraction (generous for cold starts/API congestion)"

patterns-established:
  - "LightRAG-inspired dual-level keyword extraction: high_level (themes) + low_level (entities)"
  - "Structured JSON output from Claude with try/except parse and re-raise pattern"

requirements-completed:
  - SMART-02

# Metrics
duration: 2min
completed: 2026-02-24
---

# Phase 12 Plan 01: Keyword Extraction + Tool Definition Summary

**LightRAG-inspired dual-level keyword extractor with 3 few-shot examples, config limits, and SMART_SEARCH_TOOL definition (8 agent tools)**

## Performance

- **Duration:** 2 min
- **Started:** 2026-02-24T08:01:08Z
- **Completed:** 2026-02-24T08:03:12Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created keyword_extractor.py with extract_query_keywords() that calls Claude Haiku to classify queries into high-level (theme) and low-level (entity) keywords
- Added SMART_SEARCH_ES_LIMIT and SMART_SEARCH_GRAPH_LIMIT config settings (default 5 each)
- Defined SMART_SEARCH_TOOL with concise description and query input schema, bringing agent from 7 to 8 tools

## Task Commits

Each task was committed atomically:

1. **Task 1: Create keyword extraction module and add config settings** - `ed45809` (feat)
2. **Task 2: Add SMART_SEARCH_TOOL definition to tools.py** - `7f3949d` (feat)

## Files Created/Modified
- `src/pam/agent/keyword_extractor.py` - Dual-level keyword extraction module with QueryKeywords dataclass, KEYWORD_EXTRACTION_PROMPT (3 few-shot examples), and extract_query_keywords() async function
- `src/pam/common/config.py` - Added smart_search_es_limit and smart_search_graph_limit Settings fields
- `src/pam/agent/tools.py` - Added SMART_SEARCH_TOOL definition and appended to ALL_TOOLS list

## Decisions Made
- Hardcoded Haiku model ID as default parameter (not env var) -- simple enough to change via function arg; env var adds complexity for a classification task model that rarely changes
- Re-raise all extraction failures (json parse, key error, general exceptions) per user decision to return error to agent rather than silent fallback
- 15s timeout for keyword extraction per context guidance (generous for cold starts)
- Tool description kept concise per user decision (equal treatment of all search tools, no forced preference)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- keyword_extractor.py ready for import by Plan 02's _smart_search() handler in agent.py
- SMART_SEARCH_TOOL in ALL_TOOLS ready for tool dispatch wiring in Plan 02
- Config settings ready for use in concurrent search limit logic in Plan 02

## Self-Check: PASSED

All files verified present. All commit hashes verified in git log.

---
*Phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool*
*Completed: 2026-02-24*
