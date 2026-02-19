# Phase 3 — Research Findings

## 1. Technology Evaluation

### Graphiti (by Zep AI) — REJECTED for Phase 3
- **Latest version**: v0.27.0rc2 (Feb 5, 2026) — still release candidate
- **What it does**: Full temporal knowledge graph framework on Neo4j
  - Bi-temporal model (valid_from/valid_to on all edges)
  - Entity extraction, relationship mapping, community detection
  - Hybrid retrieval (semantic + keyword + graph traversal)
- **Why rejected**:
  - Still in RC, not production-stable
  - We already have our own entity extraction pipeline (Phase 2)
  - Opinionated schema that may conflict with our domain model
  - Heavy dependency for what we need (temporal edges + Cypher queries)
- **Source**: [graphiti-core on PyPI](https://pypi.org/project/graphiti-core/), [GitHub](https://github.com/getzep/graphiti)

### Neo4j Python Driver v6.1 — SELECTED
- **Latest version**: 6.1.0 (Jan 12, 2026) — stable release
- **Key features**:
  - Full async support via `AsyncGraphDatabase.driver()`
  - Python >= 3.10 required (our project uses 3.12+)
  - Connection pooling built-in
  - Bolt protocol for efficient binary transport
- **Package**: `neo4j` (NOT `neo4j-driver`, which is deprecated)
- **Source**: [neo4j on PyPI](https://pypi.org/project/neo4j/), [Async API docs](https://neo4j.com/docs/api/python-driver/current/async_api.html)

### Neo4j Community Edition 5.x — SELECTED for Docker
- Compatible with driver v6.1
- Free, no enterprise features needed
- Supports constraints, indexes, APOC (if needed)

### react-force-graph-2d — SELECTED for Frontend
- Lightweight React wrapper around d3-force
- Perfect for interactive entity relationship visualization
- Better React integration than raw D3.js or vis.js

---

## 2. Current Entity Foundation (Phase 2 Output)

### Extraction Schemas (`src/pam/ingestion/extractors/schemas.py`)
Three entity types already extracted from documents:

| Entity Type | Key Fields | Graph Node Label |
|------------|-----------|-----------------|
| MetricDefinition | name, formula, owner, data_source | `:Metric` |
| EventTrackingSpec | event_name, properties, trigger | `:Event` |
| KPITarget | metric, target_value, period, owner | `:KPI` |

### Storage (`extracted_entities` table)
- `entity_type`: string enum
- `entity_data`: JSONB (serialized Pydantic model)
- `confidence`: float 0.0–1.0
- `source_segment_id`: FK to segments (SET NULL on delete)
- `source_text`: first 500 chars for context

### Existing Agent Tool
- `search_entities` tool: query by type + search term, returns top 10 by confidence

---

## 3. Graph Schema Design

### Node Types (6)
```
(:Metric {name, formula, owner, data_source, confidence, segment_id, created_at, version})
(:Event {name, properties, trigger, confidence, segment_id, created_at, version})
(:KPI {metric, target_value, period, owner, confidence, segment_id, created_at, version})
(:Document {id, title, source_type, source_url})
(:Team {name})
(:DataSource {name})
```

### Relationship Types (8)
```
(:Metric)-[:DEFINED_IN {valid_from, valid_to}]->(:Document)
(:Metric)-[:SOURCED_FROM {valid_from, valid_to}]->(:DataSource)
(:Metric)-[:OWNED_BY {valid_from, valid_to}]->(:Team)
(:Metric)-[:DEPENDS_ON {valid_from, valid_to, confidence}]->(:Metric)
(:KPI)-[:TARGETS {valid_from, valid_to}]->(:Metric)
(:KPI)-[:OWNED_BY {valid_from, valid_to}]->(:Team)
(:Event)-[:DEFINED_IN {valid_from, valid_to}]->(:Document)
(:Event)-[:TRACKED_BY {valid_from, valid_to, confidence}]->(:Metric)
```

### Uniqueness Constraints
- `Metric.name` — globally unique
- `Event.name` — globally unique
- `Document.id` — maps to PostgreSQL document UUID
- `Team.name` — deduped from owner fields
- `DataSource.name` — deduped from data_source fields

### Design Rationale
- **Implicit nodes** (Team, DataSource) extracted from entity fields — provides richer graph without extra extraction step
- **Temporal edges** with valid_from/valid_to — enables "what changed" queries without full Graphiti
- **Version counter** on entity nodes — tracks how many times an entity has been updated
- **Confidence on relationship edges** — only for LLM-inferred relationships (DEPENDS_ON, TRACKED_BY)

---

## 4. Codebase Integration Points

### Ingestion Pipeline (`src/pam/ingestion/pipeline.py`)
Current flow: Connector → Parser → Chunker → Embedder → Store
New flow: Connector → Parser → Chunker → Embedder → Store → **Extract Entities** → **Build Graph**

### Agent (`src/pam/agent/agent.py`)
Current tools: search_knowledge, get_document_context, get_change_history, query_database, search_entities
New tool: **query_graph** (for relationship and temporal queries)

### Config (`src/pam/common/config.py`)
New settings needed:
- `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`
- `GRAPH_CONTEXT_ENABLED` (default: true)

### Docker Compose (`docker-compose.yml`)
Current services: postgres, elasticsearch, redis
New service: **neo4j** (Community 5.x)

---

## 5. Test Strategy

### Mocking Strategy for Neo4j
- Mock `GraphClient` (our wrapper) rather than the Neo4j driver directly
- Use `AsyncMock` for all async graph operations
- Test Cypher query generation separately from execution
- Integration tests (if needed) against Neo4j testcontainers

### Test Distribution Target
| Wave | Component | Estimated Tests |
|------|-----------|----------------|
| 1 | Neo4j Setup | 12-15 |
| 2 | Entity-to-Graph Pipeline | 20-25 |
| 3 | Graph-Aware Retrieval | 15-18 |
| 4 | Change Detection | 10-12 |
| 5 | Frontend + API Routes | 8-10 |
| **Total** | | **65-80 new tests** |

Target: **460-475 total tests** (396 baseline + ~70 new)

---

## 6. Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|-----------|
| LLM relationship extraction hallucinations | Medium | Validate endpoints exist; confidence threshold; human review |
| Neo4j Docker startup time | Low | Healthcheck with retry; separate from fast tests |
| Graph query performance at scale | Low-Medium | Indexes on frequently queried properties; limit traversal depth |
| Circular dependencies in graph | Medium | Detect cycles in DEPENDS_ON; warn but allow (real metrics can be circular) |
| Entity name deduplication across documents | Medium | Fuzzy matching on names; LLM-assisted disambiguation |
