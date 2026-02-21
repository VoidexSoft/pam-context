# Roadmap: PAM Context

## Milestones

- ✅ **v1 Code Quality Cleanup** — Phases 1-5 (shipped 2026-02-19)
- **v2.0 Knowledge Graph & Temporal Reasoning** — Phases 6-9 (in progress)

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
- [ ] **Phase 7: Ingestion Pipeline Extension + Diff Engine** - Graph extraction step, dual-write safety, change detection
- [ ] **Phase 8: Agent Graph Tool + REST Graph Endpoints** - Natural language graph queries via agent, REST API for graph data
- [ ] **Phase 9: Graph Explorer UI** - Visual graph explorer with neighborhood view, entity details, temporal timeline

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
**Plans:** 2 plans
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
| 8. Agent Graph Tool + REST Graph Endpoints | v2.0 | 0/2 | Not started | - |
| 9. Graph Explorer UI | v2.0 | 0/? | Not started | - |
