# Pitfalls Research

**Domain:** Adding Neo4j + Graphiti knowledge graph, LLM-driven entity extraction, change detection, and graph visualization to an existing PG + ES RAG system
**Researched:** 2026-02-19
**Confidence:** HIGH (direct codebase analysis + verified against official Graphiti docs, Neo4j driver docs, Anthropic tool-use docs, and community post-mortems)

---

## Critical Pitfalls

### Pitfall 1: Using add_episode_bulk for Document Re-ingestion — Temporal Invalidation Is Silently Skipped

**What goes wrong:**
The Graphiti library has two ingestion paths: `add_episode()` (sequential, full validation) and `add_episode_bulk()` (batch, high throughput). `add_episode_bulk` explicitly skips edge invalidation and temporal contradiction detection. If you use the bulk path for document re-ingestion — which is tempting because it's faster — you get a graph with stale edges that were never invalidated. A document that changed its "Q3 revenue target" from $2M to $3M will have BOTH edges in the graph simultaneously, each with valid temporal metadata. Queries that don't filter on `t_invalid` will return contradictory facts.

**Why it happens:**
The bulk path is advertised for performance ("significantly outperforming add_episode for large datasets") and developers use it during initial ingestion. When documents are re-ingested on update, they reuse the same path. The temporal invalidation silently not happening is not obvious at the API call site — both methods have the same signature.

**How to avoid:**
Use `add_episode()` (sequential) for ALL document ingestion — both initial and re-ingestion. The bulk path is only appropriate for a one-time empty-graph bootstrap where you do not care about temporal consistency. Document this constraint in the ingestion pipeline's docstring. Route document updates through `add_episode()` unconditionally. If performance is a concern, control concurrency via `SEMAPHORE_LIMIT` environment variable rather than switching to bulk mode.

**Warning signs:**
- Graph queries return two contradictory values for the same fact at the same point in time
- `t_invalid` is null on edges that should have been superseded by newer ingestion
- Re-ingesting the same document twice results in doubled edges rather than temporal transitions

**Phase to address:**
Phase 1 (Neo4j + Graphiti Infrastructure) — bake the `add_episode()` requirement into the pipeline integration before writing any ingestion code.

---

### Pitfall 2: Neo4j Driver AsyncSession Is Not Concurrency-Safe — Sharing Across Coroutines Causes Undefined Behavior

**What goes wrong:**
The Neo4j Python driver's `AsyncSession` is explicitly documented as not safe for concurrent use across multiple coroutines. The existing codebase already uses SQLAlchemy's `AsyncSession` with per-request scoping (correctly initialized in deps.py). If the Neo4j driver is initialized once and sessions are shared across FastAPI request handlers — especially in a pattern mirroring the current SQLAlchemy singleton pattern — concurrent requests will corrupt each other's state. The symptoms are non-deterministic: race conditions that only appear under load, silent result corruption, or cryptic driver errors.

**Why it happens:**
SQLAlchemy async sessions can be scoped per-request through dependency injection and developers port that pattern directly. But Neo4j's session semantics are different: sessions are cheap to create/close, the driver itself (connection pool) is the expensive singleton. The `asyncio.wait_for()` and `asyncio.shield()` wrappers that FastAPI uses internally can wrap work in `asyncio.Task`, which introduces the concurrency that breaks `AsyncSession`.

**How to avoid:**
Initialize a single `AsyncGraphDatabase.driver()` instance during FastAPI lifespan startup and store it on `app.state.neo4j_driver`. Create a new session per request via dependency injection, just like the existing `get_db_session` pattern. Close the session in a `finally` block. Never pass an `AsyncSession` to a background task or store it in a shared variable. The driver (not the session) is the singleton.

```python
# Correct pattern
async def get_neo4j_session(request: Request):
    async with request.app.state.neo4j_driver.session() as session:
        yield session
```

**Warning signs:**
- Neo4j errors that only appear under concurrent load (not in tests)
- `asyncio.Task` in the call stack when session errors occur
- Non-deterministic failures that pass when run with `--workers 1`

**Phase to address:**
Phase 1 (Neo4j + Graphiti Infrastructure) — driver lifecycle must be established before any graph write code is written.

---

### Pitfall 3: Graphiti's LLM Extraction Cost Per Document Is Multiplicative — 5-10 LLM Calls Per Chunk

**What goes wrong:**
Every call to `add_episode()` triggers multiple LLM calls internally: entity extraction (`extract_nodes()`), edge extraction (`extract_edges()`), deduplication resolution for ambiguous matches, and temporal metadata extraction. The Zep paper documents a three-stage deduplication pipeline (fast hashing → MinHash → LLM resolution). For a document with 50 chunks, this can mean 150-300 LLM API calls during a single ingestion run. At Claude claude-sonnet-4-6 pricing, ingesting a 100-document corpus becomes expensive enough to notice on the bill. Re-ingestion on document change multiplies this again.

**Why it happens:**
Graphiti defaults to OpenAI but the system uses Anthropic (Claude). The cost math that Graphiti's examples show is OpenAI-priced. Claude claude-sonnet-4-6 is more expensive per token than GPT-4o-mini (which Graphiti examples commonly use). Developers don't model the total LLM call count before writing the integration.

**How to avoid:**
1. Profile the actual LLM call count on a sample document before building the integration (run with structured logging on the Graphiti client, count `LLM call` log entries per episode).
2. Use `SEMAPHORE_LIMIT` environment variable to control parallel LLM calls and avoid rate-limit errors (default is 10; lower this if hitting Claude's rate limits).
3. Consider using a cheaper model for extraction (e.g., Claude Haiku) and reserving claude-sonnet-4-6 for agent answering. Graphiti supports configurable LLM clients.
4. Implement extraction budgeting: only run graph extraction on documents that changed (content hash check in the existing pipeline already provides this — integrate the hash check before calling `add_episode()`).
5. Prompt caching via the Anthropic API reduces cost by 90% on cache hits for repeated system prompts.

**Warning signs:**
- Ingestion runs significantly slower after adding graph extraction
- Anthropic API cost spike after testing with a real document corpus
- Rate limit errors from the Anthropic API during bulk ingestion

**Phase to address:**
Phase 1 (Neo4j + Graphiti Infrastructure) — establish cost ceiling per document before wiring into ingestion pipeline. Phase 2 (Ingestion Integration) — validate actual costs on real corpus before full rollout.

---

### Pitfall 4: Entity Type Explosion from Schema-Free Extraction — Graph Becomes Unqueryable

**What goes wrong:**
LLM-driven "auto-discover" entity extraction with no predefined schema generates a different entity type vocabulary for every document. One document produces `Person`, another produces `Employee`, another `Staff Member`, another `Individual`. These are semantically equivalent but structurally distinct in the graph. Traversal queries that ask "find all people who approved this process" fail because they match only one entity type. The graph accumulates hundreds of label variants that are synonyms of a smaller canonical set.

**Why it happens:**
The LLM generates entity types based on the context of each document independently. Without a constraint list, it will name types using whatever phrasing is most natural for that document's content. Graphiti's Pydantic-based entity type system (custom entity types via subclassing `BaseNode`) mitigates this, but only if used — the default untyped extraction produces unconstrained labels.

**How to avoid:**
Define a bounded list of entity types before writing any extraction code. For PAM Context's business knowledge domain, this list is probably: `Organization`, `Person`, `Metric`, `Process`, `Product`, `System`, `Policy`, `Team`, `Project`. Use Graphiti's custom entity type API (subclass `BaseNode` with a `name` field and Pydantic validators) to pass this type list to the LLM as a constraint. The extraction prompt becomes "extract entities of ONLY these types, ignoring others." Enforce this in the `ExtractorConfig` passed to `Graphiti()`.

**Warning signs:**
- `MATCH (n) RETURN DISTINCT labels(n)` in Neo4j returns more than 15 distinct label types
- Entity type names have spaces or multiple words (e.g., `"Product Manager"` as a type rather than a label)
- Queries for person-related entities must enumerate 5+ label variants

**Phase to address:**
Phase 2 (Ingestion Integration) — define the entity type taxonomy BEFORE writing the extraction config. Do not iterate on it during integration.

---

### Pitfall 5: Document Re-ingestion Leaves Orphan Nodes in the Graph — Entities from Deleted Content Persist

**What goes wrong:**
When a document is re-ingested after a change, the existing system (PG + ES) handles this by deleting old segments and replacing them with new ones. The graph layer has no equivalent delete: `add_episode()` adds new nodes and temporally invalidates stale edges, but it does not delete nodes whose source document no longer contains the entity. A document that previously mentioned "Project Orion" but now no longer does will leave a `Project Orion` node in the graph with no active edges, permanently. Over many re-ingestion cycles, the graph accumulates orphan nodes that inflate entity counts and confuse deduplication.

**Why it happens:**
Graphiti's temporal model is non-lossy by design — it preserves history. This is correct for its primary use case (agent memory across conversations). For document knowledge bases, where a re-ingested document should replace the old one's extracted facts, the non-lossy design works against you unless you build explicit tombstoning logic.

**How to avoid:**
Before calling `add_episode()` for a re-ingested document, run a cleanup Cypher query that soft-deletes (sets `t_invalid = now()` on) all edges sourced from that document's prior episodes. Link each `add_episode()` call to a `source_document_id` in the episode metadata so you can filter by it. Store the document's UUID (from PG) in the episode's `group_id` or `metadata` field. This creates a document-scoped episode namespace that can be cleaned up on re-ingestion.

**Warning signs:**
- Node count grows monotonically even when re-ingesting the same documents repeatedly
- Entities appear in graph queries that no longer appear in any current document
- Deduplication LLM calls rise with each re-ingestion cycle because there are more candidates to resolve

**Phase to address:**
Phase 2 (Ingestion Integration) — design the episode-to-document linking scheme before first write, not as a retrofit.

---

### Pitfall 6: The query_graph Agent Tool Returns Raw Graph Data That Blows the Context Window

**What goes wrong:**
A graph query for "all entities related to the compliance process" can return hundreds of nodes and edges. If the `query_graph` tool serializes this result naively into the agent's context (e.g., as a JSON list of node/edge dicts), it consumes thousands of tokens in a single tool result. The existing agent has `MAX_TOOL_ITERATIONS = 5`. With 5 tools now instead of 5, and each tool result potentially consuming 2-5k tokens, the context fills before the agent reaches a synthesis step. Anthropic's tool-use research shows tool definitions alone can consume 134k tokens with many tools defined.

**Why it happens:**
Developers write the tool result formatter to be comprehensive ("return everything") rather than agent-friendly ("return the minimum needed to answer"). Graph data is especially verbose when serialized: each node has properties, labels, and relationship data. The existing tools (`search_knowledge`, `search_entities`) are already formatted to be concise — the graph tool inherits that discipline only if explicitly designed for it.

**How to avoid:**
1. Cap graph query results hard: return at most 20 nodes and 30 edges per tool call, with a note if results were truncated.
2. Format results as prose summaries, not raw JSON: "Found 3 entities related to Compliance Process: Risk Assessment (Process), SOC2 Framework (Policy), Jane Smith (Person, owner)."
3. Add a `depth` parameter to the tool input (default 1 hop) to prevent unbounded traversal.
4. The tool description should explicitly instruct the LLM to use targeted queries, not broad traversals.
5. Keep the `query_graph` tool description concise — tool definitions are paid tokens in every request.

**Warning signs:**
- Agent hits `MAX_TOOL_ITERATIONS` before providing an answer when graph queries are involved
- Tool result length exceeds 3000 characters for any single graph call
- The agent is calling `query_graph` repeatedly with slightly different queries (it's stuck trying to fit results into context)

**Phase to address:**
Phase 3 (Agent Tool Integration) — design the result formatter for the `query_graph` tool with explicit token budgets from day one.

---

### Pitfall 7: Adding query_graph Tool Changes Agent Routing Behavior for Existing Tools

**What goes wrong:**
The existing 5 tools are carefully balanced: `search_knowledge` is the workhorse, others handle specific cases. Adding `query_graph` as tool 6 does not just add capability — it changes how the LLM selects between all 6 tools on every request. Claude may now route questions that previously went to `search_entities` to `query_graph` instead (both can answer "what metrics does Team X own?"). If the graph data is incomplete (early phases), this routing shift produces worse answers than the old path. The problem is invisible without A/B testing.

**Why it happens:**
The tool-use router is the LLM itself, and it optimizes across the full tool list on every call. Adding a tool that superficially overlaps with existing tools degrades routing precision proportional to the overlap. The `search_entities` and `query_graph` tools both handle structured entity queries.

**How to avoid:**
1. Write the `query_graph` tool description to be clearly distinct: emphasize relationship traversal, not entity lookup. "Use when the question requires following connections between entities — e.g., 'who approved this process?' or 'what systems does this team own?'"
2. Update the `search_entities` description to de-emphasize relationship queries: "Use for direct entity attribute lookups — e.g., 'what is the formula for Metric X?'"
3. Add an explicit routing note to the system prompt: "Use query_graph only when the question requires traversal. For simple entity lookups, use search_entities."
4. Run regression tests on the existing question set from `eval/questions.json` after adding the tool, comparing answer quality.

**Warning signs:**
- `search_entities` call frequency drops to near-zero after adding `query_graph`
- Eval score on entity-specific questions degrades after tool addition
- Agent calls both `search_entities` and `query_graph` on the same question (tool overlap confusion)

**Phase to address:**
Phase 3 (Agent Tool Integration) — write and validate tool descriptions before wiring the tool into `ALL_TOOLS`. Run eval suite after every tool addition.

---

### Pitfall 8: Neo4j Memory Configuration Defaults Are Unsuitable for Coexistence with PG + ES

**What goes wrong:**
The current `docker-compose.yml` allocates 2GB heap to Elasticsearch (`-Xms2g -Xmx2g`). Adding Neo4j with default Docker image settings gives it only 512MB heap and 512MB page cache. With PG + ES + Redis + Neo4j all running on the same host (development), this creates memory pressure. Neo4j degrades silently under low memory: slower queries, increased GC pauses, and eventually OOM kills that corrupt the graph store. The default Neo4j Docker configuration is explicitly documented as "intended for learning, not production."

**Why it happens:**
Neo4j's Docker image defaults to conservative settings to allow co-location during development demos. These same defaults are copied into production-like docker-compose files without adjustment. The OOM failure is intermittent (depends on host memory and concurrent load), making it hard to diagnose.

**How to avoid:**
Add explicit memory configuration to the Neo4j docker-compose service. For a development environment with 16GB host RAM and existing PG + ES + Redis services, target: heap initial/max = 1GB, page cache = 512MB. For production (dedicated Neo4j), run `neo4j-admin server memory-recommendation --docker` to generate accurate settings. Do not share Neo4j's data volume with other services.

```yaml
neo4j:
  image: neo4j:5.26
  environment:
    NEO4J_AUTH: neo4j/password
    NEO4J_server_memory_heap_initial__size: 1g
    NEO4J_server_memory_heap_max__size: 1g
    NEO4J_server_memory_pagecache__size: 512m
```

**Warning signs:**
- Neo4j query latency increases over a test session even for small graphs
- `docker stats` shows Neo4j container memory at 80%+ of its limit
- Intermittent Neo4j connection errors that resolve after container restart

**Phase to address:**
Phase 1 (Neo4j + Graphiti Infrastructure) — configure memory in docker-compose before first data is written. Data written with wrong memory config may require graph rebuild after fixing.

---

### Pitfall 9: @neo4j-nvl/react Graph Renders Every Node on Every State Update — React Reconciliation Performance

**What goes wrong:**
`@neo4j-nvl/react` renders a canvas-based graph (WebGL). When the parent React component's state changes — e.g., the user sends a chat message and the conversation list re-renders — if the graph component is not properly memoized, NVL reinitializes the canvas on every parent re-render. This causes visible flicker, loss of user's pan/zoom position, and 100-300ms render freezes. The existing frontend already has the `key={i}` anti-pattern in `ChatInterface.tsx` (addressed in v1 cleanup); applying similar non-stable references to graph data props has the same failure mode.

**Why it happens:**
Canvas-based graph libraries reinitialize when their root React element is remounted. React remounts elements when keys change or when parent components replace them with new JSX nodes. If graph data is passed as `nodes={computedNodes}` where `computedNodes` is recomputed on every parent render (not memoized), NVL receives a new array reference on every render, triggering a full reinitialize.

**How to avoid:**
1. Wrap the graph component in `React.memo()` so it only re-renders when its props actually change.
2. Memoize the nodes and relationships arrays with `useMemo()`, using stable node IDs as dependency keys.
3. Place the graph component in a route that is not the parent of the chat interface — keep them as sibling routes, not nested.
4. Implement a stable `graphData` state object that is only replaced when graph content changes (not on every chat message).

**Warning signs:**
- Graph resets pan/zoom position when user types in the chat input
- React DevTools Profiler shows the graph component re-rendering on every keystroke
- Canvas flicker visible during conversation streaming

**Phase to address:**
Phase 4 (Graph Visualization) — architect the component hierarchy before adding NVL. The graph explorer should live on a dedicated route, not embedded in the chat view.

---

### Pitfall 10: Dual-Write Consistency Between PG/ES and Neo4j Without Transactions

**What goes wrong:**
The existing pipeline commits to PG first, then writes to ES — with ES as a recoverable secondary (if ES fails, re-ingestion catches up). Adding Neo4j as a third store with no distributed transaction support means all three can diverge. The common failure mode: PG commit succeeds, ES write succeeds, Neo4j `add_episode()` fails mid-extraction (LLM timeout). The document is in PG and ES but missing from the graph. The next ingestion (content hash unchanged) is skipped by the existing hash check, so the graph entry is permanently absent.

**Why it happens:**
The existing pipeline's "PG is authoritative, ES is recoverable" pattern works because ES writes are idempotent — rerun the ingest and ES catches up. Graphiti's `add_episode()` is not cleanly idempotent: re-running it creates new temporal episodes rather than being a no-op for unchanged content. There is no equivalent of "check if this document's graph is current" before calling `add_episode()`.

**How to avoid:**
1. Add a `graph_synced` boolean flag (or `graph_synced_at` timestamp) to the `documents` PG table. Set it to `False` on every ingest, set to `True` only after `add_episode()` succeeds.
2. Build a reconciliation job (`/ingest/sync-graph` endpoint or a scheduled task) that finds documents where `graph_synced = False` and retries the graph extraction.
3. The content hash check in the pipeline must be paired with a `graph_synced` check: skip PG/ES re-write if hash unchanged AND `graph_synced = True`.
4. Log `pipeline_graph_write_failed` separately from PG/ES failures so the reconciliation job can identify targets.

**Warning signs:**
- Graph entity count is lower than document count would predict (some documents have no graph representation)
- Re-ingesting a document with unchanged content does not appear to add graph nodes (skipped by hash check before graph write)
- `graph_synced` flag never gets set to True for documents that failed during LLM extraction

**Phase to address:**
Phase 2 (Ingestion Integration) — the `graph_synced` flag pattern must be in place before any production ingestion.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Using `add_episode_bulk` for initial ingestion then `add_episode` for updates | Faster initial graph build | Temporal consistency gap: initial graph has no invalidation baseline, so first update creates spurious "contradictions" | Only if the initial graph is a true bootstrap of an empty system with no subsequent updates expected — in practice, never |
| Storing Neo4j connection string in plain env var alongside PG/ES/Redis | Consistent with existing config pattern | No credential rotation path; all four store credentials in same `.env` file — one compromise exposes all | Acceptable in development; production should use a secrets manager |
| Querying Neo4j directly from FastAPI route handlers without a service layer | Fewer files to create | Cypher queries scattered across handler files; no testable abstraction; impossible to swap graph backends | Never — create a `GraphService` abstraction from day one, even if thin |
| Skipping entity type constraints ("let the LLM decide") | Faster to prototype | Entity type explosion (see Pitfall 4); graph becomes unqueryable within 20 documents | Prototype only, never in integration |
| Embedding graph node IDs from Neo4j directly in API responses | Avoids mapping layer | Neo4j internal IDs are not stable across database rebuilds; clients cache stale IDs | Never — always expose stable UUIDs (PAM's own document/segment IDs) |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Graphiti + Anthropic | Graphiti defaults to OpenAI; developers set `OPENAI_API_KEY` and miss that `LLMClient` must be explicitly overridden to use Claude | Pass `LLMClient` and `EmbedderClient` instances to `Graphiti()` constructor explicitly; do not rely on env var auto-detection |
| Neo4j driver + FastAPI lifespan | Creating driver in module scope (like old `deps.py` singleton pattern) instead of in `lifespan` | Use `@asynccontextmanager` lifespan, create driver on startup, close on shutdown, store on `app.state` |
| Graphiti episodes + PAM documents | Graphiti's `group_id` is for session/conversation grouping; developers overload it as document ID | Use `group_id` for document ID scoping AND store document metadata in episode `source` field for independent querying |
| Neo4j + ES vector search | Both support vector similarity search; developers route all vector queries to Neo4j after adding it | Keep semantic/hybrid search in ES (it's already optimized); use Neo4j only for graph traversal; never replace ES with Neo4j for embedding search |
| `@neo4j-nvl/react` + Vite | NVL uses canvas/WebGL; some Vite configurations have issues with canvas-heavy libraries in SSR or test environments | Add NVL to Vite's `optimizeDeps.exclude` or `ssr.noExternal` as needed; never import NVL in server-side code or test files |
| PG document_id + Neo4j node identity | Developers use Neo4j's internal numeric element IDs as foreign keys back to PG | Store PAM's UUID (`document_id`, `segment_id`) as properties on Neo4j nodes; use these as the join key, never the Neo4j internal ID |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Graphiti `add_episode()` called synchronously in the ingestion request handler | HTTP request times out (3-5 min per document) because LLM extraction blocks the response | Run graph extraction as a background task after PG/ES commit; update `graph_synced` flag when done | Immediately on any document > 5 chunks |
| Unbounded Cypher graph traversal in `query_graph` tool | Tool result is thousands of nodes, blows context window, agent loops | Hard-cap LIMIT clauses in all Cypher queries; add traversal depth parameter (default 1 hop, max 3) | On any graph with more than 50 nodes |
| No index on Neo4j node properties used in entity lookup | Full graph scan on every `MATCH (n {name: $name})` query | Add Neo4j property indexes during schema setup: `CREATE INDEX entity_name FOR (n:Entity) ON (n.name)` | At 500+ nodes |
| Re-querying Neo4j on every chat message to populate graph explorer | Graph explorer flickers and re-loads on every message send | Cache graph data in React state; only refresh on explicit user action or on new ingestion completion | Immediately — N+1 API calls pattern |
| Sequential `add_episode()` with default `SEMAPHORE_LIMIT=10` against Claude API | Rate limit errors during bulk ingestion | Lower `SEMAPHORE_LIMIT` to 3-5 for Claude; use Anthropic Batch API for initial corpus ingestion | At 20+ documents ingested simultaneously |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Passing raw user query strings as Cypher query parameters without validation | Cypher injection (analogous to SQL injection); attacker can traverse or modify graph | Never construct Cypher from user input; the `query_graph` tool should generate Cypher from structured parameters, not freeform strings |
| Exposing Neo4j Bolt port (7687) in docker-compose without authentication | Direct graph database access from any container on the Docker network | Always set `NEO4J_AUTH` in docker-compose; never expose port 7687 to the host interface in production |
| Storing extracted entities that include PII (names, emails from documents) in Neo4j without access control | Graph query tool returns PII to any authenticated user | Audit extracted entity types before production deployment; redact PII fields from entity extraction prompts; restrict `query_graph` tool results to non-PII properties |
| Returning full Graphiti episode content in API responses | Internal document structure, chunk content, and LLM-generated intermediate data exposed | Graph API endpoints should return only node metadata (type, name, relationships), never episode content |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Graph explorer shows all nodes at once for a large corpus | Canvas is unreadable; 500+ nodes overlapping | Default to ego-graph view (selected entity + 1 hop); paginate or cluster beyond 50 nodes |
| Graph not populated during initial ingestion (graph extraction is async/background) | User sees empty graph immediately after ingesting documents | Show "Graph indexing in progress" state with progress; disable graph explorer tab until `graph_synced` count > 0 |
| Change detection diff shown as raw JSON | Users can't parse `{"added": [...], "removed": [...], "modified": [...]}` | Render diffs as readable prose: "3 new entities added, 1 relationship changed: Q3 Revenue Target updated from $2M to $3M" |
| query_graph tool failure returns empty agent answer | User sees "I couldn't find that information" when the graph is simply not populated yet | Distinguish "graph empty" from "entity not found"; show "Graph index still building" if graph has < 10 nodes |

---

## "Looks Done But Isn't" Checklist

- [ ] **Graphiti integration:** Often missing entity type constraints — verify `labels(n)` returns fewer than 15 distinct types after ingesting 10+ documents
- [ ] **Document re-ingestion:** Often leaves orphan nodes — verify node count does not grow when re-ingesting the same document with minor changes 3+ times
- [ ] **Neo4j driver lifecycle:** Often initialized at module scope — verify driver is created in lifespan handler and stored on `app.state`, not as a global
- [ ] **graph_synced flag:** Often the reconciliation path is missing — verify documents with failed graph extraction are retried on next ingestion run, not silently skipped
- [ ] **query_graph tool result size:** Often unbounded — verify that querying a 200-node graph returns fewer than 3000 characters of tool result text
- [ ] **Graph explorer memoization:** Often causes full canvas reinit — verify with React DevTools Profiler that NVL component does not re-render on chat message send
- [ ] **Tool routing regression:** Often degrades existing tool accuracy — verify eval/questions.json scores are not lower after adding query_graph to ALL_TOOLS
- [ ] **Neo4j property indexes:** Often not created — verify `SHOW INDEXES` in Neo4j returns at least entity name and document_id indexes before first query
- [ ] **Cypher injection guard:** Often overlooked — verify `query_graph` tool never passes freeform user strings directly into a Cypher string (use parameterized queries only)

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Bulk ingestion path used, temporal edges are wrong | HIGH | Drop and rebuild graph from scratch using `add_episode()` sequential path; this means a full re-ingestion of all documents |
| Entity type explosion (200+ label types) | HIGH | Clear all nodes/edges, redefine entity type list, re-ingest all documents with constrained extraction |
| Orphan nodes accumulated over many re-ingestions | MEDIUM | Write a Cypher cleanup query: `MATCH (n) WHERE NOT (n)--() DELETE n`; run graph reconciliation job; add orphan prevention to pipeline |
| Neo4j session concurrency corruption | MEDIUM | Restart Neo4j container to clear corrupted in-flight transactions; fix session scoping in deps.py; verify with concurrent load test before re-deploying |
| graph_synced gap (documents missing from graph) | LOW | Run reconciliation endpoint against all documents where `graph_synced = False`; monitor completion |
| query_graph tool context overflow | LOW | Add hard LIMIT clause to all Cypher queries in tool implementation; update tool description; no data loss |
| NVL graph explorer reinit on every render | LOW | Add `React.memo()` and `useMemo()` wrappers; no data loss; purely a frontend fix |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| bulk vs sequential ingestion (Pitfall 1) | Phase 1: Infrastructure + Phase 2: Ingestion | Re-ingest same doc twice; verify edges have `t_invalid` set on superseded relationships |
| Neo4j AsyncSession concurrency (Pitfall 2) | Phase 1: Infrastructure | Load test with 10 concurrent requests; no driver errors; session created/closed per request |
| LLM extraction cost per document (Pitfall 3) | Phase 1: Infrastructure + Phase 2: Ingestion | Count LLM calls per document in CI smoke test; set budget alert on Anthropic API |
| Entity type explosion (Pitfall 4) | Phase 2: Ingestion | After ingesting 20 docs, `MATCH (n) RETURN DISTINCT labels(n)` returns <= 15 labels |
| Orphan nodes on re-ingestion (Pitfall 5) | Phase 2: Ingestion | Re-ingest modified doc 3 times; node count for that document's entities does not grow |
| query_graph context window bloat (Pitfall 6) | Phase 3: Agent Tool | Tool result for any query is <= 3000 chars; MAX_TOOL_ITERATIONS not hit on graph questions |
| query_graph routing shift (Pitfall 7) | Phase 3: Agent Tool | Eval score on `eval/questions.json` matches or exceeds pre-graph-tool baseline |
| Neo4j memory under co-location (Pitfall 8) | Phase 1: Infrastructure | `docker stats` shows all containers stable under 5-minute load test |
| NVL render performance (Pitfall 9) | Phase 4: Visualization | React Profiler shows NVL not re-rendering during chat interaction |
| Dual-write consistency (Pitfall 10) | Phase 2: Ingestion | Simulate Neo4j failure mid-ingestion; verify `graph_synced=False` document is retried; verify content hash check does not skip it |

---

## Sources

- Graphiti official documentation — `add_episode_bulk` warning: "Use only for populating empty graphs or when edge invalidation is not required" (HIGH confidence, fetched 2026-02-19)
- Zep temporal knowledge graph architecture paper (arXiv:2501.13956) — bi-temporal model (t_valid, t_invalid, t_created, t_expired) (HIGH confidence)
- Neo4j Python Driver documentation — "AsyncSession is not concurrency-safe; must not span multiple asyncio Tasks" (HIGH confidence)
- Neo4j driver best practices — "Create one driver instance per DBMS; sessions are cheap, create and close freely" (HIGH confidence)
- Graphiti GitHub issues #871 (Invalid JSON errors in bulk ingestion), #879 (ValidationError in bulk upload), #223 (KeyError in bulk ingest) — documented instability in bulk path (MEDIUM confidence)
- Neo4j Operations Manual — Docker memory defaults (512MB heap/pagecache), explicit note that defaults are "for learning, not production" (HIGH confidence)
- Anthropic tool-use engineering blog — tool definitions consuming 55K-134K tokens in large tool sets (HIGH confidence)
- GDELT Project entity extraction experiments — "LLM extractors are massively more brittle than traditional extractors; single apostrophe changes results" (MEDIUM confidence — WebSearch verified)
- Knowledge graph update challenges — Stanford CS520 notes on evolution, orphan nodes, and schema versioning (MEDIUM confidence)
- Direct codebase analysis of `src/pam/agent/agent.py`, `src/pam/agent/tools.py`, `src/pam/ingestion/pipeline.py`, `src/pam/common/models.py`, `docker-compose.yml`, `web/package.json` (HIGH confidence — direct code evidence)

---
*Pitfalls research for: PAM Context — Knowledge Graph + Temporal Reasoning milestone*
*Researched: 2026-02-19*
