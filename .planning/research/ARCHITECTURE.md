# Architecture Patterns: Knowledge Graph & Temporal Reasoning Milestone

**Domain:** Knowledge graph integration into existing RAG + FastAPI system
**Researched:** 2026-02-19
**Confidence:** HIGH (codebase read directly; Graphiti and Neo4j NVL verified via official docs + PyPI)

---

## Recommended Architecture

This milestone adds a **graph layer alongside** the existing vector+BM25 layer — not replacing it. The existing `HybridSearchService` (ES) continues to handle segment-level retrieval. Neo4j + Graphiti handle entity-relationship retrieval with bi-temporal semantics. The agent gains a new `search_knowledge_graph` tool that queries facts from the graph.

### High-Level System After Milestone

```
                     ┌─────────────────────────────────┐
                     │          FastAPI (main.py)       │
                     │   lifespan initializes all       │
                     │   services on app.state          │
                     └──────────────┬──────────────────┘
                                    │
           ┌────────────────────────┼──────────────────────┐
           │                        │                      │
           ▼                        ▼                      ▼
  ┌─────────────────┐   ┌──────────────────────┐  ┌───────────────────┐
  │ HybridSearch    │   │  GraphitiService      │  │  RetrievalAgent   │
  │ (ES RRF)        │   │  (NEW)                │  │  (extended)       │
  │ segment retrieval│  │  wraps Graphiti class │  │  +search_graph    │
  └────────┬────────┘   └──────────┬───────────┘  └─────────┬─────────┘
           │                       │                         │
           ▼                       ▼                         ▼
  ┌─────────────────┐   ┌──────────────────────┐  ┌───────────────────┐
  │ Elasticsearch   │   │  Neo4j 5.26+         │  │  Anthropic SDK    │
  │ (unchanged)     │   │  (NEW docker service) │  │  (unchanged)      │
  └─────────────────┘   └──────────┬───────────┘  └───────────────────┘
                                   │
                         ┌─────────┴──────────┐
                         │                    │
                         ▼                    ▼
                  EntityNode            EntityEdge
                  (entities)         (facts + t_valid,
                                       t_invalid)

Ingestion pipeline (modified):
  connector → parser → chunker → embedder → PG+ES (unchanged)
                                         ↘
                                    GraphitiEntityExtractor (NEW)
                                    → graphiti.add_episode()
                                    → Neo4j ← graph update
```

---

## Component Boundaries

### New Components

| Component | Location | Responsibility | Communicates With |
|-----------|----------|----------------|-------------------|
| `GraphitiService` | `src/pam/graph/graphiti_service.py` | Wraps `graphiti_core.Graphiti`; lifecycle management; add_episode, search | Neo4j driver (via Graphiti), OpenAI (embeddings), Anthropic (LLM) |
| `GraphEntityExtractor` | `src/pam/graph/entity_extractor.py` | Bridges ingestion pipeline → Graphiti; converts KnowledgeSegment + raw doc into episodes | `GraphitiService` |
| `GraphDiffEngine` | `src/pam/graph/diff_engine.py` | Detects entity/edge changes between ingestion runs; uses Graphiti's temporal invalidation | `GraphitiService`, PG `SyncLog` |
| `graph` route module | `src/pam/api/routes/graph.py` | REST endpoints: GET /graph/nodes, GET /graph/edges, GET /graph/subgraph/{entity_id} | `GraphitiService`, `get_graph_service` dep |
| GraphExplorer component | `web/src/components/graph/GraphExplorer.tsx` | `@neo4j-nvl/react` `InteractiveNvlWrapper` rendering | `/api/graph/*` endpoints |
| Graph API hooks | `web/src/hooks/useGraph.ts` | Fetches graph data, adapts API response to NVL node/rel format | `/api/graph/*` endpoints |

### Existing Components Modified

| Component | What Changes | Why |
|-----------|-------------|-----|
| `src/pam/api/main.py` | Add `GraphitiService` init/close in lifespan | Needs lifecycle management (Neo4j bolt connection) |
| `src/pam/api/deps.py` | Add `get_graph_service(request)` dependency | Stateless accessor matching existing pattern |
| `src/pam/common/config.py` | Add `neo4j_uri`, `neo4j_user`, `neo4j_password`, `graph_enabled` settings | Configuration without breaking existing settings |
| `src/pam/ingestion/pipeline.py` | Add optional graph extraction step (step 9) after PG commit | Graphiti extraction is expensive; runs after PG commit so failures don't roll back |
| `src/pam/agent/agent.py` | Add `graph_service` constructor param; add `search_knowledge_graph` tool dispatch | New tool for graph-aware retrieval |
| `src/pam/agent/tools.py` | Add `SEARCH_KNOWLEDGE_GRAPH_TOOL` definition | Exposes new tool to Claude |
| `src/pam/api/routes/ingest.py` | Pass `graph_service` to `spawn_ingestion_task` | Background task needs graph service reference |
| `src/pam/ingestion/task_manager.py` | Accept optional `graph_service` param; pass to pipeline | Background task wiring |
| `docker-compose.yml` | Add `neo4j` service | Infrastructure |
| `pyproject.toml` | Add `graphiti-core[anthropic]` dependency | Python package |

### Existing Components Unchanged

- `HybridSearchService`, `HaystackSearchService` — ES retrieval unchanged
- `ElasticsearchStore`, `PostgresStore` — storage unchanged
- `DoclingParser`, `HybridChunker` — document processing unchanged
- `OpenAIEmbedder` — still used for ES embeddings (Graphiti uses its own)
- Existing `ExtractedEntity` table in PG — still used by `search_entities` tool (flat entity store for metrics/KPIs)
- All existing API routes (chat, documents, search, auth, admin) — unchanged
- Alembic migrations for PG — no new PG tables needed (graph lives in Neo4j)
- Frontend chat, document list, search UI — unchanged

---

## Data Flow Changes

### Ingestion Pipeline (Modified)

```
Before (steps 1-10 unchanged):
  1. connector.fetch_document()
  2. content hash check
  3. docling_parser.parse()
  4. chunk_document()
  5. embedder.embed_texts_with_cache()
  6. build KnowledgeSegment objects
  7. pg_store.upsert_document() + save_segments()
  8. pg_store.log_sync()
  9. session.commit()
  10. es_store.delete_by_document() + bulk_index()

After — add step 11 (conditional):
  11. if graph_enabled and graph_service:
        await graph_service.ingest_document_episodes(
            source_id=source_id,
            title=raw_doc.title,
            segments=segments,
            reference_time=now(),
        )
      # failure here logs an error but does NOT rollback PG/ES
```

**Why after commit:** Graphiti `add_episode()` is expensive (multiple LLM calls for entity extraction, deduplication, temporal invalidation). PG is authoritative. A graph extraction failure should never cause data loss in the primary store.

**Episode structure per document:** One episode per chunked segment (not per document). This gives Graphiti fine-grained provenance and lets it invalidate individual facts when a section changes.

```python
await graphiti.add_episode(
    name=f"{source_id}::{segment.position}",
    episode_body=segment.content,
    source=EpisodeType.text,
    source_description=f"PAM document: {title}",
    reference_time=ingestion_timestamp,
    group_id=source_id,  # isolates per document for targeted re-ingestion
    entity_types=PAM_ENTITY_TYPES,   # Pydantic schemas
    edge_types=PAM_EDGE_TYPES,
    edge_type_map=PAM_EDGE_TYPE_MAP,
)
```

### Agent Tool Call Flow (New Tool)

```
User: "How has our MRR definition changed over time?"
  → Claude selects search_knowledge_graph tool
  → agent._search_knowledge_graph({"query": "MRR definition", "include_history": true})
    → graph_service.search(query, center_node_uuid=None)
    → graphiti.search(query) → List[EntityEdge]
    → format facts with t_valid/t_invalid timestamps
  → Claude receives: facts with temporal validity periods
  → Claude synthesizes temporal narrative in answer
```

### Change Detection / Diff Flow

The change detection engine hooks into re-ingestion. When a document is re-ingested (content hash changed), the pipeline calls `GraphDiffEngine.diff_document()` which:

1. Retrieves current active edges for `group_id=source_id` from Neo4j
2. Calls `add_episode()` with new segment content — Graphiti's built-in invalidation LLM call handles edge-level conflicts automatically (sets `t_invalid` on contradicted edges)
3. Queries edges with `t_invalid` set after the ingestion timestamp — these are the "changed facts"
4. Writes a diff summary to `SyncLog.details` (JSONB) — already exists in PG schema

This design **delegates temporal conflict resolution to Graphiti** rather than building a custom diff algorithm. Graphiti's invalidation prompt already handles "was X, now Y" semantics correctly.

---

## Patterns to Follow

### Pattern 1: GraphitiService as app.state Singleton

**What:** Initialize one `Graphiti` instance in lifespan, store on `app.state.graph_service`, expose via `get_graph_service(request)` dependency — identical to how `es_client`, `embedder`, and `search_service` are handled today.

**Why:** The `Graphiti` class holds a Neo4j driver (bolt connection pool) and LLM clients. Creating it per-request is prohibitively expensive. The existing `app.state` singleton pattern (already used for `es_client`, `embedder`, `search_service`) is the correct FastAPI pattern.

```python
# main.py lifespan addition
if settings.graph_enabled:
    from pam.graph.graphiti_service import GraphitiService
    graph_service = GraphitiService(
        neo4j_uri=settings.neo4j_uri,
        neo4j_user=settings.neo4j_user,
        neo4j_password=settings.neo4j_password,
        anthropic_api_key=settings.anthropic_api_key,
        openai_api_key=settings.openai_api_key,
    )
    await graph_service.initialize()  # builds indices + constraints
    app.state.graph_service = graph_service
else:
    app.state.graph_service = None

# lifespan shutdown:
if app.state.graph_service:
    await app.state.graph_service.close()
```

```python
# deps.py addition (stateless, matches existing pattern)
def get_graph_service(request: Request) -> "GraphitiService | None":
    return cast("GraphitiService | None", request.app.state.graph_service)
```

### Pattern 2: Anthropic + OpenAI Split in Graphiti

**What:** Configure Graphiti with `AnthropicClient` for entity extraction LLM calls but `OpenAIEmbedder` for graph embeddings. OpenAI embeddings in Graphiti are independent from the project's existing `OpenAIEmbedder` — Graphiti manages its own embedder instance internally.

**Why:** Graphiti requires OpenAI for embeddings even when using Anthropic for LLM inference. The existing project already has `settings.openai_api_key` and `settings.anthropic_api_key`.

```python
# GraphitiService initialization
from graphiti_core import Graphiti
from graphiti_core.llm_client.anthropic_client import AnthropicClient, LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder as GraphitiEmbedder, OpenAIEmbedderConfig

graphiti = Graphiti(
    neo4j_uri, neo4j_user, neo4j_password,
    llm_client=AnthropicClient(
        config=LLMConfig(
            api_key=anthropic_api_key,
            model="claude-sonnet-4-20250514",
            small_model="claude-3-5-haiku-20241022",
        )
    ),
    embedder=GraphitiEmbedder(
        config=OpenAIEmbedderConfig(
            api_key=openai_api_key,
            embedding_model="text-embedding-3-small",  # Graphiti's own embedding
        )
    ),
)
```

### Pattern 3: PAM-Specific Entity Types as Pydantic Models

**What:** Define domain-specific entity and edge types as Pydantic models extending Graphiti's schema, passed to `add_episode()` as `entity_types` dict.

**Why:** The existing `ExtractedEntity` table stores flat JSONB. Graphiti's graph entities require typed Pydantic schemas for the LLM extraction prompt. The schemas should mirror the business domain already established in `src/pam/ingestion/extractors/schemas.py`.

```python
# src/pam/graph/pam_entity_types.py
from pydantic import BaseModel, Field
from typing import Optional

class Metric(BaseModel):
    """A business metric with formula and ownership."""
    formula: Optional[str] = Field(None, description="Calculation formula")
    owner_team: Optional[str] = Field(None, description="Owning team")
    data_source: Optional[str] = Field(None, description="Source system")

class KPITarget(BaseModel):
    """A measurable target for a metric."""
    target_value: Optional[str] = Field(None, description="Numeric or percentage target")
    period: Optional[str] = Field(None, description="Time period e.g. Q1 2025")

class Process(BaseModel):
    """A business process or workflow."""
    owner_team: Optional[str] = Field(None)
    frequency: Optional[str] = Field(None)

PAM_ENTITY_TYPES = {
    "Metric": Metric,
    "KPITarget": KPITarget,
    "Process": Process,
    "Team": None,  # None = use default EntityNode (name only)
    "System": None,
}
```

### Pattern 4: group_id for Document Isolation

**What:** Use Graphiti's `group_id` parameter set to the PAM `source_id` (document path or Google Doc ID) when calling `add_episode()`.

**Why:** `group_id` partitions graph data so re-ingesting a single document only conflicts with that document's existing edges. Without this, temporal invalidation would compare a new segment's facts against all knowledge in the graph, causing spurious conflicts.

### Pattern 5: New Agent Tool Following Existing Dispatch Pattern

**What:** Add `search_knowledge_graph` to `ALL_TOOLS` in `tools.py` and add a `graph_service` optional dependency to `RetrievalAgent.__init__()`. Dispatch in `_execute_tool()` matches the existing pattern for all five current tools.

**Why:** The agent tool loop in `agent.py` is already extensible — `_execute_tool()` is a simple if/elif dispatch. Adding a new branch for `search_knowledge_graph` follows the established pattern with no architectural changes required.

```python
# agent/tools.py addition
SEARCH_KNOWLEDGE_GRAPH_TOOL = {
    "name": "search_knowledge_graph",
    "description": (
        "Search the knowledge graph for entity relationships and facts. "
        "Returns structured facts with temporal validity (when they were true). "
        "Use this for: entity relationships, historical changes, 'how has X changed', "
        "'what team owns Y', 'what is the relationship between A and B'."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language question about entities and relationships.",
            },
            "include_history": {
                "type": "boolean",
                "description": "Include invalidated (historical) facts. Default false.",
                "default": False,
            },
        },
        "required": ["query"],
    },
}
```

```python
# agent.py RetrievalAgent modifications
class RetrievalAgent:
    def __init__(
        self,
        search_service: SearchService,
        embedder: BaseEmbedder,
        api_key: str,
        model: str,
        cost_tracker: CostTracker | None = None,
        db_session: AsyncSession | None = None,
        duckdb_service: DuckDBService | None = None,
        graph_service: GraphitiService | None = None,  # NEW, optional
    ) -> None:
        ...
        self.graph_service = graph_service  # None = tool returns "not configured"

    async def _execute_tool(self, tool_name: str, tool_input: dict):
        ...
        if tool_name == "search_knowledge_graph":
            return await self._search_knowledge_graph(tool_input)
        ...

    async def _search_knowledge_graph(self, input_: dict) -> tuple[str, list[Citation]]:
        if not self.graph_service:
            return "Knowledge graph not configured.", []
        query = input_["query"]
        include_history = input_.get("include_history", False)
        facts = await self.graph_service.search_facts(query, include_invalidated=include_history)
        # format EntityEdge results with validity timestamps
        ...
```

### Pattern 6: NVL React Component as Sidebar/Panel

**What:** Add a `GraphExplorer` React component using `@neo4j-nvl/react` `InteractiveNvlWrapper`. Render it as a collapsible side panel in the existing layout, not a separate page.

**Why:** The existing frontend uses React Router with a layout pattern. A side panel keeps the graph explorer contextual to the current chat/document without requiring navigation. NVL's `InteractiveNvlWrapper` provides pan/zoom/click interactions out of the box.

```typescript
// web/src/components/graph/GraphExplorer.tsx
import { InteractiveNvlWrapper } from '@neo4j-nvl/react'
import type { Node, Relationship } from '@neo4j-nvl/base'

interface GraphExplorerProps {
  entityQuery?: string   // pre-populate from chat context
}

export function GraphExplorer({ entityQuery }: GraphExplorerProps) {
  const { nodes, rels, isLoading } = useGraph(entityQuery)
  return (
    <InteractiveNvlWrapper
      nodes={nodes}
      rels={rels}
      mouseEventCallbacks={{
        onNodeClick: handleNodeClick,
        onNodeDoubleClick: handleExpand,
      }}
    />
  )
}
```

```typescript
// web/src/hooks/useGraph.ts
// Fetches /api/graph/subgraph?query=... and adapts to NVL format
// NVL Node: { id: string, captions: [{value: string}], color: string }
// NVL Rel: { id: string, from: string, to: string, captions: [{value: string}] }
```

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: One Episode Per Full Document

**What:** Calling `graphiti.add_episode(episode_body=full_document_content)` with the entire document as one episode.

**Why bad:** Graphiti's entity extraction runs LLM calls proportional to content length. Full documents will hit token limits, produce inaccurate extraction, and slow ingestion. The bi-temporal tracking granularity is also too coarse — a section change invalidates the entire document's edges.

**Instead:** One episode per `KnowledgeSegment` (chunked). Use `group_id=source_id` to logically group episodes from the same document.

### Anti-Pattern 2: Creating Graphiti Instance Per Request

**What:** Initializing `Graphiti(...)` inside `get_agent()` in `deps.py`.

**Why bad:** `Graphiti.__init__()` creates a Neo4j bolt driver connection pool and instantiates LLM clients. This is a heavyweight operation that would dominate request latency.

**Instead:** Single `GraphitiService` instance on `app.state`, initialized in lifespan, closed in shutdown.

### Anti-Pattern 3: Blocking the Ingestion Pipeline on Graph Extraction

**What:** Putting `await graphiti.add_episode()` inside the PG transaction (before `session.commit()`).

**Why bad:** Each `add_episode()` call makes 4-8 LLM calls for entity extraction, deduplication, and temporal invalidation. A document with 20 segments would make 80-160 LLM calls before PG commits. This creates a catastrophically long transaction window and makes PG the bottleneck.

**Instead:** Graph extraction runs after `session.commit()` (step 11 in the pipeline). A graph failure logs an error but never rolls back PG data. The PG data is always authoritative.

### Anti-Pattern 4: Replacing ExtractedEntity with Graph Only

**What:** Removing the existing `ExtractedEntity` PG table and routing `search_entities` tool calls to Neo4j instead.

**Why bad:** The PG entity table stores structured business entities (metrics, events, KPIs) as searchable JSONB. It's fast, simple, and proven. The knowledge graph serves a different purpose: capturing relationships and temporal changes between any entity types, including free-form ones the LLM discovers.

**Instead:** Both coexist. `search_entities` tool → PG `extracted_entities` (precise structured lookup). `search_knowledge_graph` tool → Neo4j (relationship discovery and temporal history). The agent uses both as needed.

### Anti-Pattern 5: Hardwiring NVL in Core Layout

**What:** Adding the graph explorer as a permanent fixture in the app shell layout.

**Why bad:** The graph explorer is only useful when there's graph data. Making it always visible wastes screen real estate and confuses users when `graph_enabled=false`.

**Instead:** Conditionally render based on `VITE_GRAPH_ENABLED` env variable or an API feature flag endpoint. Use a toggle button that reveals the explorer panel.

### Anti-Pattern 6: Sharing Graphiti's Internal Embedder with PAM's OpenAIEmbedder

**What:** Passing PAM's existing `OpenAIEmbedder` instance into Graphiti's constructor.

**Why bad:** Graphiti's `embedder` parameter accepts a `graphiti_core.embedder.openai.OpenAIEmbedder`, not PAM's `pam.ingestion.embedders.openai_embedder.OpenAIEmbedder`. These are different classes from different packages with different interfaces.

**Instead:** Let Graphiti manage its own embedder instance. Both use the same OpenAI API key but operate independently. This is two API clients to OpenAI, which is acceptable.

---

## Build Order

Build order is determined by dependency direction. Each stage can be tested independently before the next.

### Stage 1: Infrastructure (blocking everything else)

**Deliverables:**
- Add Neo4j 5.26 to `docker-compose.yml` with health check
- Add `graphiti-core[anthropic]>=0.28` to `pyproject.toml`
- Add `neo4j_uri`, `neo4j_user`, `neo4j_password`, `graph_enabled` to `config.py` Settings
- Add `@neo4j-nvl/react` and `@neo4j-nvl/base` to `web/package.json`

**Why first:** Nothing else can be built or tested without the graph database running and the Python package installed.

**Test:** `docker-compose up neo4j` + `from graphiti_core import Graphiti` imports without error.

### Stage 2: GraphitiService + Lifespan Wiring

**Deliverables:**
- `src/pam/graph/__init__.py`, `src/pam/graph/graphiti_service.py`
- `GraphitiService` class wrapping `Graphiti` with `initialize()`, `close()`, `add_episode_for_segment()`, `search_facts()`, `get_subgraph()`
- `src/pam/graph/pam_entity_types.py` — PAM-specific Pydantic entity schemas
- `main.py` lifespan: conditional `GraphitiService` init/close
- `deps.py`: `get_graph_service()` dependency function

**Why second:** This is the foundation all other components depend on. Agent tools, ingestion extension, and REST endpoints all need a working `GraphitiService`.

**Test:** Unit test `GraphitiService` with mocked `Graphiti` client. Integration test against running Neo4j.

### Stage 3: Ingestion Pipeline Extension

**Deliverables:**
- `src/pam/graph/entity_extractor.py` — `GraphEntityExtractor` bridges pipeline → Graphiti
- `src/pam/ingestion/pipeline.py` — add step 11 (graph extraction after commit)
- `src/pam/ingestion/task_manager.py` — accept `graph_service` param
- `src/pam/api/routes/ingest.py` — pass `graph_service` from `app.state` to task spawner

**Why third:** Depends on `GraphitiService` (Stage 2). The ingestion pipeline modification is independent of the agent and UI.

**Test:** Ingest a test markdown document; verify entities appear in Neo4j. Re-ingest a modified document; verify old facts are temporally invalidated.

### Stage 4: Change Detection / Diff Engine

**Deliverables:**
- `src/pam/graph/diff_engine.py` — `GraphDiffEngine` with `diff_document()` method
- Write changed fact summaries to `SyncLog.details` JSONB (no new PG schema changes)
- Extend `get_change_history` agent tool to optionally include graph diff data

**Why fourth:** Requires Neo4j to be populated (Stage 3) before meaningful diffs can be generated. Can be built and tested independently of the UI.

**Test:** Ingest v1 of a document → modify facts → re-ingest v2 → assert diff engine reports correct changed edges.

### Stage 5: Agent Graph Tool

**Deliverables:**
- `src/pam/agent/tools.py` — add `SEARCH_KNOWLEDGE_GRAPH_TOOL`
- `src/pam/agent/agent.py` — add `graph_service` param, `_search_knowledge_graph()` dispatch
- `src/pam/api/deps.py` — update `get_agent()` to pass `graph_service`
- Update `SYSTEM_PROMPT` to mention `search_knowledge_graph` tool

**Why fifth:** Requires `GraphitiService` (Stage 2) and working graph data (Stage 3). The agent tool is the primary user-facing integration point.

**Test:** End-to-end: ingest → ask "what team owns MRR?" → verify agent uses `search_knowledge_graph` tool and returns entity relationship from Neo4j.

### Stage 6: REST Graph Endpoints

**Deliverables:**
- `src/pam/api/routes/graph.py` — `GET /api/graph/nodes`, `GET /api/graph/edges`, `GET /api/graph/subgraph`
- Register router in `main.py`
- Pydantic response models for graph data

**Why sixth:** The REST endpoints are consumed by the frontend (Stage 7). They can be built independently of the UI and tested with curl.

**API shape:**
```
GET /api/graph/nodes?query=MRR&limit=20
  → [{ id, name, labels, attributes, created_at }]

GET /api/graph/subgraph?entity_id=<uuid>&depth=2
  → { nodes: [...], edges: [{id, from, to, fact, valid_at, invalid_at}] }

GET /api/graph/entities?entity_type=Metric&limit=50
  → paginated list of entity nodes
```

### Stage 7: Graph Explorer UI

**Deliverables:**
- `web/src/hooks/useGraph.ts` — React Query hook for graph API
- `web/src/components/graph/GraphExplorer.tsx` — `InteractiveNvlWrapper` component
- `web/src/components/graph/EntityPanel.tsx` — click-to-expand entity detail sidebar
- `web/src/components/graph/TemporalTimeline.tsx` — visualize t_valid/t_invalid periods
- Toggle button in main chat layout to show/hide graph panel

**Why last:** All backend work must be complete and the REST API must be returning valid data before the UI can be built meaningfully.

**Dependencies:** `@neo4j-nvl/react ^1.0.0`, `@neo4j-nvl/base ^1.0.0`

---

## Scalability Considerations

| Concern | At 100 docs (initial) | At 1K docs | At 10K docs |
|---------|----------------------|------------|-------------|
| Neo4j memory | 512MB sufficient | 2GB recommended | Dedicated instance, index tuning |
| Graphiti add_episode LLM cost | ~$0.05/segment (Claude Haiku) | Bulk ingestion adds up; consider async queue | Background worker process |
| Graph query latency | <300ms (Graphiti docs claim P95) | Acceptable with Neo4j indexes | May need Neo4j vector index tuning |
| NVL rendering | Fine for <500 nodes | Force-directed layout degrades | Limit subgraph depth to 2; paginate |
| Re-ingestion diff | O(edges in document group) | O(edges in document group), unaffected by total graph size | Same, group_id isolation prevents cross-document scan |

---

## Sources

- Codebase read directly (`src/pam/api/main.py`, `deps.py`, `agent/agent.py`, `ingestion/pipeline.py`, `common/models.py`, `common/config.py`, `ingestion/extractors/entity_extractor.py`) — HIGH confidence
- [Graphiti GitHub: getzep/graphiti](https://github.com/getzep/graphiti) — HIGH confidence
- [graphiti-core on PyPI (v0.28.0, released 2026-02-17)](https://pypi.org/project/graphiti-core/) — HIGH confidence
- [Graphiti Quick Start Documentation](https://help.getzep.com/graphiti/getting-started/quick-start) — HIGH confidence
- [Graphiti Custom Entity and Edge Types](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types) — HIGH confidence
- [Graphiti LLM Configuration — Anthropic](https://help.getzep.com/graphiti/configuration/llm-configuration) — HIGH confidence
- [Graphiti Core Client — DeepWiki](https://deepwiki.com/getzep/graphiti/4.1-graphiti-core) — MEDIUM confidence (community wiki)
- [Graphiti change detection and temporal invalidation](https://blog.getzep.com/beyond-static-knowledge-graphs/) — HIGH confidence
- [Zep Temporal Knowledge Graph paper (arxiv 2501.13956)](https://arxiv.org/abs/2501.13956) — HIGH confidence (peer-reviewed)
- [@neo4j-nvl/react npm package (v1.0.0)](https://www.npmjs.com/package/@neo4j-nvl/react) — HIGH confidence
- [NVL React Wrappers documentation](https://neo4j.com/docs/nvl/current/react-wrappers/) — HIGH confidence
- [Neo4j Python Driver Async API (v6.x)](https://neo4j.com/docs/api/python-driver/current/async_api.html) — HIGH confidence
- [Neo4j Docker Hub](https://hub.docker.com/_/neo4j) — HIGH confidence
