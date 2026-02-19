# Project Research Summary

**Project:** PAM Context — Knowledge Graph & Temporal Reasoning Milestone
**Domain:** Neo4j knowledge graph + Graphiti bi-temporal model + graph-aware agent + NVL graph explorer
**Researched:** 2026-02-19
**Confidence:** HIGH

## Executive Summary

This milestone adds a graph layer to an already-built Python/FastAPI RAG system (ES + PG + Claude agent). The recommended approach is to use Graphiti (graphiti-core >= 0.28) as the graph engine over Neo4j 5.26+. Graphiti handles everything that would otherwise require bespoke code: LLM-driven entity extraction, bi-temporal edge tracking (t_valid/t_invalid), entity deduplication, and temporal conflict resolution. The graph is additive — it runs alongside the existing ES hybrid search, not replacing it. The existing simple tool-use loop pattern extends cleanly by adding a `search_knowledge_graph` tool with no architectural changes required.

The recommended stack is Neo4j 5.26 Community + graphiti-core[anthropic] >= 0.28 + @neo4j-nvl/react ^1.0.0. The frontend receives graph data as JSON through new FastAPI endpoints — no direct Neo4j browser connection. Graphiti uses Anthropic for entity extraction (consistent with the project's existing Claude usage) and a separate OpenAI embedder for graph-specific embeddings. Two version floor bumps are required in pyproject.toml: openai >= 1.91.0 (was >= 1.50) and tenacity >= 9.0.0 (was >= 8.0).

The top risk is operational: Graphiti's `add_episode()` triggers 5–10 LLM calls per document chunk, making cost and latency management critical. Three design decisions from day one prevent the most expensive recovery scenarios: (1) always use sequential `add_episode()`, never `add_episode_bulk()`, for re-ingested documents; (2) define a bounded entity type taxonomy before any extraction runs; (3) add a `graph_synced` flag to PG documents to track dual-write consistency. None of these can be retrofitted cheaply.

---

## Key Findings

### Recommended Stack

The graph infrastructure adds three new backend packages and three new frontend packages to an otherwise unchanged stack. The Python driver is `neo4j >= 6.1` (the `neo4j-driver` package is deprecated). Graphiti is installed as `graphiti-core[anthropic]` to wire Claude directly as the extraction LLM. The frontend uses `@neo4j-nvl/base`, `@neo4j-nvl/react`, and `@neo4j-nvl/interaction-handlers` — all at ^1.0.0, compatible with the existing React 18 + TypeScript 5.6 setup.

**Core technologies:**
- `neo4j >= 6.1`: Async Bolt driver — v6.x is current (Jan 2026); `neo4j-driver` package is deprecated
- `graphiti-core[anthropic] >= 0.28`: Bi-temporal graph engine — handles entity extraction, deduplication, temporal invalidation, and hybrid search in one library
- `neo4j:5.26-community` (Docker): Minimum version required by Graphiti; APOC not required; Community Edition sufficient
- `@neo4j-nvl/react ^1.0.0`: GPU-accelerated graph renderer — purpose-built for Neo4j data, ships with TypeScript types
- `openai >= 1.91.0`: Version floor bump required by graphiti-core (existing project floor was 1.50)
- `tenacity >= 9.0.0`: Version floor bump required by graphiti-core (existing project floor was 8.0)

Full details: `.planning/research/STACK.md`

### Expected Features

The feature dependency tree has a clear critical path: Neo4j + Graphiti setup must be operational before any other feature, and the entity type schema must be defined before extraction runs. Seven features constitute the MVP (P1); everything else is validated post-launch.

**Must have (table stakes — P1):**
- Entity node creation in Neo4j on every ingestion run — without this the graph is empty
- Relationship edge extraction between entities — entities without edges are just a list
- `search_knowledge_graph` agent tool — makes the graph accessible via natural language
- Bi-temporal edges with timestamps sourced from document `modified_at` — not ingestion clock
- Conflict detection and edge invalidation — newer documents supersede older definitions
- Entity neighborhood API (`/api/graph/neighborhood/{entity_name}`) — backend for the visual explorer
- Graph explorer UI using `InteractiveNvlWrapper` — makes the graph tangible for users

**Should have (differentiators — P2):**
- `get_entity_history` agent tool — temporal edge traversal for "how has X changed?" questions
- Point-in-time graph query (`reference_time` parameter) — answers "what did we believe in Q3?"
- Change diff engine — entity-level semantic diffs on re-ingestion, not just document-level SyncLog
- Ingestion-time graph preview — mini-graph of entities added/changed/invalidated per run

**Defer (v3+):**
- Multi-hop Cypher traversal templates (high complexity, narrow use case)
- Full "As-of" chat mode with date picker UI (requires all temporal machinery first)
- Entity confidence audit UI (power-user feature, not general audience)
- Graph schema management UI (config file approach is sufficient until it isn't)

**Anti-features (do not build):**
- Full Cypher query interface for end users (security surface + Cypher learning curve)
- Schema-free entity extraction (entity type explosion, graph becomes unqueryable)
- Replacing ES/PG vector search with pure graph search (they are complementary, not substitutes)

Full details: `.planning/research/FEATURES.md`

### Architecture Approach

The graph layer is strictly additive. `HybridSearchService` (ES) continues unchanged. Neo4j + Graphiti add a parallel retrieval path via a new `GraphitiService` singleton on `app.state`, following the same pattern already used for `es_client`, `embedder`, and `search_service`. The ingestion pipeline gets one new optional step (step 11) that runs after PG commit — a Graphiti failure never rolls back PG data. The agent gets one new tool dispatch branch in the existing `_execute_tool()` method.

**Major components:**
1. `src/pam/graph/graphiti_service.py` — wraps Graphiti instance; lifecycle on app.state; exposes `add_episode_for_segment()`, `search_facts()`, `get_subgraph()`
2. `src/pam/graph/entity_extractor.py` — bridges ingestion pipeline to Graphiti; converts KnowledgeSegment to episodes
3. `src/pam/graph/diff_engine.py` — detects entity/edge changes between re-ingestion runs; delegates temporal conflict resolution to Graphiti's built-in invalidation
4. `src/pam/graph/pam_entity_types.py` — bounded PAM entity type taxonomy as Pydantic models (Metric, KPITarget, Process, Team, System)
5. `src/pam/api/routes/graph.py` — REST endpoints: GET /api/graph/nodes, /api/graph/subgraph, /api/graph/entities
6. `web/src/components/graph/GraphExplorer.tsx` — `InteractiveNvlWrapper` as collapsible side panel; data from graph API hooks
7. `src/pam/agent/tools.py` + `agent.py` — `SEARCH_KNOWLEDGE_GRAPH_TOOL` definition + `_search_knowledge_graph()` dispatch

**Key patterns:**
- GraphitiService as `app.state` singleton (matches existing es_client pattern)
- Anthropic for extraction LLM + independent OpenAI embedder for graph embeddings (two separate instances)
- `group_id = source_id` in every `add_episode()` call (document-scoped episode isolation)
- One episode per KnowledgeSegment, not per document (fine-grained temporal tracking)
- Graph extraction runs as step 11 after PG commit (failure-safe, non-blocking)
- Conditional rendering: `VITE_GRAPH_ENABLED` env flag gates the graph explorer

**Build order:** Infrastructure → GraphitiService + lifespan → Ingestion extension → Diff engine → Agent tool → REST endpoints → Graph explorer UI

Full details: `.planning/research/ARCHITECTURE.md`

### Critical Pitfalls

1. **`add_episode_bulk()` silently skips temporal invalidation** — use `add_episode()` (sequential) unconditionally for all ingestion, both initial and re-ingestion. The bulk path is only for one-time empty-graph bootstrap. Stale contradictory edges resulting from this error cannot be fixed without a full graph rebuild.

2. **Entity type explosion without a predefined schema** — define the entity type taxonomy (`Metric`, `KPITarget`, `Process`, `Team`, `System`) as Pydantic models before writing any extraction code. If the LLM invents entity type names freely, the graph becomes unqueryable within 20 documents and requires a full rebuild to fix.

3. **Dual-write consistency gap (PG committed, Neo4j extraction failed)** — add a `graph_synced` boolean to the `documents` PG table. Set it `False` on ingest start, `True` only after `add_episode()` completes. The content hash check must consider `graph_synced` status, or documents with failed graph extraction are permanently missing from the graph.

4. **LLM extraction cost is multiplicative (5–10 calls per chunk)** — a 50-chunk document triggers 150–300 LLM API calls at Claude claude-sonnet-4-6 pricing. Mitigations: use Claude Haiku for extraction, lower `SEMAPHORE_LIMIT` to 3–5 against Anthropic API, profile costs on a sample document before full corpus ingestion, enable prompt caching.

5. **`search_knowledge_graph` tool degrades existing tool routing** — adding tool 6 changes how Claude selects between all 6 tools on every request. Write the new tool description to emphasize relationship traversal exclusively; update `search_entities` description to de-emphasize relationship queries; run `eval/questions.json` baseline comparison after every tool addition.

6. **Neo4j AsyncSession not concurrency-safe** — never share a session across coroutines. The driver is the singleton; sessions are created and closed per request via dependency injection (same pattern as `get_db_session`).

7. **Orphan nodes accumulate on document re-ingestion** — Graphiti's non-lossy temporal model never deletes nodes. Implement episode soft-delete using `group_id = source_id` before calling `add_episode()` on re-ingestion to tombstone prior episodes from that document.

Full details: `.planning/research/PITFALLS.md`

---

## Implications for Roadmap

The feature dependency tree and pitfall-to-phase mapping from research align on a 4-phase build order. Every phase has a clear gate: do not start the next phase until the current phase's verification criteria pass.

### Phase 1: Neo4j + Graphiti Infrastructure

**Rationale:** Everything else is blocked by this phase. No graph feature can be built or tested without the graph database running, the Python package installed, and the driver lifecycle established correctly. Neo4j memory configuration and the decision to ban `add_episode_bulk()` must be locked in before any data is written.

**Delivers:** Docker Neo4j service with health check and explicit memory config; `graphiti-core[anthropic]` installed; config settings for `neo4j_uri`/`neo4j_user`/`neo4j_password`/`graph_enabled`; `GraphitiService` singleton on `app.state`; `PAM_ENTITY_TYPES` Pydantic schemas (the entity type taxonomy); `get_graph_service()` dependency; `@neo4j-nvl` packages installed in web/.

**Addresses (from FEATURES.md):** Infrastructure prerequisite for all P1 features.

**Avoids (from PITFALLS.md):**
- Pitfall 2: Neo4j AsyncSession concurrency — driver lifecycle established in lifespan from day one
- Pitfall 8: Neo4j memory defaults — explicit heap/page cache config in docker-compose before any data is written
- Pitfall 3: LLM extraction cost — profile on sample document before wiring into ingestion pipeline

**Gate:** `docker-compose up neo4j` passes health check; `from graphiti_core import Graphiti` imports without error; `GraphitiService` unit tests pass with mocked Graphiti client; entity type taxonomy has <= 10 types defined.

---

### Phase 2: Ingestion Pipeline Extension + Diff Engine

**Rationale:** Before building any user-facing features, graph data must be populated. The ingestion pipeline extension and dual-write safety mechanisms (Pitfalls 1, 5, 10) must be solved together — retrofitting them after ingestion code is written is a full rebuild.

**Delivers:** Step 11 in pipeline (graph extraction after PG commit); `GraphEntityExtractor` bridging pipeline to Graphiti; `graph_synced` flag in PG `documents` table (new Alembic migration); reconciliation endpoint (`/ingest/sync-graph`); `GraphDiffEngine` writing entity-level diff summaries to `SyncLog.details`; orphan node prevention via pre-ingestion episode tombstoning by `group_id`.

**Addresses (from FEATURES.md):** Entity node creation, relationship edge extraction, bi-temporal edges with correct timestamps, conflict detection and edge invalidation.

**Avoids (from PITFALLS.md):**
- Pitfall 1: `add_episode_bulk()` ban baked in — use sequential path only
- Pitfall 4: Entity type taxonomy locked before first extraction run (completed in Phase 1)
- Pitfall 5: Orphan nodes — `group_id`-scoped tombstoning before re-ingestion
- Pitfall 10: `graph_synced` flag + reconciliation job before production ingestion

**Gate:** Ingest a test markdown document; verify entities appear in Neo4j. Re-ingest a modified document; verify old facts have `t_invalid` set. Re-ingest the same document 3 times; verify node count for that document's entities does not grow. `MATCH (n) RETURN DISTINCT labels(n)` returns <= 15 distinct labels after 20 documents.

---

### Phase 3: Agent Graph Tool + REST Graph Endpoints

**Rationale:** With graph data populated, the primary user-facing value — natural language graph queries via the agent — can be built. REST endpoints are built in the same phase because the agent tool and the explorer UI share the same backend graph query logic, and building the API before the UI enables independent testing.

**Delivers:** `SEARCH_KNOWLEDGE_GRAPH_TOOL` definition and `_search_knowledge_graph()` dispatch in agent; `graph_service` optional param on `RetrievalAgent`; updated system prompt with tool routing instructions; `src/pam/api/routes/graph.py` with GET /api/graph/nodes, /api/graph/subgraph, /api/graph/entities endpoints; Pydantic response models for graph data.

**Addresses (from FEATURES.md):** `search_graph` agent tool, entity neighborhood API, graph schema endpoint.

**Avoids (from PITFALLS.md):**
- Pitfall 6: Hard cap on tool result size (20 nodes / 30 edges max; prose format not raw JSON)
- Pitfall 7: Tool routing regression — write distinct tool descriptions; run `eval/questions.json` baseline comparison before and after tool addition

**Gate:** End-to-end test: ingest → ask "what team owns MRR?" → agent uses `search_knowledge_graph` and returns entity relationship from Neo4j. Eval score on `eval/questions.json` matches or exceeds pre-graph-tool baseline. Any single graph tool result is <= 3000 characters.

---

### Phase 4: Graph Explorer UI

**Rationale:** All backend work is complete. The REST API returns validated data. The UI can be built against real graph data without speculative assumptions about API shape. NVL rendering performance pitfalls require deliberate component architecture from the start — this cannot be added incrementally to an existing layout.

**Delivers:** `useGraph.ts` React Query hook for graph API; `GraphExplorer.tsx` using `InteractiveNvlWrapper` as collapsible side panel; `EntityPanel.tsx` for click-to-expand entity detail; `TemporalTimeline.tsx` for t_valid/t_invalid visualization; toggle button in chat layout; `VITE_GRAPH_ENABLED` env flag; "Graph indexing in progress" state when `graph_synced` count is 0.

**Addresses (from FEATURES.md):** Graph explorer UI with click-to-expand, node type coloring, zoom/pan; ingestion-time graph preview (mini-graph on IngestionTaskPage).

**Avoids (from PITFALLS.md):**
- Pitfall 9: NVL reinit on every render — `React.memo()` + `useMemo()` from day one; graph component on sibling route, not nested in chat
- UX pitfalls: default to ego-graph view (1 hop), not full corpus; show "indexing in progress" state; render diffs as prose not raw JSON

**Gate:** React Profiler shows NVL component does not re-render during chat message send. Graph explorer loads entity neighborhood within 2 seconds. Pan/zoom state is preserved when user types in chat input. Canvas does not flicker during conversation streaming.

---

### Phase Ordering Rationale

- **Infrastructure before everything:** Graphiti's `build_indices_and_constraints()` must have run before any write, and the entity type taxonomy must be locked before any extraction. Neither can be retrofitted.
- **Ingestion before agent:** The `search_knowledge_graph` tool returns empty results until the graph is populated. Building the agent before ingestion creates false negatives in testing and misleads users about graph capability.
- **Agent + REST API before UI:** The UI is a thin client over the REST API. Building it before the API shape is finalized means UI code must be rewritten when the API changes.
- **Diff engine in Phase 2, not later:** The diff engine depends on comparing entity states across ingestion runs. It requires at least 2 full ingestion cycles to produce meaningful output. Deferring it means waiting weeks for enough re-ingestion history.
- **`graph_synced` flag required before Phase 3:** The agent tool must not mislead users with missing graph data. The flag and reconciliation job ensure the graph is complete before the tool is activated.

### Research Flags

Phases likely needing deeper research during planning:

- **Phase 2 (Ingestion + Diff Engine):** The `add_episode()` signature, `group_id` semantics, and episode tombstoning mechanism should be validated against the exact Graphiti 0.28 API before implementation. Read `graphiti_core/graphiti.py` directly. The diff engine design (querying edges with `t_invalid` set post-ingestion) needs verification against actual Graphiti query patterns.
- **Phase 3 (Agent Tool):** Tool routing degradation (Pitfall 7) has no deterministic solution — it requires empirical testing against `eval/questions.json`. Plan for a tuning iteration on tool descriptions.

Phases with well-documented patterns (skip research-phase):

- **Phase 1 (Infrastructure):** Neo4j Docker setup, Graphiti lifespan initialization, and NVL npm installation are all fully documented with exact configuration. No research needed during planning.
- **Phase 4 (Graph Explorer UI):** NVL React component usage is well-documented. `React.memo` + `useMemo` patterns for canvas components are standard. No novel research needed.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All core packages verified via official docs, PyPI, and GitHub pyproject.toml. Version floors for graphiti-core transitive deps confirmed from source. NVL version confirmed via WebSearch + official Neo4j docs (npm page inaccessible). |
| Features | HIGH | Feature taxonomy derived from Graphiti official docs, Zep arXiv paper, and Neo4j documentation. GraphRAG survey (ACM TOIS) confirms multi-hop reasoning patterns. |
| Architecture | HIGH | Architecture research directly read the live codebase (agent.py, pipeline.py, deps.py, models.py). All integration points confirmed against real code, not assumptions. |
| Pitfalls | HIGH | Critical pitfalls verified against official documentation (Graphiti bulk ingestion warning, Neo4j AsyncSession docs, Neo4j memory defaults) and GitHub issue evidence. Direct codebase analysis for existing anti-patterns. |

**Overall confidence:** HIGH

### Gaps to Address

- **Graphiti 0.28 exact API for episode tombstoning:** The approach of querying and soft-deleting prior episodes by `group_id` before re-ingestion is architecturally sound but the exact Graphiti API call sequence needs validation during Phase 2 planning. Read `graphiti_core/graphiti.py` directly before implementing.
- **Claude rate limits under `SEMAPHORE_LIMIT`:** Recommended `SEMAPHORE_LIMIT=3–5` for Anthropic API, but the exact limit depends on the project's API tier. Validate during Phase 1 smoke test on a 10-document sample before committing to a value.
- **NVL temporal timeline component:** `TemporalTimeline.tsx` is proposed but NVL does not ship a timeline widget natively. Implementation will require custom React + CSS — not a pure NVL feature. Scope this during Phase 4 planning.
- **Alembic migration for `graph_synced` flag:** A `graph_synced` column on the `documents` table is required for Pitfall 10 mitigation. This is a schema change needing an Alembic migration — confirm it does not conflict with existing migration state before Phase 2.

---

## Sources

### Primary (HIGH confidence)
- [graphiti-core PyPI v0.28.0](https://pypi.org/project/graphiti-core/) — version, license, transitive deps
- [getzep/graphiti GitHub pyproject.toml](https://github.com/getzep/graphiti/blob/main/pyproject.toml) — exact dependency version floors
- [Zep Graphiti Documentation](https://help.getzep.com/graphiti/) — Neo4j config, custom entity types, quick start, LLM config, bulk ingestion warning
- [Zep Temporal KG Architecture (arXiv 2501.13956)](https://arxiv.org/html/2501.13956v1) — bi-temporal model, invalidation mechanism, entity resolution
- [Neo4j Python Driver 6.x docs](https://neo4j.com/docs/api/python-driver/current/) — async API, AsyncSession concurrency warning, driver vs session lifecycle
- [Neo4j NVL React Wrappers docs](https://neo4j.com/docs/nvl/current/react-wrappers/) — InteractiveNvlWrapper, BasicNvlWrapper
- [Neo4j NVL Installation docs](https://neo4j.com/docs/nvl/current/installation/) — npm packages, free licensing
- [Neo4j Docker Hub](https://hub.docker.com/_/neo4j) — 5.26-community image tag, memory configuration docs
- [PAM codebase (direct read)](src/pam/) — agent.py, pipeline.py, deps.py, models.py, config.py — all integration points confirmed
- [Graph RAG Survey (ACM TOIS)](https://dl.acm.org/doi/10.1145/3777378) — GraphRAG patterns, multi-hop reasoning
- [Graphiti change detection blog (Zep)](https://blog.getzep.com/beyond-static-knowledge-graphs/) — temporal invalidation design

### Secondary (MEDIUM confidence)
- [Graphiti GitHub issues #871, #879, #223](https://github.com/getzep/graphiti) — bulk ingestion instability documented in issues
- [Neo4j Graphiti blog (Neo4j developer blog)](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) — integration overview
- [Agentic RAG with Knowledge Graphs (arXiv 2507.16507)](https://arxiv.org/abs/2507.16507) — agent tool design for graph traversal
- [@neo4j-nvl/react npm](https://www.npmjs.com/package/@neo4j-nvl/react) — version 1.0.0 (npm page inaccessible, confirmed via WebSearch)
- [Anthropic tool-use engineering blog](https://anthropic.com) — tool definitions token consumption

### Tertiary (LOW confidence)
- [Building Production-Ready Graph Systems in 2025 (Medium)](https://medium.com/@claudiubranzan/from-llms-to-knowledge-graphs-building-production-ready-graph-systems-in-2025-2b4aff1ec99a) — production pitfalls, schema importance (single source)
- [Knowledge Graph Extraction Challenges (Neo4j Blog)](https://neo4j.com/blog/developer/knowledge-graph-extraction-challenges/) — extraction pitfalls (official blog, qualitative)

---

*Research completed: 2026-02-19*
*Ready for roadmap: yes*
