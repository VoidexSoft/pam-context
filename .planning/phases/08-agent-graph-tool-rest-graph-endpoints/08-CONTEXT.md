# Phase 8: Agent Graph Tool + REST Graph Endpoints - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Expose the Neo4j knowledge graph through two channels: agent tools (for natural language relationship and temporal queries) and REST endpoints (for the upcoming Graph Explorer UI). Users ask the Claude agent graph questions and get answers with source citations; REST APIs serve structured graph data with pagination. Creating the Graph Explorer UI is Phase 9.

</domain>

<decisions>
## Implementation Decisions

### Agent tool responses
- Response format is Claude's discretion — agent picks the best format (prose, list, structured) based on query type and result size
- Always cite source documents — every graph answer includes which document(s) the entities/relationships were extracted from
- Two separate tools: `search_knowledge_graph` for relationship queries and `get_entity_history` for temporal queries
- Multi-tool answers supported — agent can call both document search and graph tools in one turn, weaving results together

### Temporal query behavior
- Natural language date parsing — agent interprets "last month", "since January", "in Q3" and converts to timestamps before calling the tool
- Point-in-time queries show snapshot + diff — show the as-of state AND highlight what has changed between then and now
- Long temporal history gets summary + drill-down — agent summarizes the change pattern ("modified 20 times, mostly ownership changes") then offers detail on request
- No-history entities stated plainly — "AuthService was first seen on [date] and hasn't changed since. Here's its current state."

### Result limits and overflow
- Overflow handling: summarize + offer drill-down — "Found 45 related entities. Showing top 20 by relevance. Ask me to narrow by type or relationship."
- REST pagination: cursor-based — opaque cursor tokens for stable pagination
- Neighborhood endpoint: fixed 1-hop depth — no configurable depth parameter
- Entities listing: supports type filtering — optional `?type=Service` query param to narrow results

### Error and empty states
- Neo4j down: explain and fall back to document search — "Graph database is currently unavailable. Let me search the documents instead."
- Empty graph: guide toward ingestion — "The knowledge graph is empty. Ingest documents first to build the graph."
- Entity not found: auto-fallback to document search — "Entity not found in graph. Searching documents..."
- REST error format: match existing PAM API error response patterns for consistency

### Claude's Discretion
- Exact response formatting (prose vs list vs table) per query type
- Tool result JSON schema design
- Cursor implementation strategy for REST pagination
- Ranking/ordering of overflow results ("top 20 by relevance")

</decisions>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 08-agent-graph-tool-rest-graph-endpoints*
*Context gathered: 2026-02-21*
