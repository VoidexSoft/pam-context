# Feature Research: Knowledge Graph & Temporal Reasoning Milestone

**Domain:** Knowledge graph layer for a business document RAG system (GraphRAG)
**Researched:** 2026-02-19
**Confidence:** HIGH (Graphiti/NVL via official docs + verified web sources)

---

## Context: What Already Exists

The following is already built and out of scope for this milestone:

- Hybrid search (BM25 + kNN + RRF) with reranking
- Claude agent with tools: `search_knowledge`, `get_document_context`, `get_change_history`, `query_database`, `search_entities`
- Basic entity extraction into `extracted_entities` PG table (types: `metric_definition`, `event_tracking_spec`, `kpi_target`)
- React chat interface, document management, citation tooltips
- SyncLog table tracking document-level ingestion events

The new milestone adds a **graph layer** on top: Neo4j/Graphiti for relationships and temporal reasoning, plus a visual explorer.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that must exist for the knowledge graph milestone to feel complete. Missing any of these makes the feature feel half-baked.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Entity node creation in Neo4j on ingest** | A "knowledge graph" that only stores in PG is not a knowledge graph. Every new ingestion run must populate the graph. | MEDIUM | Graphiti's `add_episode()` API handles this. Each document chunk becomes an episode. Must wire into existing ingestion pipeline (`pipeline.py`). |
| **Relationship edge extraction between entities** | Entities without relationships are just a list. The graph value comes from edges: "Metric X is defined in Doc Y", "KPI A depends on Metric B". | HIGH | Requires LLM call per episode (Graphiti handles this). Entity types need expansion beyond current 3 types. Relationship schema must be designed upfront. |
| **Graph-aware agent tool: `search_graph`** | Users asking "how is X related to Y?" or "what entities are connected to Z?" need a graph traversal path — not just keyword search. Without this tool, the graph is invisible to the agent. | MEDIUM | Wraps Graphiti's hybrid `search()` API (semantic + BM25 + graph traversal). Returns edges+nodes. Claude must be instructed when to prefer this over `search_knowledge`. |
| **Bi-temporal metadata on all graph edges** | Any claim about temporal reasoning without actual timestamps on edges is false advertising. Graphiti requires `t_valid`/`t_invalid` and `t_created`/`t_expired` on every edge. | LOW | Graphiti provides this out-of-the-box. Implementation task is ensuring episode timestamps come from document `last_synced_at` or source `modified_at`, not ingestion time. |
| **Conflict detection and edge invalidation** | If Doc A says "CAC = spend / acquisitions" and Doc B (newer) says "CAC = spend / (acquisitions + trials)", the graph must resolve this — not store both as equally true. | HIGH | Graphiti's LLM-based invalidation prompt handles this per edge. Requires careful configuration of the invalidation prompt to match business document semantics. |
| **Point-in-time graph query** | Users ask "what did we believe about X in Q3?" — a core value prop of temporal modeling. Without this, temporal modeling is implementation detail, not user value. | MEDIUM | Graphiti's `search()` accepts `reference_time` parameter for point-in-time queries. Agent needs a time-parsing wrapper to convert user expressions ("last quarter", "before the rebrand") to datetime objects. |
| **Graph schema visible to users** | Users need to understand what entity types and relationship types exist in the graph. Otherwise the feature is a black box and they can't formulate useful queries. | LOW | Read from Neo4j schema or maintain a config-driven registry. Expose via `/api/graph/schema` endpoint. Display in UI alongside the explorer. |

### Differentiators (Competitive Advantage)

Features that go beyond "we have a knowledge graph" to actual user value that sets this implementation apart.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Change diff engine: entity-level deltas** | SyncLog already tracks document-level changes. Adding entity-level diffs ("Metric X definition changed: formula was A, now B") answers the question "what actually changed in our business metrics?" — which document-level change logs cannot. | HIGH | Requires comparing entity snapshots before and after ingestion. Diff must be semantic (LLM-assisted for formula changes) not just textual. Store diffs in PG for agent query and UI display. |
| **`get_entity_history` agent tool** | Complements existing `get_change_history`. Where the current tool returns "Document X was re-ingested on date Y", this returns "Entity Z's definition evolved: v1 → v2 → v3 with timestamps and source citations". Directly answers "how has our definition of DAU changed over time?" | MEDIUM | Wraps Graphiti's temporal edge traversal. Returns ordered list of edge states with `t_valid` windows. Needs agent prompt instruction for when to use vs `get_change_history`. |
| **Multi-hop reasoning via graph traversal** | Vector search returns chunks that explicitly contain the answer. Graph traversal finds answers that span multiple documents through relationships — "What KPIs roll up to revenue?" may require traversing 3 hops through metric → composite metric → KPI → revenue target. | HIGH | Agent must be instructed to use multi-hop Cypher traversal for "roll-up", "depends on", "contributes to" question types. Requires well-designed relationship schema with directional semantics. |
| **Graph explorer: entity neighborhood view** | Users paste an entity name (or click a citation) and see its graph neighborhood: what documents define it, what relationships it has, what changed over time. This makes the knowledge graph tangible and explorable without Cypher knowledge. | HIGH | `@neo4j-nvl/react` `InteractiveNvlWrapper` with click-to-expand nodes. Backend: `/api/graph/neighborhood/{entity_id}` endpoint returning NVL-compatible node/edge format. |
| **Ingestion-time graph preview** | After ingestion completes, show a miniature graph of what was added/changed/invalidated in this run. Not just "5 segments added" but "3 entities created, 2 edges updated, 1 conflict resolved". | MEDIUM | Requires Graphiti to return episode-level graph delta. Surfaced in the existing ingestion task result payload. UI: small graph panel on IngestionTaskPage. |
| **Entity confidence scoring with provenance** | Each extracted entity shows: confidence score, which segments it was extracted from, how many documents agree/disagree. Users can audit why an entity has a given value. | MEDIUM | Graphiti tracks episode provenance per edge. `ExtractedEntity.confidence` already exists in PG schema. Extend to surface in UI alongside graph nodes. |
| **"As-of" chat mode** | User prefixes a question with a date ("As of Jan 2025, what was our CAC definition?") and the agent answers using only edges valid at that point in time. | HIGH | Requires NLP date parsing layer (dateparser library) + passing `reference_time` to Graphiti search + agent prompt instruction to preserve temporal context across tool calls. |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **Full Cypher query interface for end users** | Power users want direct Neo4j access. Feels like "opening the hood". | Requires users to learn Cypher. Schema changes break user-written queries. Security surface (injection). Most users are not graph DB experts. | Expose curated `/api/graph/neighborhood`, `/api/graph/path`, `/api/graph/schema` endpoints. Let the agent generate Cypher internally via the graph tool — invisible to users. |
| **Automatic ontology/schema inference** | Tempting to let the LLM freely invent entity types and relationship types. | Without a fixed schema, the graph becomes inconsistent. "METRIC_DEFINITION" and "MetricDef" and "metric" become separate nodes. Retrieval breaks. Merging is expensive. | Define entity types and relationship types upfront in a config file. Use Graphiti's custom entity type support. Enforce schema in extraction prompts. |
| **Real-time graph updates on every chat message** | "The graph should learn from conversations." | Chat messages are user questions + agent answers, not ground-truth business knowledge. Pollutes the graph with speculation, misremembered facts, and query artifacts. Graphiti is designed for episodic memory; this is the wrong episode source. | Only ingest from authoritative sources (the document corpus). Mark conversation-derived nodes with low confidence and exclude from retrieval by default. |
| **Graph-based auth / row-level security in Neo4j** | "Restrict what graph nodes users can see based on role." | Duplicates access control logic that already exists in PG. Neo4j graph permissions are coarse-grained. Maintaining two authorization systems creates drift. | Apply access control at the API layer: filter graph results by project membership (already enforced in PG) before returning to client. |
| **Replacing ES/PG vector search with pure graph search** | "The graph makes vector search redundant." | Graph search excels at relationship traversal; vector search excels at semantic similarity over unstructured text. They complement each other. Removing ES eliminates fuzzy matching on prose content. | Keep hybrid retrieval (ES BM25+kNN) as the primary search. Add graph as a secondary tool (`search_graph`) for relationship questions. Agent chooses which to use. |
| **Live graph synchronization (WebSocket push)** | "The graph explorer should update in real time as documents are ingested." | Adds WebSocket complexity to both backend and frontend. Graph changes during ingestion are high-churn and not useful until ingestion completes. | Poll or refresh-on-demand. Show ingestion status via existing task polling. Refresh graph explorer after task completes. |

---

## Feature Dependencies

```
[Neo4j + Graphiti setup (infrastructure)]
    └──required by──> Entity extraction pipeline (ingest-time graph population)
                          └──required by──> Graph-aware agent tool (search_graph)
                          └──required by──> Entity neighborhood API
                          └──required by──> Change diff engine

[Entity extraction pipeline]
    └──required by──> Bi-temporal edges (populated during extraction)
                          └──required by──> Point-in-time query (reference_time)
                          └──required by──> Entity history tool (get_entity_history)
                          └──required by──> "As-of" chat mode

[Graph-aware agent tool (search_graph)]
    └──required by──> Multi-hop reasoning

[Entity neighborhood API]
    └──required by──> Graph explorer UI (NVL React component)
                          └──required by──> Ingestion-time graph preview

[Change diff engine]
    └──required by──> get_entity_history agent tool

[Graph schema definition (config)]
    └──required by──> Entity extraction pipeline (constrains LLM output types)
    └──required by──> Graph explorer UI (node coloring/labeling by type)
```

### Dependency Notes

- **Neo4j + Graphiti setup must come first:** Every other graph feature depends on the graph database being operational and Graphiti's `add_episode()` being wired into the ingestion pipeline.
- **Graph schema definition is a prerequisite, not a phase:** The entity type list and relationship type list must be agreed-upon and encoded in config before any extraction runs, or the graph will be inconsistent.
- **Change diff engine depends on extraction pipeline:** Can only diff entity states that were captured in the graph. Must run at least 2 ingestion cycles before diffs are meaningful.
- **"As-of" chat mode requires all temporal machinery first:** Depends on bi-temporal edges, point-in-time query, and NLP date parsing all being in place.
- **Graph explorer UI has no external dependencies beyond the API:** Can be built in parallel with agent tools, as long as the neighborhood API exists.

---

## MVP Definition

### Launch With (Phase 1 - 3 of milestone)

Minimum to demonstrate the graph layer is real and useful:

- [ ] **Neo4j + Graphiti infrastructure** — Docker service, async client, health check. Without this nothing runs.
- [ ] **Entity extraction pipeline wired to graph** — Every ingestion run populates graph nodes and edges using Graphiti `add_episode()`. Domain entity types defined in config.
- [ ] **`search_graph` agent tool** — Wraps Graphiti's hybrid search. Claude can answer "how is X related to Y?" questions.
- [ ] **Bi-temporal edges with correct timestamps** — `t_valid` sourced from document `modified_at`, not ingestion clock.
- [ ] **Conflict detection + edge invalidation** — Newer document supersedes older definition. Non-lossy: old edges kept with `expired_at` set.
- [ ] **Entity neighborhood API endpoint** — `/api/graph/neighborhood/{entity_name}` returns N-hop subgraph in NVL format.
- [ ] **Graph explorer UI (basic)** — NVL `InteractiveNvlWrapper` with click-to-expand, node type coloring, zoom/pan. Accessible from chat citations.

### Add After Validation (v2.x)

Add once core graph is running and used:

- [ ] **`get_entity_history` agent tool** — Temporal edge traversal for "how has X changed?" questions. Trigger: users start asking temporal questions that `search_graph` can't fully answer.
- [ ] **Point-in-time query ("As-of" mode)** — NLP date parsing + `reference_time` parameter threading. Trigger: users explicitly ask about historical states.
- [ ] **Change diff engine** — Entity-level semantic diffs on re-ingestion. Trigger: users want to understand what changed, not just that it changed.
- [ ] **Ingestion-time graph preview** — Mini-graph of entities added/changed/invalidated per run. Trigger: users doing frequent re-ingestion.

### Future Consideration (v3+)

Defer until product-market fit on the graph feature is established:

- [ ] **Multi-hop Cypher traversal templates** — Curated traversal patterns for domain-specific questions ("show metric roll-up tree"). High complexity, narrow use case.
- [ ] **"As-of" chat mode (full UX)** — Date picker in chat UI, graph timeline slider. Requires date parsing, temporal retrieval, and UI all working well together first.
- [ ] **Entity confidence audit UI** — Full provenance drill-down showing which segments support each entity value. Complex to build; useful for power users only.
- [ ] **Graph schema management UI** — In-app interface for adding/editing entity types. Premature until the config-file approach proves insufficient.

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Neo4j + Graphiti infrastructure | HIGH (blocker) | MEDIUM | P1 |
| Entity extraction pipeline (ingest-time) | HIGH | HIGH | P1 |
| `search_graph` agent tool | HIGH | LOW | P1 |
| Bi-temporal edges with correct timestamps | HIGH | LOW | P1 |
| Conflict detection + invalidation | HIGH | MEDIUM (Graphiti handles logic; config is the work) | P1 |
| Entity neighborhood API | HIGH | MEDIUM | P1 |
| Graph explorer UI (basic NVL) | HIGH | MEDIUM | P1 |
| `get_entity_history` agent tool | HIGH | MEDIUM | P2 |
| Point-in-time query | MEDIUM | HIGH | P2 |
| Change diff engine | MEDIUM | HIGH | P2 |
| Ingestion-time graph preview | LOW | MEDIUM | P2 |
| "As-of" chat mode (full UX) | MEDIUM | HIGH | P3 |
| Multi-hop Cypher traversal templates | LOW | HIGH | P3 |
| Entity confidence audit UI | LOW | HIGH | P3 |

**Priority key:**
- P1: Must have for milestone to demonstrate value
- P2: Should have, add when P1 is stable
- P3: Nice to have, future milestone

---

## Competitor Feature Analysis

| Feature | Microsoft GraphRAG | Zep/Graphiti | Our Approach |
|---------|-------------------|--------------|--------------|
| Entity extraction | LLM-driven, generic graph | LLM-driven, custom entity types | LLM-driven via Graphiti with domain-specific business types (metric, KPI, process, team) |
| Temporal model | Snapshot-based (no bi-temporal) | Bi-temporal (t_valid/t_invalid + t_created/t_expired) | Graphiti bi-temporal, with document `modified_at` as authoritative `t_valid` source |
| Graph storage | Azure Cosmos DB or Neo4j | Neo4j (primary), FalkorDB, Kuzu | Neo4j for consistency with NVL React library |
| Retrieval strategy | Community summaries + vector search | Hybrid: semantic + BM25 + graph traversal | Graphiti hybrid search as new `search_graph` tool, existing ES hybrid search preserved |
| Visual explorer | None built-in | None built-in | `@neo4j-nvl/react` `InteractiveNvlWrapper` integrated in React app |
| Change detection | None | Edge invalidation (non-lossy) | Graphiti edge invalidation + custom entity-level diff engine for business semantics |
| Agent integration | Via LangChain tools | Via MCP server or direct API | Direct Graphiti Python client in existing Claude tool-use loop |

---

## Dependency on Existing Features

| New Feature | Depends On (Existing) | Integration Point |
|-------------|----------------------|-------------------|
| Entity extraction pipeline | `pipeline.py` ingestion orchestrator | Hook into post-chunking step, before/after ES/PG stores |
| Entity extraction pipeline | `ExtractedEntity` PG table | Existing entity storage remains; graph adds relationship layer |
| `search_graph` tool | `agent.py` tool-use loop | Add to `ALL_TOOLS` list in `tools.py`, implement handler in `agent.py` |
| `get_entity_history` tool | `SyncLog` table (for context) | Read graph edge history; optionally join with SyncLog for document context |
| Graph explorer UI | Document management page | "View in graph" link from document list; citation popover → graph neighborhood |
| Graph explorer UI | Chat citation tooltips | Clicking a citation opens entity neighborhood in graph explorer panel |
| Change diff engine | `content_hash` on segments | Use existing hash to detect re-ingestion; compare entity states before/after |
| Point-in-time query | `modified_at` on documents | Source of `t_valid` timestamp for graph edges |

---

## Sources

- [Graphiti GitHub: Build Real-Time Knowledge Graphs for AI Agents](https://github.com/getzep/graphiti) — entity extraction, bi-temporal model, retrieval API (MEDIUM confidence — web source verified against official docs)
- [Graphiti Overview (Zep Docs)](https://help.getzep.com/graphiti/getting-started/overview) — hybrid search, episode model, sub-second latency (HIGH confidence — official docs)
- [Zep: A Temporal Knowledge Graph Architecture (arXiv 2501.13956)](https://arxiv.org/html/2501.13956v1) — bi-temporal timestamps, invalidation mechanism, entity resolution (HIGH confidence — academic paper from authors)
- [Graphiti: Knowledge Graph Memory for an Agentic World (Neo4j Blog)](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) — architecture overview, Neo4j integration (HIGH confidence — official Neo4j blog)
- [Neo4j Visualization Library React Wrappers](https://neo4j.com/docs/nvl/current/react-wrappers/) — InteractiveNvlWrapper, event handlers, mouse callbacks (HIGH confidence — official Neo4j docs)
- [Graph Retrieval-Augmented Generation: A Survey (ACM TOIS)](https://dl.acm.org/doi/10.1145/3777378) — GraphRAG patterns, multi-hop reasoning (HIGH confidence — peer-reviewed)
- [From LLMs to Knowledge Graphs: Building Production-Ready Graph Systems in 2025](https://medium.com/@claudiubranzan/from-llms-to-knowledge-graphs-building-production-ready-graph-systems-in-2025-2b4aff1ec99a) — production pitfalls, schema importance (LOW confidence — web, single source)
- [Agentic RAG with Knowledge Graphs for Complex Multi-Hop Reasoning (arXiv 2507.16507)](https://arxiv.org/abs/2507.16507) — agent tool design for graph traversal (MEDIUM confidence — academic preprint)
- [Knowledge Graph Extraction and Challenges (Neo4j Blog)](https://neo4j.com/blog/developer/knowledge-graph-extraction-challenges/) — extraction pitfalls, schema consistency (MEDIUM confidence — official blog)

---

*Feature research for: PAM Context — Knowledge Graph & Temporal Reasoning Milestone*
*Researched: 2026-02-19*
