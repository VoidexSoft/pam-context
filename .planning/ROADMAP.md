# Roadmap: PAM Context

## Milestones

- ✅ **v1 Code Quality Cleanup** — Phases 1-5 (shipped 2026-02-19)
- ✅ **v2.0 Knowledge Graph & Temporal Reasoning** — Phases 6-9 (complete 2026-02-21)
- **v3.0 LightRAG-Inspired Smart Retrieval** — Phases 12-15 (planned)

## Phases

<details>
<summary>v1 Code Quality Cleanup (Phases 1-5) — SHIPPED 2026-02-19</summary>

- [x] Phase 1: Singleton Lifecycle + Tooling (2/2 plans) — completed 2026-02-16
- [x] Phase 2: Database Integrity (1/1 plan) — completed 2026-02-16
- [x] Phase 3: API + Agent Hardening (3/3 plans) — completed 2026-02-18
- [x] Phase 4: Frontend + Dead Code Cleanup (2/2 plans) — completed 2026-02-18
- [x] Phase 5: Audit Gap Closure (2/2 plans) — completed 2026-02-18

Full details: `.planning/milestones/v1-ROADMAP.md`

</details>

### v2.0 Knowledge Graph & Temporal Reasoning

- [x] **Phase 6: Neo4j + Graphiti Infrastructure** - Graph database, Graphiti engine, entity schema, and service lifecycle
- [x] **Phase 7: Ingestion Pipeline Extension + Diff Engine** - Graph extraction step, dual-write safety, change detection (completed 2026-02-20)
- [x] **Phase 8: Agent Graph Tool + REST Graph Endpoints** - Natural language graph queries via agent, REST API for graph data (completed 2026-02-21)
- [x] **Phase 9: Graph Explorer UI** - Visual graph explorer with neighborhood view, entity details, temporal timeline (completed 2026-02-21)
- [x] **Phase 10: Bi-temporal Timestamp Pipeline Fix** - Wire document modified_at through to graph extraction reference_time (gap closure) (completed 2026-02-22)
- [ ] **Phase 11: Graph Polish + Tech Debt Cleanup** - Fix VIZ-06 empty state, graph service null guard, lint, docs alignment (gap closure)

## Phase Details

### Phase 6: Neo4j + Graphiti Infrastructure
**Goal**: The graph database is running, the Graphiti engine is configured, the entity type schema is locked, and the service lifecycle follows established FastAPI patterns — so that all subsequent phases can write and read graph data without infrastructure work.
**Depends on**: Phase 5 (v1 complete)
**Requirements**: INFRA-01, INFRA-02, INFRA-03, INFRA-04, INFRA-05, INFRA-06
**Success Criteria** (what must be TRUE):
  1. `docker compose up` starts Neo4j alongside existing services, and Neo4j passes its health check within 30 seconds
  2. Python code can `from graphiti_core import Graphiti` and initialize a client that connects to the running Neo4j instance
  3. `GraphitiService` is available on `app.state` via `get_graph_service()` dependency, following the same `cast()` pattern used by existing services
  4. Entity type taxonomy exists as Pydantic models with 10 or fewer types, importable from `src/pam/graph/`
  5. Frontend `@neo4j-nvl` packages are installed and importable in the web/ project (verified by a trivial import in a test file)
**Plans:** 3 plans
Plans:
- [x] 06-01-PLAN.md — Docker Compose Neo4j + graphiti-core dependency + entity type taxonomy + GraphitiService class
- [x] 06-02-PLAN.md — FastAPI lifespan integration + deps.py + health check + graph status endpoint + tests
- [x] 06-03-PLAN.md — NVL packages + feature-flagged /graph route + placeholder graph status page

### Phase 7: Ingestion Pipeline Extension + Diff Engine
**Goal**: Every ingested document produces entity nodes and relationship edges in Neo4j with correct bi-temporal timestamps, graph failures never corrupt PG/ES data, and re-ingestion detects entity-level changes — so that the graph contains queryable knowledge before any user-facing feature is built.
**Depends on**: Phase 6
**Requirements**: EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-04, EXTRACT-05, EXTRACT-06, DIFF-01, DIFF-02, DIFF-03
**Success Criteria** (what must be TRUE):
  1. Ingesting a Markdown document creates entity nodes and relationship edges in Neo4j, with bi-temporal timestamps sourced from the document's `modified_at` field
  2. Re-ingesting a modified document sets `t_invalid` on superseded edges and creates new edges for changed facts, without growing orphan node count for that document
  3. If Neo4j is unreachable during ingestion, the document still commits to PG and ES successfully, with `graph_synced=False` recorded in PostgreSQL
  4. Calling `POST /ingest/sync-graph` retries graph extraction for all documents where `graph_synced=False` and updates the flag on success
  5. Entity-level diff summaries (added/modified/removed entities) are written to `SyncLog.details` as structured JSON after each re-ingestion
**Plans:** 2 plans
Plans:
- [ ] 07-01-PLAN.md — Alembic migration + Document model + Graph extraction orchestrator + Diff engine
- [ ] 07-02-PLAN.md — Pipeline integration + Sync recovery endpoint + skip_graph API support

### Phase 8: Agent Graph Tool + REST Graph Endpoints
**Goal**: Users can ask the Claude agent relationship and temporal questions that are answered from the knowledge graph, and REST endpoints serve graph data for the upcoming UI — so that graph knowledge is accessible through natural language and API before any frontend work begins.
**Depends on**: Phase 7
**Requirements**: GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-04, GRAPH-05, GRAPH-06
**Success Criteria** (what must be TRUE):
  1. Asking the agent "what depends on [entity]?" or "what team owns [entity]?" triggers the `search_knowledge_graph` tool and returns relationship data from Neo4j
  2. Asking the agent "how has [entity] changed since [date]?" triggers the `get_entity_history` tool and returns temporal edge history
  3. Passing a `reference_time` parameter to graph queries returns the graph state as it was believed at that point in time
  4. `GET /api/graph/neighborhood/{entity}` returns a 1-hop subgraph (nodes + edges) and `GET /api/graph/entities` returns all entity nodes with type and name
  5. No single graph tool result exceeds 3000 characters or 20 nodes, and existing eval scores on `eval/questions.json` do not regress after adding graph tools
**Plans:** 2/2 plans complete
Plans:
- [ ] 08-01-PLAN.md — Agent graph tools (search_knowledge_graph + get_entity_history + graph_service injection)
- [ ] 08-02-PLAN.md — REST graph endpoints (neighborhood subgraph + entity listing with pagination)

### Phase 9: Graph Explorer UI
**Goal**: Users can visually explore the knowledge graph alongside chat, inspect entity details and temporal history, and see graph extraction status — so that graph knowledge is tangible and navigable beyond the chat interface.
**Depends on**: Phase 8
**Requirements**: VIZ-01, VIZ-02, VIZ-03, VIZ-04, VIZ-05, VIZ-06
**Success Criteria** (what must be TRUE):
  1. A collapsible graph explorer panel shows entity neighborhoods using NVL, with pan/zoom that does not interfere with the chat interface
  2. Clicking an entity node expands a detail panel showing its properties, relationships, and temporal history (t_valid/t_invalid edges)
  3. After an ingestion run, a graph preview shows which entities were added, changed, or invalidated in that run
  4. The graph explorer is gated behind `VITE_GRAPH_ENABLED` — when disabled, no graph UI elements render; when `graph_synced` count is 0, a "Graph indexing in progress" state is shown
  5. The NVL graph component does not re-render during chat message streaming, and pan/zoom state is preserved when the user types in the chat input
**Plans:** 3 plans
Plans:
- [x] 09-01-PLAN.md — Backend REST endpoints (entity history + sync-logs) + frontend API client types and functions
- [x] 09-02-PLAN.md — Graph explorer page with NVL canvas, entity sidebar (search + details + temporal timeline), route and feature-flag gating
- [x] 09-03-PLAN.md — Ingestion diff preview with color-coded canvas + chat entity deep-links

### Phase 10: Bi-temporal Timestamp Pipeline Fix
**Goal**: Document modification timestamps flow through the ingestion pipeline to graph extraction, so that bi-temporal graph queries reflect when facts were actually valid — not when they were ingested.
**Depends on**: Phase 7
**Requirements**: EXTRACT-02
**Gap Closure**: Closes partial requirement from v2.0 audit
**Success Criteria** (what must be TRUE):
  1. `RawDocument` model has a `modified_at: datetime | None` field populated from connector metadata
  2. `add_episode()` calls use `modified_at` as `reference_time` when available, falling back to `datetime.now(UTC)` only when `modified_at` is None
  3. Re-ingestion of a document with a different `modified_at` produces edges with the correct temporal timestamps
**Plans:** 1/1 plans complete
Plans:
- [ ] 10-01-PLAN.md — Add modified_at to models/migration + connector population + pipeline/sync-endpoint reference_time wiring

### Phase 11: Graph Polish + Tech Debt Cleanup
**Goal**: All v2.0 spec mismatches and tech debt identified by the milestone audit are resolved — so that the milestone can be archived cleanly.
**Depends on**: Phase 9
**Requirements**: VIZ-06
**Gap Closure**: Closes partial requirement + 4 tech debt items from v2.0 audit
**Success Criteria** (what must be TRUE):
  1. Graph explorer empty state shows "Graph indexing in progress" when documents exist but `graph_synced` count is 0, and "No documents ingested" when no documents exist
  2. Graph REST endpoints have explicit null guard for `get_graph_service()` returning None (not relying on outer try/except alone)
  3. `ingest.py:121` uses `raise ... from err` pattern (ruff B904 resolved)
  4. All 10 SUMMARY.md files include `requirements_completed` frontmatter field
**Plans:** 1/2 plans executed
Plans:
- [ ] 11-01-PLAN.md — VIZ-06 empty state + graph_status PG counts + graph endpoint null guards
- [ ] 11-02-PLAN.md — Ruff B904 fix (3 files) + SUMMARY.md frontmatter standardization (11 files)

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Singleton Lifecycle + Tooling | v1 | 2/2 | Complete | 2026-02-16 |
| 2. Database Integrity | v1 | 1/1 | Complete | 2026-02-16 |
| 3. API + Agent Hardening | v1 | 3/3 | Complete | 2026-02-18 |
| 4. Frontend + Dead Code Cleanup | v1 | 2/2 | Complete | 2026-02-18 |
| 5. Audit Gap Closure | v1 | 2/2 | Complete | 2026-02-18 |
| 6. Neo4j + Graphiti Infrastructure | v2.0 | 3/3 | Complete | 2026-02-19 |
| 7. Ingestion Pipeline Extension + Diff Engine | v2.0 | 2/2 | Complete | 2026-02-20 |
| 8. Agent Graph Tool + REST Graph Endpoints | v2.0 | 2/2 | Complete | 2026-02-21 |
| 9. Graph Explorer UI | v2.0 | 3/3 | Complete | 2026-02-21 |
| 10. Bi-temporal Timestamp Pipeline Fix | v2.0 | 1/1 | Complete | 2026-02-22 |
| 11. Graph Polish + Tech Debt Cleanup | v2.0 | 1/2 | In Progress | — |
| 12. Dual-Level Keyword Extraction + Unified Search | v3.0 | 0/2 | Pending | — |
| 13. Entity & Relationship Vector Indices | v3.0 | 0/2 | Pending | — |
| 14. Graph-Aware Context Assembly + Token Budgets | v3.0 | 0/2 | Pending | — |
| 15. Retrieval Mode Router | v3.0 | 0/2 | Pending | — |

### v3.0 LightRAG-Inspired Smart Retrieval

Inspired by [LightRAG](https://github.com/HKUDS/LightRAG) (EMNLP 2025). Key insight: integrating knowledge graph into both indexing and retrieval with dual-level (entity + relationship) keyword extraction produces dramatically better results than treating text search and graph search as separate paths. LightRAG achieves ~6,000x fewer retrieval tokens than GraphRAG with comparable quality.

- [ ] **Phase 12: Dual-Level Keyword Extraction + Unified Search Tool** - Query keyword generation + merged ES/graph retrieval in one tool call
- [ ] **Phase 13: Entity & Relationship Vector Indices** - Embed entity descriptions and relationship descriptions into ES as separate searchable indices
- [ ] **Phase 14: Graph-Aware Context Assembly with Token Budgets** - Structured context blocks with per-category token limits for entity, relationship, and chunk data
- [ ] **Phase 15: Retrieval Mode Router** - Query classification to select optimal retrieval strategy per question type

### Phase 12: Dual-Level Keyword Extraction + Unified Search Tool
**Goal**: A single `smart_search` agent tool generates entity-level and theme-level keywords from the query, runs ES hybrid search and graph relationship search in parallel, and returns merged results — so that the agent answers graph-aware questions in 1 tool call instead of 2-3, following LightRAG's dual-level retrieval pattern.
**Depends on**: Phase 11
**Inspired by**: LightRAG `extract_keywords_only()` + `_perform_kg_search()` dual-path retrieval
**Requirements**: SMART-01, SMART-02, SMART-03
**Success Criteria** (what must be TRUE):
  1. A new `smart_search` tool exists that accepts a natural language query and returns merged results from both ES and the knowledge graph
  2. Before retrieval, the tool calls Claude to extract `{"high_level_keywords": [...], "low_level_keywords": [...]}` from the query (~50 tokens)
  3. Low-level keywords drive ES hybrid search (BM25 + kNN); high-level keywords drive Graphiti semantic edge search — both run concurrently
  4. Results are merged via round-robin interleaving (alternating ES and graph results) with deduplication by content hash
  5. Existing `search_knowledge` and `search_knowledge_graph` tools remain available as fallbacks, but `smart_search` is the agent's preferred first tool
  6. Agent tool iterations for relationship-aware questions drop from 2-3 to 1 (measured on eval/questions.json)
Plans:
- [ ] 12-01-PLAN.md — Keyword extraction prompt + `extract_query_keywords()` function
- [ ] 12-02-PLAN.md — `smart_search` tool implementation + result merging + agent integration

### Phase 13: Entity & Relationship Vector Indices
**Goal**: Entity descriptions and relationship descriptions are independently embedded and searchable in Elasticsearch — so that semantic entity discovery ("find teams working on deployment") and relationship discovery ("what connects infrastructure to reliability") work without knowing exact entity names, following LightRAG's 3-VDB pattern.
**Depends on**: Phase 12
**Inspired by**: LightRAG `entities_vdb` + `relationships_vdb` with content = `"{name}\n{description}"` and `"{keywords}\t{src}\n{tgt}\n{description}"`
**Requirements**: VDB-01, VDB-02, VDB-03
**Success Criteria** (what must be TRUE):
  1. ES index `pam_entities` stores entity records with fields: `name`, `entity_type`, `description`, `embedding` (1536-dim), `source_ids`, `file_paths`
  2. ES index `pam_relationships` stores relationship records with fields: `src_entity`, `tgt_entity`, `keywords`, `description`, `embedding` (1536-dim), `weight`, `source_ids`
  3. During graph extraction, entity and relationship descriptions are embedded and upserted into these indices alongside the existing Neo4j writes
  4. `smart_search` uses entity VDB for low-level keyword matching and relationship VDB for high-level keyword matching (in addition to existing `pam_segments` and Graphiti search)
  5. Re-ingestion updates entity/relationship embeddings when descriptions change (keyed by entity name or sorted src+tgt pair)
Plans:
- [ ] 13-01-PLAN.md — ES index schemas + embedding pipeline for entities/relationships during extraction
- [ ] 13-02-PLAN.md — Vector search functions + smart_search integration

### Phase 14: Graph-Aware Context Assembly with Token Budgets
**Goal**: Retrieved results are assembled into structured context blocks with explicit per-category token budgets — so that the LLM receives optimally organized context (entities, relationships, source chunks) within predictable token limits, following LightRAG's 4-stage context pipeline.
**Depends on**: Phase 13
**Inspired by**: LightRAG `_build_query_context()` 4-stage pipeline: search -> truncate -> merge chunks -> build context string
**Requirements**: CTX-01, CTX-02, CTX-03
**Success Criteria** (what must be TRUE):
  1. Context assembly follows a 4-stage pipeline: (1) raw retrieval, (2) per-category token truncation, (3) chunk dedup and merge, (4) structured prompt construction
  2. Token budgets are configurable: entity descriptions (default 4000), relationship descriptions (default 6000), source chunks (dynamic: total budget minus other categories)
  3. The agent's system prompt includes structured context blocks: `## Knowledge Graph Entities`, `## Knowledge Graph Relationships`, `## Document Chunks` with source references
  4. Context assembly happens inside `smart_search` before returning to the agent, not as a separate tool call
  5. Total context per search result stays within a configurable `max_context_tokens` (default 12000), preventing context window bloat from large result sets
Plans:
- [ ] 14-01-PLAN.md — Token-budgeted context assembly pipeline + structured prompt templates
- [ ] 14-02-PLAN.md — Integration with smart_search + agent system prompt updates

### Phase 15: Retrieval Mode Router
**Goal**: A query classifier routes each question to the optimal retrieval strategy — so that entity-specific questions use graph-first retrieval, conceptual questions use relationship search, temporal questions use history tools, and simple factual questions skip the graph entirely, following LightRAG's mode-based retrieval pattern.
**Depends on**: Phase 14
**Inspired by**: LightRAG's 6 retrieval modes (naive, local, global, hybrid, mix, bypass) adapted to PAM's tool ecosystem
**Requirements**: MODE-01, MODE-02, MODE-03
**Success Criteria** (what must be TRUE):
  1. A `classify_query_mode()` function categorizes queries into modes: `entity` (graph-first), `conceptual` (relationship-first), `temporal` (history-first), `factual` (ES-only), `hybrid` (all sources)
  2. Classification uses either a lightweight LLM call (~30 tokens) or rule-based heuristics (entity name detection, temporal keywords, question patterns)
  3. `smart_search` uses the classified mode to skip unnecessary retrieval paths (e.g., `factual` mode skips graph search entirely)
  4. Mode selection reduces average retrieval latency by skipping irrelevant search paths for 40%+ of queries
  5. Mode classification is logged in agent response metadata for observability and tuning
Plans:
- [ ] 15-01-PLAN.md — Query classifier implementation (LLM-based + rule-based fallback)
- [ ] 15-02-PLAN.md — Mode-based routing in smart_search + observability logging
