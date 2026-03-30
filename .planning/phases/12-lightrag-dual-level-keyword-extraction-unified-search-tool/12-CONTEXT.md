# Phase 12: Dual-Level Keyword Extraction + Unified Search Tool - Context

**Gathered:** 2026-02-24
**Status:** Ready for planning

<domain>
## Phase Boundary

A single `smart_search` agent tool that generates entity-level and theme-level keywords from a query, runs ES hybrid search and graph relationship search in parallel, and returns merged results. Replaces 2-3 tool calls with 1 for relationship-aware questions, following LightRAG's dual-level retrieval pattern. Existing `search_knowledge` and `search_knowledge_graph` tools remain as fallbacks.

</domain>

<decisions>
## Implementation Decisions

### Keyword classification
- Always extract both high-level and low-level keywords regardless of query ambiguity — ensures both ES and graph backends always contribute
- Prompt design, classification criteria (theme vs entity), and keyword count per level are Claude's discretion — follow LightRAG patterns adapted for PAM

### Result format & source attribution
- Return two separate sections: `document_results` and `graph_results` arrays (not a single merged list)
- Graph results must include relationship structure: source entity, target entity, relationship type, plus text content
- Response must include the extracted `high_level_keywords` and `low_level_keywords` alongside results — transparency for the agent and useful for debugging/eval
- Whether individual results carry a source tag is Claude's discretion

### Result limits & balance
- Default 10 total results: 5 from ES, 5 from graph
- Limits configurable via env vars (SMART_SEARCH_ES_LIMIT, SMART_SEARCH_GRAPH_LIMIT)
- Backfill enabled: if one source returns fewer than its quota, the other source fills the gap up to total limit
- Deduplication by content hash favors the ES version (carries document citations and chunk context needed for the agent's citation workflow)

### Fallback & error behavior
- If keyword extraction LLM call fails: return error to agent (agent can retry or fall back to individual search tools)
- If one search backend fails (e.g. Neo4j down): return partial results from the working backend, with a warning field indicating which backend failed
- Agent routing: describe all three tools (smart_search, search_knowledge, search_knowledge_graph) equally — let the agent decide per-query which to use, no forced preference in system prompt
- Keyword extraction timeout: generous 10-15 seconds (allows for cold starts / API congestion)

### Claude's Discretion
- Keyword extraction prompt wording and few-shot examples
- Whether to pass the original query as an implicit low-level keyword to ES
- Exact keyword count caps (fixed vs variable)
- Loading/progress behavior for concurrent searches
- Error message formatting

</decisions>

<specifics>
## Specific Ideas

- LightRAG's `extract_keywords_only()` and `_perform_kg_search()` as primary reference for the dual-path pattern
- ~50 token extraction call as specified in roadmap — keep it lightweight
- Round-robin interleaving for the internal merge step (before splitting into sections), with dedup by content hash

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 12-lightrag-dual-level-keyword-extraction-unified-search-tool*
*Context gathered: 2026-02-24*
