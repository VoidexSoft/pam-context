# Phase 3: Knowledge Graph & Temporal Reasoning — Implementation Plan

**Goal**: Add Neo4j knowledge graph for relationship modeling and "what changed and why" reasoning.

**Dependency**: Phase 2 complete (confirmed: 396 tests passing, all components integrated)

---

## Phase Overview

| # | Component | Risk | Priority | Status |
|---|-----------|------|----------|--------|
| 3.1 | Neo4j Setup & Infrastructure | LOW | High | pending |
| 3.2 | Entity-to-Graph Pipeline | MEDIUM | High | pending |
| 3.3 | Graph-Aware Retrieval (Agent Tools) | MEDIUM | High | pending |
| 3.4 | Change Detection & History | MEDIUM | Medium | pending |
| 3.5 | Frontend: Knowledge Graph Explorer | LOW | Lower | pending |

**Current test count**: 396 tests (baseline before Phase 3)

---

## Key Technical Decisions

| Decision | Rationale |
|----------|-----------|
| **Neo4j direct driver** (not Graphiti) | Graphiti v0.27 is still RC; we already have entity extraction; direct driver gives more control over schema |
| **neo4j v6.1** Python driver | Latest stable (Jan 2026), full async support, matches our async-everywhere pattern |
| **Neo4j Community 5.x** Docker | Free, sufficient for our graph workload, compatible with driver v6.1 |
| **D3.js/react-force-graph** for frontend | Lighter than vis.js, React-native integration, good for interactive graph exploration |
| **Temporal edges** (valid_from/valid_to) | Simple bi-temporal model on relationship properties, not full Graphiti overhead |

---

## Implementation Order (Dependency-Aware)

### Wave 1: Neo4j Infrastructure
> Foundation: Docker service, driver, schema, health check.

#### Step 3.1 — Neo4j Setup `status: pending`

**3.1.1 — Docker & Driver Setup**
- [ ] Add Neo4j 5.x Community to `docker-compose.yml`
  - Port 7687 (Bolt), 7474 (HTTP browser)
  - Auth: neo4j/neo4j_password (configurable via env)
  - Volume for data persistence
  - Healthcheck via cypher-shell
- [ ] Add `neo4j>=5.0` to `pyproject.toml` dependencies
- [ ] Add Neo4j config to `src/pam/common/config.py`:
  - `NEO4J_URI` (default: bolt://localhost:7687)
  - `NEO4J_USER` (default: neo4j)
  - `NEO4J_PASSWORD`
  - `NEO4J_DATABASE` (default: neo4j)
- [ ] Create `src/pam/common/graph.py` — async Neo4j driver wrapper
  - `GraphClient` class: connect, close, execute_read, execute_write
  - Connection pool management
  - Transaction helpers (read/write)

**3.1.2 — Schema Design & Constraints**
- [ ] Create `src/pam/graph/__init__.py` — new module
- [ ] Create `src/pam/graph/schema.py` — graph schema definition + initialization
  - Node types:
    - `(:Metric {name, formula, owner, data_source, confidence, segment_id})`
    - `(:Event {name, properties, trigger, confidence, segment_id})`
    - `(:KPI {metric, target_value, period, owner, confidence, segment_id})`
    - `(:Document {id, title, source_type, source_url})`
    - `(:Team {name})` — extracted from owner fields
    - `(:DataSource {name})` — extracted from data_source fields
  - Relationship types:
    - `(:Metric)-[:DEFINED_IN]->(:Document)`
    - `(:Metric)-[:SOURCED_FROM]->(:DataSource)`
    - `(:Metric)-[:OWNED_BY]->(:Team)`
    - `(:Metric)-[:DEPENDS_ON]->(:Metric)`
    - `(:KPI)-[:TARGETS]->(:Metric)`
    - `(:KPI)-[:OWNED_BY]->(:Team)`
    - `(:Event)-[:DEFINED_IN]->(:Document)`
    - `(:Event)-[:TRACKED_BY]->(:Metric)` — when events feed metrics
  - Temporal properties on edges: `{valid_from, valid_to, created_at, version}`
  - Uniqueness constraints: Metric.name, Event.name, Document.id, Team.name, DataSource.name
- [ ] Create schema initialization function (run on startup, idempotent)

**3.1.3 — Health Check & Integration**
- [ ] Add Neo4j health check to `/api/health` endpoint
- [ ] Add `GraphClient` to FastAPI dependency injection (`deps.py`)
- [ ] App lifecycle: connect on startup, close on shutdown (`main.py`)
- [ ] Tests: connection, schema creation, health check, CRUD basics

**Files to create**: `src/pam/common/graph.py`, `src/pam/graph/__init__.py`, `src/pam/graph/schema.py`
**Files to modify**: `docker-compose.yml`, `pyproject.toml`, `src/pam/common/config.py`, `src/pam/api/deps.py`, `src/pam/api/main.py`, `src/pam/api/routes/documents.py` (health)
**Tests**: `tests/test_common/test_graph.py`, `tests/test_graph/__init__.py`, `tests/test_graph/test_schema.py`

---

### Wave 2: Entity-to-Graph Pipeline
> Map Phase 2's extracted entities into Neo4j nodes and relationships.

#### Step 3.2 — Entity-to-Graph Pipeline `status: pending`

**3.2.1 — Entity-to-Node Mapper**
- [ ] Create `src/pam/graph/mapper.py` — maps ExtractedEntity → graph nodes
  - `EntityGraphMapper` class
  - `map_metric(entity) -> NodeData` — extract name, formula, owner, data_source
  - `map_event(entity) -> NodeData` — extract event_name, properties, trigger
  - `map_kpi(entity) -> NodeData` — extract metric, target_value, period, owner
  - Extract implicit nodes: Team (from owner), DataSource (from data_source)
  - Deduplication: merge entities with same name (keep highest confidence)

**3.2.2 — Relationship Extractor**
- [ ] Create `src/pam/graph/relationship_extractor.py` — LLM-assisted relationship extraction
  - Given a set of entities from the same document, identify relationships
  - Use Claude to analyze entity context and suggest relationships:
    - Metric → depends on → Metric (e.g., "Conversion Rate" depends on "Signups" and "Visits")
    - Event → tracked by → Metric (e.g., "signup_completed" feeds "DAU")
    - KPI → targets → Metric
  - Prompt template with entity context + available relationship types
  - Validate relationship endpoints exist before creating edges
  - Confidence score on each relationship

**3.2.3 — Graph Writer**
- [ ] Create `src/pam/graph/writer.py` — writes nodes + edges to Neo4j
  - `GraphWriter` class using `GraphClient`
  - `upsert_node(label, properties)` — MERGE on unique key
  - `upsert_relationship(from_node, rel_type, to_node, properties)` — MERGE
  - `create_temporal_edge(from_node, rel_type, to_node, valid_from)` — with timestamp
  - `close_temporal_edge(from_node, rel_type, to_node, valid_to)` — set end date
  - Batch operations for efficiency (UNWIND)
  - Transaction management (all-or-nothing per document)

**3.2.4 — Pipeline Integration**
- [ ] Create `src/pam/graph/pipeline.py` — orchestrates entity → graph flow
  - `GraphPipeline` class
  - `process_document(document_id)`:
    1. Fetch extracted entities for document from PostgreSQL
    2. Map entities to nodes via EntityGraphMapper
    3. Extract relationships via RelationshipExtractor
    4. Write all to Neo4j via GraphWriter
    5. Log results to sync_log
  - Called after entity extraction in ingestion pipeline
- [ ] Integrate into `src/pam/ingestion/pipeline.py` — add graph step after extraction
- [ ] Tests: mapper, relationship extraction, writer, pipeline integration

**Files to create**: `src/pam/graph/mapper.py`, `src/pam/graph/relationship_extractor.py`, `src/pam/graph/writer.py`, `src/pam/graph/pipeline.py`
**Files to modify**: `src/pam/ingestion/pipeline.py`
**Tests**: `tests/test_graph/test_mapper.py`, `tests/test_graph/test_relationship_extractor.py`, `tests/test_graph/test_writer.py`, `tests/test_graph/test_pipeline.py`

---

### Wave 3: Graph-Aware Retrieval
> Agent tools to query the knowledge graph.

#### Step 3.3 — Graph-Aware Retrieval `status: pending`

**3.3.1 — Graph Query Service**
- [ ] Create `src/pam/graph/query_service.py` — graph query interface
  - `GraphQueryService` class
  - `find_dependencies(entity_name) -> list[dict]` — "What depends on X?"
    - Traverses DEPENDS_ON edges (both directions)
    - Returns dependency chain with relationship metadata
  - `find_related(entity_name, max_depth=2) -> list[dict]` — all related entities
    - Multi-hop traversal up to configurable depth
    - Returns subgraph as nodes + edges
  - `get_entity_history(entity_name, since=None) -> list[dict]` — "What changed about X?"
    - Queries temporal edges (valid_from/valid_to)
    - Returns chronological changes with document provenance
  - `execute_cypher(query, params) -> list[dict]` — raw Cypher for flexibility
    - Read-only guard (reject MERGE, CREATE, DELETE, SET)
    - Row limit (configurable, default 100)

**3.3.2 — Agent Tool: `query_graph`**
- [ ] Add `query_graph` tool to `src/pam/agent/tools.py`
  - Input: `question` (natural language), `entity_name` (optional)
  - Agent provides question → tool translates to Cypher via template matching:
    - "depends on" → find_dependencies()
    - "related to" → find_related()
    - "changed since" → get_entity_history()
    - Custom Cypher for complex queries
  - Output: formatted results with entity names, relationships, temporal context
- [ ] Register tool in agent tool registry

**3.3.3 — Graph Context Injection**
- [ ] Enhance `search_knowledge` tool in `hybrid_search.py`
  - After retrieving segments, check if any mention entities in the graph
  - If so, inject graph context: "This metric depends on X, Y" as additional context
  - Configurable via `GRAPH_CONTEXT_ENABLED` (default: true)
- [ ] Tests: query service, agent tool, context injection

**Files to create**: `src/pam/graph/query_service.py`
**Files to modify**: `src/pam/agent/tools.py`, `src/pam/agent/agent.py`, `src/pam/retrieval/hybrid_search.py`, `src/pam/api/deps.py`, `src/pam/common/config.py`
**Tests**: `tests/test_graph/test_query_service.py`, `tests/test_agent/test_graph_tool.py`

---

### Wave 4: Change Detection & History
> Diff engine and temporal graph versioning.

#### Step 3.4 — Change Detection & History `status: pending`

**3.4.1 — Diff Engine**
- [ ] Create `src/pam/graph/diff_engine.py` — compare entities on re-ingestion
  - `DiffEngine` class
  - `diff_entities(old_entities, new_entities) -> list[EntityChange]`
    - Detect: added, removed, modified entities
    - For modified: identify which fields changed
  - `classify_change(change) -> ChangeType`
    - Types: definition_change, ownership_change, new_metric, deprecated_metric, target_update
  - Change represented as `EntityChange` dataclass:
    - entity_name, change_type, old_value, new_value, timestamp

**3.4.2 — Graph Edge Versioning**
- [ ] Enhance `GraphWriter` to handle versioning on re-ingestion:
  - When entity changes: close old edges (set valid_to), create new edges (valid_from=now)
  - When entity removed: close all edges (set valid_to)
  - When entity added: create new edges (valid_from=now)
  - Maintain version counter on nodes (increment on update)

**3.4.3 — Enhanced Change History**
- [ ] Enhance `get_change_history` agent tool to include graph-level changes
  - Query both sync_log (document changes) and graph temporal edges (entity changes)
  - Combine into unified timeline
  - "What changed about [metric] since [date]?" queries the graph
- [ ] Tests: diff engine, versioning, timeline queries

**Files to create**: `src/pam/graph/diff_engine.py`
**Files to modify**: `src/pam/graph/writer.py`, `src/pam/agent/tools.py`
**Tests**: `tests/test_graph/test_diff_engine.py`, `tests/test_graph/test_versioning.py`

---

### Wave 5: Frontend — Knowledge Graph Explorer
> Visual graph exploration in the web UI.

#### Step 3.5 — Frontend: Knowledge Graph Explorer `status: pending`

**3.5.1 — Backend API for Graph Data**
- [ ] Create `src/pam/api/routes/graph.py` — graph API endpoints
  - `GET /api/graph/entities` — list all graph entities (paginated)
  - `GET /api/graph/entity/{name}` — entity details + relationships
  - `GET /api/graph/subgraph?entity={name}&depth={n}` — subgraph for visualization
  - `GET /api/graph/timeline?entity={name}&since={date}` — entity change history
- [ ] Response models: `GraphNode`, `GraphEdge`, `GraphSubgraph`, `TimelineEntry`

**3.5.2 — Graph Visualization Component**
- [ ] Add `react-force-graph-2d` dependency to `web/package.json`
- [ ] Create `web/src/components/GraphExplorer.tsx`
  - Force-directed graph layout
  - Node types color-coded (Metric=blue, Event=green, KPI=orange, etc.)
  - Click node → show details sidebar
  - Hover edge → show relationship type and temporal info
  - Zoom/pan controls
  - Entity search bar (type-ahead)

**3.5.3 — Graph Page**
- [ ] Create `web/src/pages/GraphPage.tsx`
  - Full-page graph explorer
  - Search bar to find entities
  - Sidebar with entity details, relationships, history
  - Route: `/graph`
- [ ] Create `web/src/hooks/useGraph.ts`
  - Fetch entities, subgraph, timeline
  - State management for selected entity

**3.5.4 — Timeline View**
- [ ] Create `web/src/components/Timeline.tsx`
  - Chronological view of entity changes
  - Show what changed, when, and from which document
  - Visual diff (old value → new value)

**3.5.5 — Navigation & Integration**
- [ ] Add "Graph" link to navigation in `App.tsx`
- [ ] Link from AdminDashboard entity counts → Graph page
- [ ] Link from ChatPage citations → Graph explorer (when entity mentioned)
- [ ] Add graph API client functions to `web/src/api/client.ts`

**Files to create**: `src/pam/api/routes/graph.py`, `web/src/pages/GraphPage.tsx`, `web/src/components/GraphExplorer.tsx`, `web/src/components/Timeline.tsx`, `web/src/hooks/useGraph.ts`
**Files to modify**: `web/src/App.tsx`, `web/src/api/client.ts`, `web/package.json`
**Tests**: `tests/test_api/test_graph_routes.py`, `web/src/hooks/useGraph.test.ts`

---

## Errors Encountered
| Error | Resolution |
|-------|------------|
| *(none yet)* | |

---

## Key Decisions Log
| Decision | Rationale | Date |
|----------|-----------|------|
| Neo4j direct driver over Graphiti | Graphiti v0.27 still RC; we have our own extraction; more schema control | 2026-02-14 |
| neo4j Python driver v6.1 | Latest stable, full async support, matches project pattern | 2026-02-14 |
| react-force-graph-2d for visualization | Lightweight, React-native, good interactive exploration | 2026-02-14 |
| LLM-assisted relationship extraction | Complex relationships need semantic understanding | 2026-02-14 |
| Temporal edges (valid_from/valid_to) | Simple bi-temporal model without Graphiti overhead | 2026-02-14 |

---

## Verification Criteria
- [ ] All new features have unit tests (target: 450+ tests)
- [ ] Existing Phase 1+2 tests still pass (396 baseline)
- [ ] Docker Compose starts cleanly with Neo4j added
- [ ] Graph schema initializes idempotently
- [ ] Entity-to-graph pipeline runs on existing extracted entities
- [ ] Agent can answer graph-traversal questions ("What depends on X?")
- [ ] Change detection works on re-ingestion
- [ ] Frontend graph explorer renders and is interactive
- [ ] No regressions in retrieval quality
