---
phase: 15-lightrag-retrieval-mode-router
plan: 01
subsystem: agent
tags: [query-classification, retrieval-routing, llm-fallback, regex, elasticsearch]

# Dependency graph
requires:
  - phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool
    provides: "LLM call pattern via keyword_extractor.py and AsyncAnthropic"
  - phase: 13-lightrag-entity-and-relationship-vector-indices
    provides: "EntityRelationshipVDBStore with entity_index and client attributes"
provides:
  - "classify_query_mode() async function for two-tier query classification"
  - "RetrievalMode str enum with 5 modes (entity, conceptual, temporal, factual, hybrid)"
  - "ClassificationResult dataclass with mode, confidence, and method"
  - "Mode router config settings in Settings (threshold, keywords, LLM toggle)"
affects: [15-02-PLAN, smart_search, agent]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Two-tier classification cascade: rules -> entity ES lookup -> LLM fallback -> hybrid default"
    - "Configurable keyword lists as comma-separated env var strings parsed at runtime"
    - "Factual negative signal: entity mentions and conceptual keywords reduce factual confidence"

key-files:
  created:
    - src/pam/agent/query_classifier.py
    - tests/test_agent/test_query_classifier.py
  modified:
    - src/pam/common/config.py

key-decisions:
  - "Candidate entity names use original casing for ES keyword field terms query (not lowercased)"
  - "Factual negative signal checks multi-word caps and PascalCase but not single-word entities"
  - "LLM classification prompt uses inline format (not system message) for simplicity"
  - "Entity check is best-effort with try/except -- ES unavailability returns None gracefully"

patterns-established:
  - "Two-tier classification: fast rule-based primary + slow LLM fallback pattern"
  - "Comma-separated string config parsed to list at runtime for keyword configurability"

requirements-completed:
  - MODE-01

# Metrics
duration: 4min
completed: 2026-02-27
---

# Phase 15 Plan 01: Query Classifier Summary

**Two-tier query classifier with 5-mode RetrievalMode enum, rule-based heuristics, entity ES lookup, and Haiku LLM fallback**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-27T15:41:44Z
- **Completed:** 2026-02-27T15:45:24Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Created query_classifier.py with 4-step classification cascade (rules, entity ES, LLM, default)
- Rule-based layer handles temporal/factual/conceptual classification with configurable keyword lists
- Entity detection queries pam_entities ES index for known entity names via vdb_store
- LLM fallback uses Haiku with JSON output parsing, disabled via MODE_LLM_FALLBACK_ENABLED=false
- 32 comprehensive unit tests covering all classification tiers and edge cases

## Task Commits

Each task was committed atomically:

1. **Task 1: Add mode router config settings + create query_classifier.py module** - `381e4bc` (feat)
2. **Task 2: Add unit tests for query classifier** - `2eb66f6` (test)

## Files Created/Modified
- `src/pam/agent/query_classifier.py` - Two-tier query classifier with RetrievalMode enum, ClassificationResult, classify_query_mode()
- `src/pam/common/config.py` - Added mode router settings (threshold, temporal/factual/conceptual keywords, LLM toggle)
- `tests/test_agent/test_query_classifier.py` - 32 unit tests across 6 test classes

## Decisions Made
- Entity names use original casing for ES keyword field terms query (keyword fields store as-is, not analyzed)
- Factual negative signal checks only multi-word capitalized and PascalCase patterns (not single-word entities) to avoid over-triggering
- LLM classification uses inline prompt format following keyword_extractor.py pattern
- Entity check is best-effort: ES errors return None rather than failing classification

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- query_classifier.py is ready for integration into smart_search (Plan 02)
- RetrievalMode enum is importable and usable as the mode routing signal
- Config settings are in place for production tuning via env vars

## Self-Check: PASSED

All files exist. All commits verified.

---
*Phase: 15-lightrag-retrieval-mode-router*
*Completed: 2026-02-27*
