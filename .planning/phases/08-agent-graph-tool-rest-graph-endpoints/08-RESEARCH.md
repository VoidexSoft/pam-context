# Phase 8: Agent Graph Tool + REST Graph Endpoints - Research

**Researched:** 2026-02-21
**Domain:** Graph querying via Graphiti SDK + FastAPI REST endpoints + Anthropic tool-use agent integration
**Confidence:** HIGH

## Summary

Phase 8 adds two new agent tools (`search_knowledge_graph` and `get_entity_history`) and two REST endpoints (`GET /api/graph/neighborhood/{entity}` and `GET /api/graph/entities`) that expose the Neo4j knowledge graph built in phases 6-7. The implementation is straightforward because all required building blocks already exist:

1. **Graphiti's `search()` and `search_()` methods** provide hybrid search (BM25 + cosine similarity) over edges and nodes with configurable reranking. The `SearchFilters` class already supports temporal filtering via `valid_at`, `invalid_at`, and `created_at` date filters with comparison operators -- this directly enables point-in-time queries (GRAPH-03).

2. **The existing agent architecture** (simple tool-use loop in `agent.py`, tool definitions in `tools.py`) follows a clear pattern: define a tool dict, add it to `ALL_TOOLS`, implement `_execute_tool` dispatch, and write the handler method. The agent is instantiated per-request, so adding a `graph_service` dependency is clean.

3. **Direct Cypher queries via `graph_service.client.driver.session()`** are already used in the graph status endpoint (`graph.py`), providing the pattern for neighborhood traversal and entity listing without going through Graphiti's search API.

**Primary recommendation:** Use Graphiti's `search()` for the `search_knowledge_graph` tool (relationship queries), use direct Cypher with temporal WHERE clauses for the `get_entity_history` tool (temporal edge history), and use direct Cypher for both REST endpoints (neighborhood + entity listing). Cap tool results at 3000 chars / 20 nodes as a post-processing truncation step.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Response format is Claude's discretion -- agent picks the best format (prose, list, structured) based on query type and result size
- Always cite source documents -- every graph answer includes which document(s) the entities/relationships were extracted from
- Two separate tools: `search_knowledge_graph` for relationship queries and `get_entity_history` for temporal queries
- Multi-tool answers supported -- agent can call both document search and graph tools in one turn, weaving results together
- Natural language date parsing -- agent interprets "last month", "since January", "in Q3" and converts to timestamps before calling the tool
- Point-in-time queries show snapshot + diff -- show the as-of state AND highlight what has changed between then and now
- Long temporal history gets summary + drill-down -- agent summarizes the change pattern ("modified 20 times, mostly ownership changes") then offers detail on request
- No-history entities stated plainly -- "AuthService was first seen on [date] and hasn't changed since. Here's its current state."
- Overflow handling: summarize + offer drill-down -- "Found 45 related entities. Showing top 20 by relevance. Ask me to narrow by type or relationship."
- REST pagination: cursor-based -- opaque cursor tokens for stable pagination
- Neighborhood endpoint: fixed 1-hop depth -- no configurable depth parameter
- Entities listing: supports type filtering -- optional `?type=Service` query param to narrow results
- Neo4j down: explain and fall back to document search -- "Graph database is currently unavailable. Let me search the documents instead."
- Empty graph: guide toward ingestion -- "The knowledge graph is empty. Ingest documents first to build the graph."
- Entity not found: auto-fallback to document search -- "Entity not found in graph. Searching documents..."
- REST error format: match existing PAM API error response patterns for consistency

### Claude's Discretion
- Exact response formatting (prose vs list vs table) per query type
- Tool result JSON schema design
- Cursor implementation strategy for REST pagination
- Ranking/ordering of overflow results ("top 20 by relevance")

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| GRAPH-01 | `search_knowledge_graph` agent tool for relationship queries ("what depends on X?") | Use Graphiti `search()` with `EDGE_HYBRID_SEARCH_RRF` config for edge-based relationship queries; format edges as fact statements with source/target nodes |
| GRAPH-02 | `get_entity_history` agent tool for temporal queries ("how has X changed since Y?") | Use direct Cypher query filtering `RELATES_TO` edges by `valid_at`/`invalid_at` timestamps; `SearchFilters` date filter pattern available for Graphiti search alternative |
| GRAPH-03 | Point-in-time graph query via `reference_time` parameter | `SearchFilters.valid_at` and `SearchFilters.invalid_at` with `ComparisonOperator` support `<=` and `IS NULL` for as-of queries; Cypher `WHERE e.valid_at <= $ref AND (e.invalid_at IS NULL OR e.invalid_at > $ref)` |
| GRAPH-04 | REST endpoint `GET /api/graph/neighborhood/{entity}` returning 1-hop subgraph | Direct Cypher: `MATCH (n:Entity)-[e:RELATES_TO]-(m:Entity) WHERE n.name = $name` with LIMIT; returns nodes + edges JSON |
| GRAPH-05 | REST endpoint `GET /api/graph/entities` listing all entity nodes | Direct Cypher: `MATCH (n:Entity) RETURN labels(n), n.name, n.uuid, n.summary` with optional label filter and cursor pagination |
| GRAPH-06 | Tool result size hard-capped at 3000 chars with <=20 nodes per response | Post-processing truncation: slice results to 20 items, then `json.dumps()` and truncate at 3000 chars with overflow summary |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| graphiti-core[anthropic] | >=0.27 (installed) | Graph search, node/edge retrieval | Already used for extraction in Phase 7; `search()` and `search_()` are the official query API |
| neo4j (driver) | via graphiti-core | Direct Cypher queries for neighborhood/entity listing | Already available via `graph_service.client.driver`; used in `graph.py` status endpoint |
| FastAPI | existing | REST endpoints | Already in use for all API routes |
| anthropic | existing | Agent tool-use loop | Already in `agent.py` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pydantic | existing | Request/response schemas for REST endpoints | Define `NeighborhoodResponse`, `EntityListResponse` models |
| structlog | existing | Logging for tool execution | Consistent with all other modules |
| base64 | stdlib | Cursor encoding for pagination | Encode/decode opaque cursor tokens |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Graphiti `search()` for GRAPH-01 | Direct Cypher queries | Graphiti search gives hybrid BM25+vector with reranking; direct Cypher is simpler but loses semantic matching |
| Direct Cypher for GRAPH-02 | Graphiti `search_()` with `SearchFilters.valid_at` | Cypher gives precise control over temporal WHERE clauses; Graphiti search adds unnecessary embedding overhead for history queries |
| base64 cursor for pagination | UUID-based cursor | base64 is more opaque (hides implementation); UUID cursor is simpler but exposes internal IDs |

## Architecture Patterns

### Recommended Project Structure
```
src/pam/
├── agent/
│   ├── agent.py          # Add graph_service param, new _execute_tool dispatch
│   └── tools.py           # Add SEARCH_KNOWLEDGE_GRAPH_TOOL, GET_ENTITY_HISTORY_TOOL
├── graph/
│   ├── service.py         # Existing GraphitiService (unchanged)
│   ├── query.py           # NEW: Graph query functions (search, history, neighborhood, entities)
│   └── entity_types.py    # Existing entity taxonomy (unchanged)
├── api/
│   ├── deps.py            # Update get_agent() to inject graph_service
│   └── routes/
│       └── graph.py       # Add neighborhood and entities endpoints
```

### Pattern 1: Agent Tool Addition
**What:** Add new tools to the existing agent following the established pattern.
**When to use:** Any new tool the agent needs.
**Example:**
```python
# In tools.py - define the tool schema
SEARCH_KNOWLEDGE_GRAPH_TOOL = {
    "name": "search_knowledge_graph",
    "description": "Search the knowledge graph for entity relationships...",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "..."},
            "entity_name": {"type": "string", "description": "..."},
            "relationship_type": {"type": "string", "description": "..."},
        },
        "required": ["query"],
    },
}

# In agent.py - add dispatch and handler
async def _execute_tool(self, tool_name, tool_input):
    ...
    if tool_name == "search_knowledge_graph":
        return await self._search_knowledge_graph(tool_input)
    if tool_name == "get_entity_history":
        return await self._get_entity_history(tool_input)
    ...
```

### Pattern 2: GraphitiService Search for Relationship Queries
**What:** Use Graphiti's built-in `search()` method for semantic relationship queries.
**When to use:** When the query is natural-language ("what depends on AuthService?") and needs hybrid search.
**Example:**
```python
# Graphiti search returns EntityEdge objects
from graphiti_core.search.search_config_recipes import EDGE_HYBRID_SEARCH_RRF

edges = await graph_service.client.search(
    query="dependencies of AuthService",
    num_results=20,
)
# Each edge has: .fact, .name, .source_node_uuid, .target_node_uuid, .valid_at, .invalid_at
```

### Pattern 3: Direct Cypher for Temporal History
**What:** Use `graph_service.client.driver.session()` for precise temporal queries.
**When to use:** When you need explicit control over temporal WHERE clauses.
**Example:**
```python
async with graph_service.client.driver.session() as session:
    result = await session.run(
        """
        MATCH (n:Entity {name: $name})-[e:RELATES_TO]-(m:Entity)
        WHERE e.valid_at <= $ref_time
        AND (e.invalid_at IS NULL OR e.invalid_at > $ref_time)
        RETURN e.fact AS fact, e.name AS rel_type,
               m.name AS related_entity, labels(m) AS labels,
               e.valid_at AS valid_at, e.invalid_at AS invalid_at
        ORDER BY e.valid_at DESC
        LIMIT $limit
        """,
        name=entity_name,
        ref_time=reference_time,
        limit=20,
    )
    records = await result.data()
```

### Pattern 4: Cursor-Based Pagination for REST
**What:** Use opaque base64-encoded cursors for stable pagination.
**When to use:** REST endpoints returning paginated lists.
**Example:**
```python
import base64
import json

def encode_cursor(uuid: str) -> str:
    return base64.urlsafe_b64encode(json.dumps({"uuid": uuid}).encode()).decode()

def decode_cursor(cursor: str) -> str:
    data = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return data["uuid"]

# In Cypher: ORDER BY n.uuid DESC, then WHERE n.uuid < $cursor_uuid
```

### Anti-Patterns to Avoid
- **Embedding graph queries into Cypher strings with f-strings:** Always use parameterized queries (`$name`, `$limit`) to prevent Cypher injection.
- **Returning raw Graphiti model objects to the agent:** EntityEdge/EntityNode objects are huge (contain embeddings). Always map to a minimal dict before returning as tool result text.
- **Using `add_episode_bulk()` for any query operations:** Bulk is for ingestion only; queries use `search()` or direct Cypher.
- **Sharing `graph_service` across concurrent agent calls without consideration:** GraphitiService is a singleton, but `driver.session()` creates new sessions, so concurrent reads are safe.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Semantic graph search | Custom Cypher full-text + vector queries | `graph_service.client.search()` | Graphiti already combines BM25 + cosine similarity with RRF reranking |
| Temporal date filtering | Custom date parsing/comparison logic | `SearchFilters` with `DateFilter` and `ComparisonOperator` | Already handles all comparison operators including IS NULL |
| Entity node data model | Custom node data classes | `EntityNode` from graphiti-core | Has `name`, `labels`, `summary`, `attributes`, `uuid`, `group_id` |
| Edge data model with temporal fields | Custom edge model | `EntityEdge` from graphiti-core | Has `fact`, `name`, `valid_at`, `invalid_at`, `expired_at`, `episodes` |
| Neo4j driver session management | Custom connection pooling | `graph_service.client.driver.session()` | Already managed by Neo4j async driver |

**Key insight:** Graphiti's data models (`EntityNode`, `EntityEdge`) and search infrastructure are comprehensive. The main custom work is: (1) mapping results to agent-friendly text, (2) writing 2-3 Cypher queries for neighborhood/entity listing/temporal history, and (3) wiring everything into the existing agent + API patterns.

## Common Pitfalls

### Pitfall 1: Tool Result Size Explosion
**What goes wrong:** Graph queries can return huge result sets. An entity with 50 relationships produces a tool result that consumes most of the agent's context window.
**Why it happens:** No result limiting in the Cypher query or post-processing.
**How to avoid:** Always LIMIT in Cypher (max 20 nodes/edges), then cap the serialized text at 3000 characters. If truncated, append a summary like "Showing 20 of 45 relationships. Ask to narrow by type."
**Warning signs:** Agent responses become slow or hit `max_tokens`; tool results exceed 5000 characters.

### Pitfall 2: Neo4j Down Crashes Agent
**What goes wrong:** If Neo4j is unavailable, the graph tool call raises an exception that breaks the tool-use loop.
**Why it happens:** No try/except around graph operations inside the agent tool handler.
**How to avoid:** Wrap every graph tool call in try/except. On failure, return a graceful message: "Graph database is currently unavailable. Let me search the documents instead." The agent will naturally fall back to `search_knowledge`.
**Warning signs:** Agent returns 500 errors when Neo4j container is down.

### Pitfall 3: Embedding Overhead in History Queries
**What goes wrong:** Using Graphiti's `search()` for temporal history queries triggers embedding generation for the query text, adding 200-500ms latency for a query that doesn't need semantic matching.
**Why it happens:** Graphiti `search()` always generates embeddings when cosine similarity is in the config.
**How to avoid:** Use direct Cypher queries for `get_entity_history` where the entity name is known and you're filtering by temporal predicates, not doing semantic search.
**Warning signs:** History tool calls take >1 second when the entity name is already known.

### Pitfall 4: Tool Schema Bloat Reduces Agent Routing Accuracy
**What goes wrong:** Adding too many tools or tools with vague descriptions causes the LLM to pick the wrong tool or call tools unnecessarily.
**Why it happens:** Current agent has 5 tools; adding 2 more (7 total) increases routing complexity.
**How to avoid:** Write precise, non-overlapping tool descriptions. `search_knowledge_graph` should clearly state "for entity RELATIONSHIPS" and `get_entity_history` should clearly state "for TEMPORAL CHANGES". Test with the existing eval questions to ensure no regression.
**Warning signs:** Existing eval questions start triggering graph tools instead of `search_knowledge`.

### Pitfall 5: EntityNode Labels Include "Entity" Base Label
**What goes wrong:** When returning node types, including the base "Entity" label alongside the specific label (e.g., "Technology") confuses users.
**Why it happens:** Graphiti adds `Entity` as a base label to all entity nodes. The `get_entity_node_from_record` function includes all labels.
**How to avoid:** Filter out "Entity" from labels when returning to users: `[l for l in node.labels if l != "Entity"]`. This pattern is already used in `extraction.py`.
**Warning signs:** API responses show `labels: ["Entity", "Technology"]` instead of `labels: ["Technology"]`.

### Pitfall 6: Edge Attributes Contain Embeddings
**What goes wrong:** Serializing EntityEdge objects includes `fact_embedding` (1536-dim float array), making tool results enormous.
**Why it happens:** EntityEdge model includes `fact_embedding` field by default.
**How to avoid:** When building tool result text, explicitly select only the fields needed: `fact`, `name`, `source_node_uuid`, `target_node_uuid`, `valid_at`, `invalid_at`. Never serialize the full Pydantic model.
**Warning signs:** Tool result text is thousands of characters for a single edge.

## Code Examples

### Example 1: search_knowledge_graph Tool Handler
```python
async def _search_knowledge_graph(self, input_: dict) -> tuple[str, list[Citation]]:
    """Execute the search_knowledge_graph tool."""
    if self.graph_service is None:
        return "Knowledge graph is not available.", []

    query = input_["query"]
    entity_name = input_.get("entity_name")
    relationship_type = input_.get("relationship_type")

    try:
        edges = await self.graph_service.client.search(
            query=query,
            num_results=20,
        )
    except Exception:
        return "Graph database is currently unavailable. Try search_knowledge instead.", []

    if not edges:
        if entity_name:
            return f"No relationships found for '{entity_name}' in the knowledge graph.", []
        return "No relevant relationships found in the knowledge graph.", []

    # Format results, capping at 20 edges and 3000 chars
    parts = []
    for edge in edges[:20]:
        parts.append(
            f"- {edge.fact} (relationship: {edge.name}, "
            f"valid: {edge.valid_at}, invalidated: {edge.invalid_at or 'current'})"
        )

    result_text = f"Found {len(edges)} relationships:\n" + "\n".join(parts)
    if len(result_text) > 3000:
        result_text = result_text[:2900] + f"\n\n... truncated. {len(edges)} total relationships found."

    return result_text, []  # No document citations from graph queries
```

### Example 2: get_entity_history Tool Handler
```python
async def _get_entity_history(self, input_: dict) -> tuple[str, list[Citation]]:
    """Execute the get_entity_history tool for temporal queries."""
    if self.graph_service is None:
        return "Knowledge graph is not available.", []

    entity_name = input_["entity_name"]
    since = input_.get("since")  # ISO datetime string, parsed by agent from natural language
    reference_time = input_.get("reference_time")  # Optional point-in-time

    try:
        async with self.graph_service.client.driver.session() as session:
            # Query all edges (current and invalidated) for this entity
            result = await session.run(
                """
                MATCH (n:Entity)-[e:RELATES_TO]-(m:Entity)
                WHERE n.name =~ $name_pattern
                AND ($since IS NULL OR e.created_at >= $since)
                RETURN e.fact AS fact, e.name AS rel_type,
                       m.name AS related, labels(m) AS labels,
                       e.valid_at AS valid_at, e.invalid_at AS invalid_at,
                       e.created_at AS created_at
                ORDER BY e.created_at DESC
                LIMIT 20
                """,
                name_pattern=f"(?i){entity_name}",
                since=since,
            )
            records = await result.data()
    except Exception:
        return "Graph database is currently unavailable.", []

    if not records:
        return f"No history found for entity '{entity_name}'.", []

    # Format temporal history
    parts = []
    for r in records:
        status = "current" if r["invalid_at"] is None else f"superseded {r['invalid_at']}"
        parts.append(f"- [{r['created_at']}] {r['fact']} ({status})")

    result_text = f"History for '{entity_name}' ({len(records)} changes):\n" + "\n".join(parts)
    if len(result_text) > 3000:
        result_text = result_text[:2900] + f"\n\n... truncated. {len(records)} total changes."

    return result_text, []
```

### Example 3: Neighborhood REST Endpoint
```python
@router.get("/graph/neighborhood/{entity_name}")
async def graph_neighborhood(
    entity_name: str,
    graph_service: GraphitiService = Depends(get_graph_service),
):
    """Return 1-hop subgraph for a named entity."""
    try:
        async with graph_service.client.driver.session() as session:
            result = await session.run(
                """
                MATCH (n:Entity)
                WHERE n.name =~ $name_pattern
                WITH n LIMIT 1
                OPTIONAL MATCH (n)-[e:RELATES_TO]-(m:Entity)
                WHERE e.invalid_at IS NULL
                RETURN n, collect(DISTINCT e) AS edges, collect(DISTINCT m) AS neighbors
                """,
                name_pattern=f"(?i){entity_name}",
            )
            record = await result.single()

        if not record or record["n"] is None:
            raise HTTPException(status_code=404, detail=f"Entity '{entity_name}' not found")

        # Build response with nodes and edges
        ...
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail="Graph database unavailable")
```

### Example 4: Entity Listing with Cursor Pagination
```python
@router.get("/graph/entities")
async def graph_entities(
    type: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
    graph_service: GraphitiService = Depends(get_graph_service),
):
    """List all entity nodes with optional type filter and cursor pagination."""
    cursor_uuid = decode_cursor(cursor) if cursor else None

    async with graph_service.client.driver.session() as session:
        cypher = "MATCH (n:Entity) "
        params = {"limit": limit + 1}  # +1 to detect next page

        where_parts = []
        if type:
            cypher += f"WHERE n:{type} "
        if cursor_uuid:
            where_parts.append("n.uuid < $cursor_uuid")
            params["cursor_uuid"] = cursor_uuid

        if where_parts:
            cypher += ("AND " if type else "WHERE ") + " AND ".join(where_parts) + " "

        cypher += "RETURN labels(n) AS labels, n.name AS name, n.uuid AS uuid, n.summary AS summary "
        cypher += "ORDER BY n.uuid DESC LIMIT $limit"

        result = await session.run(cypher, **params)
        records = await result.data()

    # Build response with next_cursor if more results
    has_next = len(records) > limit
    items = records[:limit]
    next_cursor = encode_cursor(items[-1]["uuid"]) if has_next and items else None

    return {
        "entities": [...],
        "next_cursor": next_cursor,
        "total_hint": None,  # Don't COUNT(*) for performance
    }
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Graphiti `_search()` (underscore prefix) | `search_()` (trailing underscore) | Graphiti 0.27+ | `_search()` is deprecated, redirects to `search_()` |
| SearchConfig with just edge/node | SearchConfig with edge/node/episode/community | Graphiti 0.27+ | All four search layers available simultaneously |
| No SearchFilters temporal support | `valid_at`, `invalid_at`, `created_at`, `expired_at` DateFilter | Graphiti 0.27+ | Full bi-temporal query support in search API |

**Deprecated/outdated:**
- `graphiti.client._search()`: Deprecated in favor of `search_()`. Still works but emits deprecation notice.

## Open Questions

1. **Case-insensitive entity name matching in Cypher**
   - What we know: Cypher regex `=~ "(?i)name"` works for case-insensitive matching. Graphiti stores entity names as-is from extraction.
   - What's unclear: Whether fulltext index search (which Graphiti sets up) is case-insensitive by default.
   - Recommendation: Use `=~ "(?i)..."` regex for direct Cypher queries; Graphiti `search()` handles this internally.

2. **Source document citation from graph edges**
   - What we know: Graphiti edges have an `episodes` field (list of episode UUIDs). Episodes have `source_description` containing "Document: X | Source: Y | Chunk: Z" (set during extraction in `extraction.py`).
   - What's unclear: Whether retrieving episode info for source citation adds meaningful latency.
   - Recommendation: For the agent tool, include source_description from the episode if available (1 extra query). For REST endpoints, skip it (return nodes/edges only).

3. **Eval regression testing scope**
   - What we know: 10 eval questions in `questions.json`, all about document search. Adding graph tools should not affect document-search questions.
   - What's unclear: Whether adding 2 new tools to ALL_TOOLS causes the LLM to route existing document questions through graph tools.
   - Recommendation: Run eval before and after adding tools. If any question regresses, adjust tool descriptions to be more specific about when to use each tool.

## Sources

### Primary (HIGH confidence)
- **graphiti-core source code (installed)** - `graphiti.py` (search/search_ methods), `search/search.py` (search implementation), `search/search_config.py` (SearchConfig, SearchFilters), `nodes.py` (EntityNode model), `edges.py` (EntityEdge model with temporal fields)
- **PAM codebase** - `agent.py` (existing tool-use loop), `tools.py` (tool definitions), `deps.py` (dependency injection), `graph.py` (existing graph status endpoint), `extraction.py` (extraction patterns and metadata)

### Secondary (MEDIUM confidence)
- **Graphiti SearchFilters** - `search_filters.py` (DateFilter, ComparisonOperator, edge/node filter constructors) -- verified by reading source
- **Neo4j Cypher temporal patterns** -- based on `valid_at`/`invalid_at` fields present on EntityEdge model, confirmed in `edges.py`

### Tertiary (LOW confidence)
- None -- all findings verified from installed source code

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries already installed and in use; no new dependencies needed
- Architecture: HIGH -- following exact patterns established in phases 1-7; no architectural changes
- Pitfalls: HIGH -- identified from direct source code analysis of Graphiti models and existing agent code
- Temporal queries: HIGH -- verified SearchFilters DateFilter support and EntityEdge temporal fields from installed graphiti-core source

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (stable -- all components already in project)
