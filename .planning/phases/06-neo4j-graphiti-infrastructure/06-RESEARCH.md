# Phase 6: Neo4j + Graphiti Infrastructure - Research

**Researched:** 2026-02-20
**Domain:** Graph database infrastructure, temporal knowledge graph engine, graph visualization libraries
**Confidence:** HIGH

## Summary

This phase stands up the graph database layer (Neo4j), configures the temporal knowledge graph engine (Graphiti), defines entity type schemas as Pydantic models, and wires the service lifecycle into the existing FastAPI dependency injection patterns. It also installs the frontend graph visualization packages (NVL) with a placeholder page behind a feature flag.

The existing codebase follows a consistent pattern: services are created in the FastAPI lifespan context manager, stored on `app.state`, and accessed via `deps.py` functions that use `cast()` for type safety. The GraphitiService must follow this exact pattern. Neo4j 5.26+ is required (Graphiti minimum), and the APOC Core plugin must be installed. Graphiti v0.27.1 supports Anthropic LLM + OpenAI embedder, which aligns perfectly with the existing project's API key infrastructure.

The NVL packages (@neo4j-nvl/base, @neo4j-nvl/react, @neo4j-nvl/interaction-handlers) are all at v1.0.0. The frontend work is limited to installing packages, adding a feature-flagged `/graph` route with a placeholder status page, and creating a backend `GET /api/graph/status` endpoint.

**Primary recommendation:** Use Neo4j 5.26-community Docker image with APOC Core plugin, graphiti-core[anthropic] v0.27.x with AnthropicClient + OpenAIEmbedder, and wrap the Graphiti instance in a `GraphitiService` class following the existing singleton-on-app.state pattern.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Entity type taxonomy
- **7 entity types** for a game studio domain: Person, Team, Project, Technology, Process, Concept, Asset
- Person: employees, stakeholders, partners
- Team: departments, squads, project teams
- Project: game titles, internal tools, prototypes
- Technology: engines, SDKs, backend systems, analytics tools, platforms
- Process: workflows, pipelines, LiveOps procedures, analytics workflows
- Concept: game design ideas, mechanics, features
- Asset: art, audio, code asset types/categories
- Implemented as Pydantic models, importable from `src/pam/graph/`
- Documents about game design -> extract Concept + Project entities
- Documents about config/architecture -> extract Technology entities
- Documents about analytics/LiveOps -> extract Process + Technology entities

#### Episode modeling
- One Graphiti episode per **chunk** (not per document) -- finer-grained temporal tracking
- Bi-temporal timestamps: valid_time = document `modified_at`, transaction_time = ingestion time
- Re-ingestion uses **invalidate + replace**: old episode edges get `t_invalid` set, new episode creates fresh edges
- Full traceability: each episode stores `document_id` and `chunk_id` back-references

#### Graph availability policy
- **Hard dependency**: app won't start without Neo4j -- single `docker compose up` brings everything up
- Neo4j Community Edition
- Neo4j status included in existing `/health` endpoint alongside postgres and elasticsearch
- Docker volume: persistent by default, ephemeral via `--profile test`

#### NVL frontend prep
- Install `@neo4j-nvl` packages in web/ project
- Wire up `VITE_GRAPH_ENABLED` feature flag
- Add `/graph` route with placeholder component
- Feature flag behavior: nav item **visible but disabled** (grayed out with tooltip) when `VITE_GRAPH_ENABLED=false`
- Placeholder page shows **graph status summary**: Neo4j connection status + entity counts + last sync time
- New `GET /api/graph/status` backend endpoint (not reusing /health) -- returns Neo4j status, entity counts, last sync time

### Claude's Discretion
- Neo4j version selection and Docker image tag
- Graphiti client configuration details
- GraphitiService internal implementation
- Exact Pydantic model field definitions for entity types
- Frontend component structure and styling for placeholder page

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INFRA-01 | Neo4j 5.26+ Community runs in Docker Compose with explicit memory config and health check | Neo4j 5.26-community Docker image, APOC plugin via NEO4J_PLUGINS, cypher-shell health check, memory env vars documented |
| INFRA-02 | graphiti-core[anthropic] installed with Anthropic LLM + OpenAI embedder configured | graphiti-core v0.27.1 with [anthropic] extra, AnthropicClient + OpenAIEmbedder configuration pattern documented |
| INFRA-03 | GraphitiService singleton created in FastAPI lifespan and stored on app.state | Lifespan pattern from existing main.py, Graphiti constructor + build_indices_and_constraints + close lifecycle documented |
| INFRA-04 | get_graph_service() dependency function in deps.py with cast() typing | Existing cast() pattern in deps.py for all services, direct pattern to follow |
| INFRA-05 | Entity type taxonomy defined as bounded Pydantic models (<=10 types) in config | Graphiti custom entity type API: dict[str, type[BaseModel]], protected field names, Optional fields pattern |
| INFRA-06 | @neo4j-nvl/react, @neo4j-nvl/base, @neo4j-nvl/interaction-handlers installed in web/ | All three packages at v1.0.0, npm install command, BasicNvlWrapper/InteractiveNvlWrapper components |

</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| neo4j (Docker) | 5.26-community | Graph database | Graphiti minimum requirement; 5.26 is LTS; Community Edition sufficient for single-node |
| graphiti-core[anthropic] | 0.27.x | Temporal knowledge graph engine | Only mature Python library for bi-temporal knowledge graphs on Neo4j |
| neo4j (Python driver) | (transitive via graphiti-core) | Neo4j bolt protocol client | Installed automatically as graphiti-core dependency |
| @neo4j-nvl/base | 1.0.0 | Graph visualization core | Official Neo4j visualization library, framework-agnostic |
| @neo4j-nvl/react | 1.0.0 | React wrappers for NVL | Official React integration for NVL |
| @neo4j-nvl/interaction-handlers | 1.0.0 | Interaction handlers for graph | Click, drag, zoom, hover handlers for graph visualization |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| APOC Core (Neo4j plugin) | Auto-matched to Neo4j version | Graph procedures (required by Graphiti) | Always -- Graphiti requires APOC procedures |
| pydantic | >=2.0 (already installed) | Entity type schema definitions | Defining the 7 entity type models |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Neo4j 5.26 | Neo4j 2026.01.x | Newer but not yet required by Graphiti; 5.26 LTS is more stable and documented |
| graphiti-core | Manual Cypher + neo4j driver | Would require hand-rolling temporal logic, entity extraction, conflict resolution |
| @neo4j-nvl | vis.js, d3-force | NVL is purpose-built for Neo4j data shapes; vis.js/d3 require custom Neo4j adapters |

**Installation (Python):**
```bash
pip install "graphiti-core[anthropic]"
```

Or in pyproject.toml:
```toml
"graphiti-core[anthropic]>=0.27",
```

**Installation (Frontend):**
```bash
cd web && npm install @neo4j-nvl/base @neo4j-nvl/react @neo4j-nvl/interaction-handlers
```

## Architecture Patterns

### Recommended Project Structure

```
src/pam/
├── graph/                    # NEW: Graph module
│   ├── __init__.py          # Re-exports entity types + GraphitiService
│   ├── entity_types.py      # 7 Pydantic entity type models
│   ├── edge_types.py        # Edge type models (for future phases)
│   └── service.py           # GraphitiService wrapper class
├── api/
│   ├── main.py              # MODIFIED: Add Neo4j/Graphiti to lifespan + health check
│   ├── deps.py              # MODIFIED: Add get_graph_service()
│   └── routes/
│       └── graph.py         # NEW: GET /api/graph/status endpoint
└── common/
    └── config.py            # MODIFIED: Add Neo4j + Graphiti settings

web/src/
├── pages/
│   └── GraphPage.tsx        # NEW: Placeholder graph status page
├── api/
│   └── client.ts            # MODIFIED: Add getGraphStatus() function
└── App.tsx                  # MODIFIED: Add /graph route + nav item with feature flag
```

### Pattern 1: GraphitiService Singleton on app.state

**What:** Wrap the Graphiti client in a service class, create it during lifespan startup, store on `app.state`, access via dependency function.
**When to use:** Always -- follows the established pattern for ES client, search service, cache service, etc.

```python
# src/pam/graph/service.py
from graphiti_core import Graphiti
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.config import LLMConfig
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
import structlog

logger = structlog.get_logger()

class GraphitiService:
    """Wraps graphiti-core Graphiti client with application-specific configuration."""

    def __init__(self, client: Graphiti) -> None:
        self._client = client

    @classmethod
    async def create(
        cls,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        anthropic_api_key: str,
        openai_api_key: str,
        anthropic_model: str = "claude-sonnet-4-5-20250514",
        embedding_model: str = "text-embedding-3-small",
    ) -> "GraphitiService":
        """Factory method: creates Graphiti client, builds indices, returns service."""
        client = Graphiti(
            neo4j_uri,
            neo4j_user,
            neo4j_password,
            llm_client=AnthropicClient(
                config=LLMConfig(
                    api_key=anthropic_api_key,
                    model=anthropic_model,
                )
            ),
            embedder=OpenAIEmbedder(
                config=OpenAIEmbedderConfig(
                    api_key=openai_api_key,
                    embedding_model=embedding_model,
                )
            ),
        )
        await client.build_indices_and_constraints()
        logger.info("graphiti_initialized", neo4j_uri=neo4j_uri)
        return cls(client)

    @property
    def client(self) -> Graphiti:
        return self._client

    async def close(self) -> None:
        await self._client.close()
        logger.info("graphiti_closed")
```

### Pattern 2: Lifespan Integration

**What:** Create GraphitiService in the FastAPI lifespan, following the exact pattern used for ES, Redis, etc.
**When to use:** Always.

```python
# In src/pam/api/main.py lifespan()

# --- Graphiti / Neo4j ---
from pam.graph.service import GraphitiService

graph_service = await GraphitiService.create(
    neo4j_uri=settings.neo4j_uri,
    neo4j_user=settings.neo4j_user,
    neo4j_password=settings.neo4j_password,
    anthropic_api_key=settings.anthropic_api_key,
    openai_api_key=settings.openai_api_key,
    embedding_model=settings.embedding_model,
)
app.state.graph_service = graph_service

yield

# Shutdown
await graph_service.close()
```

### Pattern 3: Dependency Function with cast()

**What:** Add `get_graph_service()` to deps.py following the existing pattern.
**When to use:** Every route handler that needs graph access.

```python
# In src/pam/api/deps.py
from pam.graph.service import GraphitiService

def get_graph_service(request: Request) -> GraphitiService:
    return cast(GraphitiService, request.app.state.graph_service)
```

### Pattern 4: Entity Types as Graphiti-Compatible Dict

**What:** Define Pydantic models and export as the `dict[str, type[BaseModel]]` format Graphiti expects.
**When to use:** Passed to `add_episode()` in future phases (7+).

```python
# src/pam/graph/entity_types.py
from pydantic import BaseModel, Field
from typing import Optional

class Person(BaseModel):
    """An employee, stakeholder, or partner at the game studio."""
    role: Optional[str] = Field(None, description="Job title or role")
    department: Optional[str] = Field(None, description="Department or team affiliation")

class Team(BaseModel):
    """A department, squad, or project team."""
    team_type: Optional[str] = Field(None, description="Type: department, squad, project team")
    size: Optional[int] = Field(None, description="Number of team members")

class Project(BaseModel):
    """A game title, internal tool, or prototype."""
    project_type: Optional[str] = Field(None, description="Type: game, tool, prototype")
    status: Optional[str] = Field(None, description="Status: active, shipped, cancelled, prototype")
    platform: Optional[str] = Field(None, description="Target platform(s)")

class Technology(BaseModel):
    """An engine, SDK, backend system, analytics tool, or platform."""
    tech_category: Optional[str] = Field(None, description="Category: engine, SDK, backend, analytics, platform")
    version: Optional[str] = Field(None, description="Current version in use")

class Process(BaseModel):
    """A workflow, pipeline, LiveOps procedure, or analytics workflow."""
    process_type: Optional[str] = Field(None, description="Type: workflow, pipeline, procedure")
    frequency: Optional[str] = Field(None, description="Execution frequency: daily, weekly, on-demand")

class Concept(BaseModel):
    """A game design idea, mechanic, or feature."""
    concept_type: Optional[str] = Field(None, description="Type: mechanic, feature, design pattern")
    maturity: Optional[str] = Field(None, description="Maturity: idea, prototype, production")

class Asset(BaseModel):
    """An art, audio, or code asset type/category."""
    asset_type: Optional[str] = Field(None, description="Type: art, audio, code, shader, model")
    format: Optional[str] = Field(None, description="File format or standard")

# Graphiti-compatible entity type registry
ENTITY_TYPES: dict[str, type[BaseModel]] = {
    "Person": Person,
    "Team": Team,
    "Project": Project,
    "Technology": Technology,
    "Process": Process,
    "Concept": Concept,
    "Asset": Asset,
}
```

### Pattern 5: Docker Compose Neo4j Service

**What:** Add Neo4j as a service in docker-compose.yml alongside existing postgres, elasticsearch, redis.

```yaml
# In docker-compose.yml
  neo4j:
    image: neo4j:5.26-community
    environment:
      - NEO4J_AUTH=neo4j/pam_graph
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_server_memory_heap_initial__size=512m
      - NEO4J_server_memory_heap_max__size=1G
      - NEO4J_server_memory_pagecache_size=512m
    ports:
      - "7474:7474"
      - "7687:7687"
    volumes:
      - neo4jdata:/var/lib/neo4j/data
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "pam_graph", "RETURN 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

volumes:
  neo4jdata:
```

### Pattern 6: Feature-Flagged Nav Item

**What:** Graph nav item visible but disabled (grayed, tooltip) when `VITE_GRAPH_ENABLED` is not `"true"`.

```tsx
// In App.tsx
const graphEnabled = import.meta.env.VITE_GRAPH_ENABLED === "true";

// In NAV_ITEMS or rendered separately:
{graphEnabled ? (
  <NavLink to="/graph" className={linkClass}>
    <GraphIcon /> Graph
  </NavLink>
) : (
  <span className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium text-gray-300 cursor-not-allowed"
        title="Graph explorer not yet enabled">
    <GraphIcon /> Graph
  </span>
)}
```

### Anti-Patterns to Avoid

- **Don't use `bolt://localhost:7687` in Docker-to-Docker communication.** Use the Docker service name `bolt://neo4j:7687` when the Python app runs inside Docker. When running Python locally against Docker Neo4j, use `bolt://localhost:7687`. The Settings class should default to `bolt://localhost:7687` (matching dev setup).
- **Don't call `build_indices_and_constraints()` on every request.** Call it once during startup in the lifespan.
- **Don't create a new Graphiti instance per request.** Graphiti holds a Neo4j driver connection pool. One singleton for the app lifetime.
- **Don't use protected field names in entity type models.** These are reserved by Graphiti's EntityNode: `uuid`, `name`, `group_id`, `labels`, `created_at`, `summary`, `attributes`, `name_embedding`.
- **Don't use `add_episode_bulk()`.** Per project requirements (REQUIREMENTS.md Out of Scope), it silently skips temporal invalidation.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Neo4j indices and constraints | Manual Cypher DDL | `graphiti.build_indices_and_constraints()` | Graphiti manages its own schema; manual DDL will conflict |
| Entity extraction from text | Custom NER pipeline | Graphiti's built-in LLM extraction (via `add_episode`) | Graphiti handles prompt engineering, validation, dedup |
| Temporal edge invalidation | Manual `t_invalid` Cypher updates | Graphiti's conflict resolution in `add_episode` | Complex bi-temporal logic with edge deduplication |
| Graph visualization rendering | Custom D3/Canvas graph renderer | @neo4j-nvl components | NVL handles layout, zoom, pan, interaction, force-directed graphs |
| Neo4j health check | Custom TCP/HTTP probe | `cypher-shell RETURN 1` in Docker healthcheck | Standard approach, verifies actual query execution not just port availability |

**Key insight:** Graphiti manages the entire Neo4j schema (indices, constraints, node labels, relationship types). Never write raw Cypher DDL for schema operations -- always go through Graphiti's API. The entity type models only define *custom attributes* on top of Graphiti's core schema.

## Common Pitfalls

### Pitfall 1: Neo4j Version Too Old
**What goes wrong:** Graphiti uses Neo4j features (like dynamic labels via `SET n:$(node.labels)`) that require 5.26+. Older versions produce cryptic Cypher syntax errors.
**Why it happens:** Docker defaults to `neo4j:latest` which may be fine, but pinning to an older version (e.g., 5.22) breaks silently.
**How to avoid:** Pin to `neo4j:5.26-community` explicitly. The `5.26` tag ensures you get the latest patch in the 5.26 LTS line.
**Warning signs:** `SyntaxError` in Cypher queries mentioning `$()` syntax during `add_episode`.

### Pitfall 2: Missing APOC Plugin
**What goes wrong:** Graphiti operations fail with "Unknown procedure" errors for APOC procedures.
**Why it happens:** Neo4j Community Docker image does not include APOC by default.
**How to avoid:** Set `NEO4J_PLUGINS=["apoc"]` in docker-compose environment. Note the JSON array syntax with double quotes inside single quotes.
**Warning signs:** `ProcedureNotFound` errors mentioning `apoc.*` procedures.

### Pitfall 3: Graphiti close() Not Called on Shutdown
**What goes wrong:** Neo4j connections leak, preventing clean container shutdown. Docker stop takes 10+ seconds as connections time out.
**Why it happens:** Graphiti holds a Neo4j driver with a connection pool. Without explicit `close()`, connections are abandoned.
**How to avoid:** Always call `await graph_service.close()` in the lifespan's shutdown block (after `yield`).
**Warning signs:** Slow container shutdown, Neo4j logs showing abandoned connections.

### Pitfall 4: Protected Field Names in Entity Types
**What goes wrong:** Graphiti silently overwrites or errors on custom entity type fields that collide with core EntityNode fields.
**Why it happens:** EntityNode already has: `uuid`, `name`, `group_id`, `labels`, `created_at`, `summary`, `attributes`, `name_embedding`.
**How to avoid:** Never use these 8 field names in your Pydantic entity type models. Use domain-specific names instead (e.g., `role` not `name`, `team_type` not `labels`).
**Warning signs:** Entity attributes being None or containing unexpected values.

### Pitfall 5: Neo4j Memory Defaults Too Low
**What goes wrong:** Neo4j OOM kills or extreme GC pauses with default 512M heap + 512M pagecache.
**Why it happens:** Docker Neo4j defaults are conservative (designed for multi-container hosts). Knowledge graph operations with LLM-generated embeddings need more headroom.
**How to avoid:** Set explicit memory: `heap_max=1G`, `pagecache=512m` minimum.
**Warning signs:** Neo4j container restarting, slow query performance, GC pause warnings in Neo4j logs.

### Pitfall 6: OpenAI API Key Required Even with Anthropic LLM
**What goes wrong:** Graphiti fails on embedding operations even though Anthropic is configured for LLM.
**Why it happens:** Graphiti uses OpenAI for embeddings regardless of LLM provider. The embedder is a separate component.
**How to avoid:** Always configure both `AnthropicClient` (for LLM) AND `OpenAIEmbedder` (for embeddings). Both API keys must be available.
**Warning signs:** `AuthenticationError` from OpenAI during `add_episode` or `search` operations.

### Pitfall 7: Feature Flag Checked at Build Time vs Runtime
**What goes wrong:** `VITE_GRAPH_ENABLED` is baked into the build, not read at runtime.
**Why it happens:** Vite replaces `import.meta.env.VITE_*` at build time via static analysis.
**How to avoid:** This is expected Vite behavior. For dev, set in `.env` file. For production, set at build time. The placeholder page should gracefully handle the backend being unavailable regardless of the flag.
**Warning signs:** Changing `.env` after build has no effect.

## Code Examples

### Neo4j Docker Compose Service (Complete)

```yaml
# Source: Neo4j Operations Manual + Graphiti Neo4j Configuration docs
  neo4j:
    image: neo4j:5.26-community
    environment:
      - NEO4J_AUTH=neo4j/pam_graph
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_server_memory_heap_initial__size=512m
      - NEO4J_server_memory_heap_max__size=1G
      - NEO4J_server_memory_pagecache_size=512m
      - NEO4J_dbms_security_procedures_unrestricted=apoc.*
    ports:
      - "7474:7474"   # HTTP (Neo4j Browser)
      - "7687:7687"   # Bolt (driver connections)
    volumes:
      - neo4jdata:/var/lib/neo4j/data
    healthcheck:
      test: ["CMD", "cypher-shell", "-u", "neo4j", "-p", "pam_graph", "RETURN 1"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    profiles:
      - ""           # Default profile: persistent volume
    # For tests: override with --profile test to use tmpfs or separate volume
```

### Settings Configuration (Python)

```python
# Source: Existing config.py pattern + Graphiti docs
# Add to Settings class in src/pam/common/config.py

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "pam_graph"

    # Graphiti
    graphiti_model: str = "claude-sonnet-4-5-20250514"
    graphiti_embedding_model: str = "text-embedding-3-small"
```

### Health Check Integration

```python
# Source: Existing health check pattern in main.py
# Add Neo4j check to the /api/health endpoint

# Check Neo4j (via graph service)
graph_service = getattr(request.app.state, "graph_service", None)
if graph_service:
    try:
        # Use the Neo4j driver to verify connectivity
        driver = graph_service.client.driver
        async with driver.session() as session:
            await session.run("RETURN 1")
        services["neo4j"] = "up"
    except Exception:
        logger.warning("health_check_neo4j_failed", exc_info=True)
        services["neo4j"] = "down"
else:
    services["neo4j"] = "down"
```

### Graph Status Endpoint

```python
# Source: Application pattern from existing routes
# GET /api/graph/status -- separate from /health

from fastapi import APIRouter, Depends
from pam.api.deps import get_graph_service
from pam.graph.service import GraphitiService

router = APIRouter()

@router.get("/api/graph/status")
async def graph_status(
    graph_service: GraphitiService = Depends(get_graph_service),
):
    """Return graph database status, entity counts, and last sync time."""
    try:
        driver = graph_service.client.driver
        async with driver.session() as session:
            # Entity counts by label
            result = await session.run(
                "MATCH (n:Entity) RETURN labels(n) AS labels, count(n) AS count"
            )
            entity_counts = {}
            async for record in result:
                for label in record["labels"]:
                    if label != "Entity":  # Skip the base label
                        entity_counts[label] = record["count"]

            # Last sync time (most recent episode)
            result = await session.run(
                "MATCH (e:Episodic) RETURN max(e.created_at) AS last_sync"
            )
            record = await result.single()
            last_sync = record["last_sync"] if record else None

        return {
            "status": "connected",
            "entity_counts": entity_counts,
            "total_entities": sum(entity_counts.values()),
            "last_sync_time": last_sync,
        }
    except Exception as e:
        return {"status": "disconnected", "error": str(e)}
```

### NVL Placeholder Component

```tsx
// Source: NVL docs + existing AdminDashboard.tsx pattern
import { useEffect, useState } from "react";

interface GraphStatus {
  status: string;
  entity_counts: Record<string, number>;
  total_entities: number;
  last_sync_time: string | null;
  error?: string;
}

export default function GraphPage() {
  const [status, setStatus] = useState<GraphStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetch("/api/graph/status")
      .then((r) => r.json())
      .then(setStatus)
      .catch(() => setStatus({ status: "error", entity_counts: {}, total_entities: 0, last_sync_time: null }))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div>Loading graph status...</div>;

  return (
    <div className="p-6 space-y-6">
      <h2 className="text-base font-semibold text-gray-800">Knowledge Graph</h2>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <StatusCard label="Neo4j" value={status?.status ?? "unknown"} />
        <StatusCard label="Total Entities" value={status?.total_entities ?? 0} />
        <StatusCard label="Last Sync" value={status?.last_sync_time ?? "Never"} />
      </div>
      {status?.entity_counts && Object.keys(status.entity_counts).length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {Object.entries(status.entity_counts).map(([type, count]) => (
            <StatusCard key={type} label={type} value={count} />
          ))}
        </div>
      )}
    </div>
  );
}
```

### Graphiti add_episode (Future Reference -- Phase 7)

```python
# Source: Graphiti docs -- for reference during entity type design
# NOT implemented in Phase 6, but entity types must be compatible

from datetime import datetime
from graphiti_core.nodes import EpisodeType
from pam.graph.entity_types import ENTITY_TYPES

await graph_service.client.add_episode(
    name=f"chunk-{chunk_id}",
    episode_body=chunk_text,
    source=EpisodeType.text,
    source_description=f"Document: {document_title}",
    reference_time=document_modified_at,  # valid_time from document
    group_id=f"doc-{document_id}",        # Scoped to document for re-ingestion
    entity_types=ENTITY_TYPES,            # The 7 game studio entity types
)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| graphiti-core < 0.20 used `source` as string | `source` is now `EpisodeType` enum | ~v0.20 | Must use `EpisodeType.text` or `EpisodeType.json` |
| Neo4j 5.x without dynamic labels | Neo4j 5.26+ supports `SET n:$(expr)` | Neo4j 5.26 | Required for Graphiti entity type labeling |
| Manual APOC jar download | `NEO4J_PLUGINS=["apoc"]` auto-download | Neo4j Docker 5.x | Simpler Docker setup, auto-matched versions |
| graphiti-core embedded OpenAI only | Pluggable LLM/Embedder via constructor | ~v0.15+ | Enables Anthropic LLM + OpenAI embedder mix |
| NVL pre-1.0 (alpha) | NVL 1.0.0 stable release | 2025 | Stable API, suitable for production use |

**Deprecated/outdated:**
- `add_episode_bulk()`: Still exists but documented as skipping temporal invalidation. Project explicitly excludes its use.
- Neo4j versions < 5.26: Missing dynamic label support required by Graphiti.
- `USE_PARALLEL_RUNTIME` Neo4j setting: Enterprise-only, not available in Community Edition.

## Open Questions

1. **Neo4j health check in Python (non-Docker context)**
   - What we know: Docker healthcheck uses `cypher-shell`. The Graphiti client wraps the neo4j Python driver.
   - What's unclear: The exact async API for checking Neo4j connectivity via the graphiti `driver` attribute (whether it's `AsyncGraphDatabase` or `GraphDatabase`). The `graph_service.client.driver` attribute type depends on Graphiti internals.
   - Recommendation: During implementation, inspect `graphiti.driver` to determine whether it exposes a `verify_connectivity()` method or requires a session-based `RETURN 1` query. The health check code example above uses a session approach which should work regardless.

2. **Graphiti telemetry**
   - What we know: Graphiti has telemetry enabled by default, controllable via `GRAPHITI_TELEMETRY_ENABLED=false`.
   - What's unclear: What data is sent and whether it impacts performance.
   - Recommendation: Disable telemetry in production by setting the env var. Not critical for Phase 6 infrastructure setup.

3. **Neo4j Docker volume with test profile**
   - What we know: User wants persistent volume by default, ephemeral via `--profile test`.
   - What's unclear: Docker Compose profile syntax for conditionally using a different volume strategy.
   - Recommendation: Use a separate `docker-compose.test.yml` override or use `tmpfs` for the neo4j data directory when `--profile test` is active. Alternatively, define a second `neo4j-test` service under the `test` profile with `tmpfs` volumes.

## Sources

### Primary (HIGH confidence)
- [Graphiti Quick Start](https://help.getzep.com/graphiti/getting-started/quick-start) -- Initialization, add_episode, environment variables
- [Graphiti Custom Entity Types](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types) -- Pydantic models, protected fields, add_episode entity_types parameter
- [Graphiti LLM Configuration](https://help.getzep.com/graphiti/configuration/llm-configuration) -- AnthropicClient + OpenAIEmbedder setup
- [Graphiti Neo4j Configuration](https://help.getzep.com/graphiti/configuration/neo-4-j-configuration) -- Version requirement, APOC, env vars
- [getzep/graphiti GitHub - graphiti.py](https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py) -- Complete API signatures for __init__, add_episode, close, build_indices_and_constraints
- [Neo4j Docker Operations Manual](https://neo4j.com/docs/operations-manual/current/docker/) -- Docker Compose setup, memory config, health checks
- [Neo4j NVL Installation](https://neo4j.com/docs/nvl/current/installation/) -- Package installation, container height requirement
- [Neo4j NVL React Wrappers](https://neo4j.com/docs/nvl/current/react-wrappers/) -- BasicNvlWrapper, InteractiveNvlWrapper API

### Secondary (MEDIUM confidence)
- [DeepWiki getzep/graphiti](https://deepwiki.com/getzep/graphiti) -- Provider configuration details, group_id concept
- [DeepWiki Provider Configuration](https://deepwiki.com/getzep/graphiti/9.3-provider-configuration) -- LLMConfig fields, OpenAIEmbedderConfig fields
- [graphiti-core PyPI](https://pypi.org/project/graphiti-core/) -- Version 0.27.1 confirmed
- [Neo4j Docker Hub](https://hub.docker.com/_/neo4j) -- Image tags, 5.26 LTS designation

### Tertiary (LOW confidence)
- [GitHub Issue #325](https://github.com/getzep/graphiti/issues/325) -- Docker Compose Neo4j version compatibility issue (confirmed fix: use 5.26+)
- [GitHub Issue #567](https://github.com/getzep/graphiti/issues/567) -- Custom entity type labels/properties issue (open, may affect entity type behavior)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Graphiti docs are clear on versions, dependencies, and configuration; Neo4j Docker is well-documented
- Architecture: HIGH -- Existing codebase patterns (lifespan, deps.py, app.state) are unambiguous; Graphiti API signatures verified from source
- Pitfalls: HIGH -- Neo4j version requirement confirmed by multiple sources including a resolved bug report; APOC requirement documented officially
- Entity types: MEDIUM -- Custom entity type API is documented but GitHub Issue #567 suggests some edge cases with label assignment; field definitions are discretionary
- Frontend (NVL): MEDIUM -- Packages are at 1.0.0 but documentation is sparse on version-specific details; React wrapper API confirmed from official docs

**Research date:** 2026-02-20
**Valid until:** 2026-03-20 (30 days -- stable domain, libraries at recent stable versions)
