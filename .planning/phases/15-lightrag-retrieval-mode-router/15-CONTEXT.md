# Phase 15: Retrieval Mode Router - Context

**Gathered:** 2026-02-25
**Status:** Ready for planning

<domain>
## Phase Boundary

A query classifier routes each question to the optimal retrieval strategy. Entity-specific questions use graph-first retrieval, conceptual questions use relationship/traversal search, temporal questions use history tools, and simple factual questions skip the graph entirely. Following LightRAG's mode-based retrieval pattern adapted to PAM's tool ecosystem.

</domain>

<decisions>
## Implementation Decisions

### Classification approach
- Rule-based classifier as the primary layer — keyword patterns, entity name detection, temporal markers
- Entity detection matches against known entities in the graph/ES (not just heuristic patterns)
- LLM fallback using Haiku (fastest, cheapest) for queries the rule-based layer can't confidently classify
- When neither rules nor LLM are confident, default to hybrid mode (search everything) — never miss results

### Mode definitions
- All 5 modes implemented from the start: entity, conceptual, temporal, factual, hybrid
- **Entity mode**: shallow graph retrieval — single node lookup + immediate neighbors (1-hop)
- **Conceptual mode**: deep graph retrieval — multi-hop traversal, community structures, relationship patterns
- **Temporal mode**: triggered only by explicit time references — keywords like 'when', 'history', 'changed', 'before/after', 'last week'
- **Factual mode**: ES-only, skip graph entirely — triggered by direct definition/fact queries ("What is X?", "Define Y", "How many Z")
- **Hybrid mode**: all retrieval paths run — the default fallback for ambiguous queries

### Routing behavior
- Agent receives the classified mode as a hint and passes it to smart_search (not transparent)
- Optional `mode` parameter in the search/chat API — users can force a specific mode, skipping classification (for debugging and power users)
- Existing RRF scoring used as-is for multi-path merging — mode routing controls WHICH paths run, not how results merge

### Observability & tuning
- Mode + confidence score logged via structlog for every classification
- Mode included in API response metadata (`retrieval_mode`, `mode_confidence`) — visible to frontend and API consumers
- Config-driven rules — keyword lists, entity patterns, and confidence thresholds in config/env vars, tunable without code changes
- Per-mode performance metrics tracked: mode distribution, average latency per mode, fallback rates

### Claude's Discretion
- Hard skip vs soft skip strategy for skipped retrieval paths
- Exact confidence threshold values for hybrid fallback
- LLM classification prompt design
- Rule ordering and priority logic

</decisions>

<specifics>
## Specific Ideas

- Entity detection should query the actual graph/ES for known entity names rather than relying on capitalization heuristics
- Factual mode is the main latency win — focus optimization there since it skips graph entirely
- Config-driven tuning enables iterating on classification quality without redeployment

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 15-lightrag-retrieval-mode-router*
*Context gathered: 2026-02-25*
