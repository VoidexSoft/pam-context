---
phase: 14-lightrag-graph-aware-context-assembly-with-token-budgets
plan: 01
subsystem: agent
tags: [tiktoken, token-budgeting, context-assembly, lightrag, markdown]

# Dependency graph
requires:
  - phase: 13-lightrag-entity-and-relationship-vector-indices
    provides: "Entity/relationship VDB store with kNN search and 4-way smart_search"
provides:
  - "4-stage context assembly pipeline (collect, truncate, dedup, build)"
  - "Token counting via tiktoken cl100k_base singleton"
  - "ContextBudget and AssembledContext dataclasses"
  - "Configurable token budgets via env vars (CONTEXT_ENTITY_BUDGET, CONTEXT_RELATIONSHIP_BUDGET, CONTEXT_MAX_TOKENS)"
affects: [14-02, smart-search-integration, agent-context-quality]

# Tech tracking
tech-stack:
  added: [tiktoken 0.12.0]
  patterns: [lazy-singleton-encoder, token-budgeted-truncation, budget-redistribution]

key-files:
  created:
    - src/pam/agent/context_assembly.py
    - tests/test_agent/test_context_assembly.py
  modified:
    - pyproject.toml
    - src/pam/common/config.py

key-decisions:
  - "500-token per-item truncation cap (truncate text, never drop items)"
  - "graph_text tokens counted toward relationship budget, appended as supplementary content"
  - "Chunk budget dynamically calculated with unused entity/relationship redistribution"
  - "Summary header only mentions non-empty categories to avoid mismatch with omitted sections"

patterns-established:
  - "Lazy tiktoken singleton: module-level _encoder with _get_encoder() factory"
  - "Token budget truncation: iterate sorted items, accumulate tokens, break at budget"
  - "Budget redistribution: unused category tokens flow to chunk budget"

requirements-completed: [CTX-01, CTX-02]

# Metrics
duration: 5min
completed: 2026-02-25
---

# Phase 14 Plan 01: Context Assembly Summary

**4-stage token-budgeted context assembly pipeline with tiktoken cl100k_base, configurable budgets (4000/6000/12000), and budget redistribution to maximize chunk context**

## Performance

- **Duration:** 5 min
- **Started:** 2026-02-24T18:47:01Z
- **Completed:** 2026-02-24T18:51:40Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Created standalone context_assembly.py module with 4-stage pipeline (collect, truncate, dedup, build)
- Added tiktoken>=0.12 for BPE token counting with lazy singleton encoder pattern
- Configurable token budgets via env vars with sensible defaults (entities 4000, relationships 6000, max 12000)
- Budget redistribution: unused entity/relationship tokens flow to chunk budget for maximum context utilization
- 23 unit tests with mocked tiktoken covering all pipeline stages, edge cases, and dataclass contracts

## Task Commits

Each task was committed atomically:

1. **Task 1: Create context_assembly.py module with 4-stage pipeline + tiktoken dependency + config settings** - `aabaeb1` (feat)
2. **Task 2: Add unit tests for context assembly pipeline** - `a6a6129` (test)

## Files Created/Modified
- `src/pam/agent/context_assembly.py` - 4-stage context assembly pipeline with token counting, truncation, dedup, and Markdown construction
- `tests/test_agent/test_context_assembly.py` - 23 unit tests across 6 test classes with mocked tiktoken
- `pyproject.toml` - Added tiktoken>=0.12 dependency
- `src/pam/common/config.py` - Added context_entity_budget, context_relationship_budget, context_max_tokens settings

## Decisions Made
- **500-token per-item cap:** Individual entity/relationship descriptions truncated at 500 tokens (not dropped), balancing detail vs budget consumption
- **graph_text handling:** Pre-formatted Graphiti text tokens counted toward relationship budget, appended as supplementary content after structured VDB relationships
- **Dynamic chunk budget:** base (max - entity_budget - relationship_budget) + unused from entities + unused from relationships, floored at 0
- **Summary header filtering:** Only mentions non-empty categories to avoid Pitfall 4 (mentioning omitted categories)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- context_assembly.py module ready for integration into _smart_search (Plan 14-02)
- assemble_context() accepts the same 4 result types that _smart_search already produces
- ContextBudget defaults match Settings fields for seamless config integration

---
*Phase: 14-lightrag-graph-aware-context-assembly-with-token-budgets*
*Completed: 2026-02-25*
