# Requirements: PAM Context — Knowledge Graph & Temporal Reasoning

**Defined:** 2026-02-19
**Core Value:** Users can ask natural-language questions about their business documents and get accurate, cited answers from a Claude agent that searches across all ingested knowledge — now including entity relationships and temporal reasoning.

## v2.0 Requirements

Requirements for the Knowledge Graph milestone. Each maps to roadmap phases.

### Infrastructure

- [x] **INFRA-01**: Neo4j 5.26+ Community runs in Docker Compose with explicit memory config and health check
- [x] **INFRA-02**: graphiti-core[anthropic] installed with Anthropic LLM + OpenAI embedder configured
- [x] **INFRA-03**: GraphitiService singleton created in FastAPI lifespan and stored on app.state
- [x] **INFRA-04**: get_graph_service() dependency function in deps.py with cast() typing
- [x] **INFRA-05**: Entity type taxonomy defined as bounded Pydantic models (<=10 types) in config
- [x] **INFRA-06**: @neo4j-nvl/react, @neo4j-nvl/base, @neo4j-nvl/interaction-handlers installed in web/

### Entity Extraction

- [x] **EXTRACT-01**: Ingestion pipeline calls add_episode() (never add_episode_bulk) after PG commit for each segment
- [x] **EXTRACT-02**: Entity nodes and relationship edges created in Neo4j with bi-temporal timestamps sourced from document modified_at
- [x] **EXTRACT-03**: graph_synced boolean added to PG documents table via Alembic migration
- [x] **EXTRACT-04**: Graph extraction runs as background step — failure never rolls back PG/ES data
- [x] **EXTRACT-05**: Reconciliation endpoint /ingest/sync-graph retries documents with graph_synced=False
- [x] **EXTRACT-06**: Orphan node prevention via group_id-scoped episode tombstoning before re-ingestion

### Graph Querying

- [ ] **GRAPH-01**: search_knowledge_graph agent tool for relationship queries ("what depends on X?")
- [ ] **GRAPH-02**: get_entity_history agent tool for temporal queries ("how has X changed since Y?")
- [ ] **GRAPH-03**: Point-in-time graph query via reference_time parameter ("what did we believe in Q3?")
- [x] **GRAPH-04**: REST endpoint GET /api/graph/neighborhood/{entity} returning nodes + edges for 1-hop subgraph
- [x] **GRAPH-05**: REST endpoint GET /api/graph/entities listing all entity nodes with type and name
- [x] **GRAPH-06**: Tool result size hard-capped at 3000 chars with <=20 nodes per response

### Change Detection

- [x] **DIFF-01**: Diff engine detects entity-level changes on re-ingestion (added/modified/removed entities)
- [x] **DIFF-02**: Superseded edges have t_invalid set via Graphiti conflict resolution
- [x] **DIFF-03**: Entity-level diff summaries written to SyncLog.details as structured JSON

### Visualization

- [ ] **VIZ-01**: Graph explorer using InteractiveNvlWrapper as collapsible side panel with neighborhood view
- [ ] **VIZ-02**: Entity click expands detail panel showing properties, relationships, and temporal history
- [ ] **VIZ-03**: Temporal timeline component showing t_valid/t_invalid edge history for selected entity
- [ ] **VIZ-04**: Ingestion graph preview showing entities added/changed/invalidated per ingestion run
- [ ] **VIZ-05**: VITE_GRAPH_ENABLED env flag gates the graph explorer UI
- [ ] **VIZ-06**: "Graph indexing in progress" state when graph_synced count is 0

## v3 Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Advanced Graph

- **ADV-01**: Multi-hop Cypher traversal templates for complex relationship chains
- **ADV-02**: Full "As-of" chat mode with date picker UI for temporal navigation
- **ADV-03**: Entity confidence audit UI showing extraction quality scores
- **ADV-04**: Graph schema management UI for editing entity type taxonomy

## Out of Scope

| Feature | Reason |
|---------|--------|
| Full Cypher query interface for end users | Security surface + Cypher learning curve; agent tool is the user interface |
| Schema-free entity extraction | Entity type explosion — graph becomes unqueryable within 20 documents |
| Replacing ES/PG search with Neo4j search | They are complementary (ES for semantic similarity, Neo4j for relationships) |
| Neo4j Enterprise Edition | Community Edition sufficient for single-node; Enterprise adds clustering/security not needed now |
| `add_episode_bulk()` for any ingestion | Silently skips temporal invalidation; contradictory facts cannot be fixed without full graph rebuild |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| INFRA-01 | Phase 6 | Complete |
| INFRA-02 | Phase 6 | Complete |
| INFRA-03 | Phase 6 | Complete |
| INFRA-04 | Phase 6 | Complete |
| INFRA-05 | Phase 6 | Complete |
| INFRA-06 | Phase 6 | Complete |
| EXTRACT-01 | Phase 7 | Complete |
| EXTRACT-02 | Phase 7 | Complete |
| EXTRACT-03 | Phase 7 | Complete |
| EXTRACT-04 | Phase 7 | Complete |
| EXTRACT-05 | Phase 7 | Complete |
| EXTRACT-06 | Phase 7 | Complete |
| GRAPH-01 | Phase 8 | Pending |
| GRAPH-02 | Phase 8 | Pending |
| GRAPH-03 | Phase 8 | Pending |
| GRAPH-04 | Phase 8 | Complete |
| GRAPH-05 | Phase 8 | Complete |
| GRAPH-06 | Phase 8 | Complete |
| DIFF-01 | Phase 7 | Complete |
| DIFF-02 | Phase 7 | Complete |
| DIFF-03 | Phase 7 | Complete |
| VIZ-01 | Phase 9 | Pending |
| VIZ-02 | Phase 9 | Pending |
| VIZ-03 | Phase 9 | Pending |
| VIZ-04 | Phase 9 | Pending |
| VIZ-05 | Phase 9 | Pending |
| VIZ-06 | Phase 9 | Pending |

**Coverage:**
- v2.0 requirements: 27 total
- Mapped to phases: 27
- Unmapped: 0

---
*Requirements defined: 2026-02-19*
*Last updated: 2026-02-19 after phase 6 completion*
