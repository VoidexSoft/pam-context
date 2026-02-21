---
phase: 08-agent-graph-tool-rest-graph-endpoints
plan: 01
subsystem: agent
tags: [graphiti, neo4j, knowledge-graph, anthropic, tool-use, cypher]

# Dependency graph
requires:
  - phase: 06-neo4j-graphiti-infrastructure
    provides: GraphitiService, Neo4j connection, entity types
  - phase: 07-ingestion-pipeline-extension-diff-engine
    provides: Episode ingestion with source_description metadata
provides:
  - search_knowledge_graph agent tool for relationship queries
  - get_entity_history agent tool for temporal queries
  - Graph query module (src/pam/graph/query.py) with source citation extraction
  - Agent with 7 tools (5 existing + 2 graph)
affects: [08-02 REST graph endpoints, 09 graph explorer UI]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Graph tool results include source document citations from episode metadata"
    - "Optional graph_service via getattr for graceful degradation"
    - "Direct Cypher for temporal queries, Graphiti search() for semantic queries"

key-files:
  created:
    - src/pam/graph/query.py
  modified:
    - src/pam/agent/tools.py
    - src/pam/agent/agent.py
    - src/pam/api/deps.py

key-decisions:
  - "Use getattr for graph_service in deps.py (not Depends) for optional Neo4j"
  - "Source citations embedded in result text (not Citation objects) for graph tools"
  - "Direct Cypher for get_entity_history to avoid embedding overhead"
  - "re.escape on entity names in Cypher regex to prevent injection"

patterns-established:
  - "Graph query functions return formatted text strings with inline source citations"
  - "Agent tool handlers check self.graph_service is None before delegating"
  - "Episode source_description parsed via regex for document title extraction"

requirements-completed: [GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-06]

# Metrics
duration: 4min
completed: 2026-02-21
---

# Phase 8 Plan 01: Agent Graph Tools Summary

**Two knowledge graph tools (search_knowledge_graph + get_entity_history) added to Claude agent with Graphiti hybrid search, direct Cypher temporal queries, and source document citations from episode metadata**

## Performance

- **Duration:** 4 min
- **Started:** 2026-02-21T05:42:27Z
- **Completed:** 2026-02-21T05:46:24Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Graph query module with search_graph_relationships (Graphiti hybrid search) and get_entity_history (direct Cypher)
- Both query functions extract source document names from episode metadata for citation
- Agent now has 7 tools with clear descriptions differentiating graph tools from document search
- Graceful degradation when Neo4j is unavailable (None-safe graph_service, try/except on queries)

## Task Commits

Each task was committed atomically:

1. **Task 1: Create graph query module and add tool definitions** - `80bc33e` (feat)
2. **Task 2: Wire graph_service into agent and add tool dispatch handlers** - `c72d271` (feat)

## Files Created/Modified
- `src/pam/graph/query.py` - Graph query functions: search_graph_relationships and get_entity_history
- `src/pam/agent/tools.py` - Added SEARCH_KNOWLEDGE_GRAPH_TOOL and GET_ENTITY_HISTORY_TOOL definitions
- `src/pam/agent/agent.py` - Added graph_service param, SYSTEM_PROMPT with 7 tools, dispatch + handlers
- `src/pam/api/deps.py` - Passes graph_service to agent via getattr (optional)

## Decisions Made
- Used `getattr(request.app.state, "graph_service", None)` instead of `Depends(get_graph_service)` because graph_service is optional -- the agent must work without Neo4j
- Source document citations are embedded directly in the result text string (e.g., "[Source: doc_name]") rather than as Citation objects, because graph edges reference episodes not document chunks
- Used `re.escape()` on entity names in Cypher regex patterns to prevent Cypher injection
- Used direct Cypher for get_entity_history (avoids embedding overhead for known entity names) and Graphiti search() for search_graph_relationships (needs semantic hybrid search)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Agent graph tools are complete and ready for use
- Phase 8 Plan 02 (REST graph endpoints) can proceed independently
- All 4 modified files pass linting and import verification

## Self-Check: PASSED

All files exist and all commits verified.

---
*Phase: 08-agent-graph-tool-rest-graph-endpoints*
*Completed: 2026-02-21*
