# Technology Stack: Knowledge Graph & Temporal Reasoning Milestone

**Project:** PAM Context
**Domain:** Neo4j knowledge graph + Graphiti bi-temporal model + graph-aware agent + NVL graph explorer
**Researched:** 2026-02-19
**Confidence:** HIGH (core libraries verified via official docs and PyPI; NVL version HIGH; graphiti version HIGH)

---

## Scope: Additions and Changes Only

This milestone adds the following capabilities to an existing Python 3.12 + FastAPI + SQLAlchemy async + ES 8.x + PG 16 + React 18 + TypeScript + Vite + Tailwind stack. Everything below is NEW — the existing stack is not changed.

---

## New Backend Dependencies

### Core Graph Technologies

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `neo4j` (Python driver) | `>=6.1` | Async Bolt connection to Neo4j; session/transaction management | v6.x is the current release (Jan 2026); v5.x is deprecated. `AsyncGraphDatabase.driver()` integrates cleanly with FastAPI lifespan pattern already in use. The project's existing `app.state` pattern applies directly. |
| `graphiti-core` | `>=0.28` | Bi-temporal knowledge graph engine; LLM-driven entity extraction; edge invalidation on change | The library that does everything: ingests episodes, extracts entities with OpenAI/Anthropic, maintains dual-timeline (event time + ingestion time), resolves entity duplicates, and queries via hybrid BM25 + vector search. Managed by Zep AI, Apache-2.0 licensed, ~14K GitHub stars as of mid-2025. |
| `graphiti-core[anthropic]` | same | Anthropic Claude as the LLM provider for entity extraction | The project already uses `anthropic>=0.40`. Installing with `[anthropic]` extra wires Claude into Graphiti's LLM interface without pulling in a second LLM provider. Graphiti defaults to OpenAI — use the Anthropic extra to keep the project vendor-consistent. |

### graphiti-core Transitive Dependencies Pulled In

These arrive automatically via graphiti-core. Document them for version-pinning awareness:

| Package | Version Pulled | Notes |
|---------|----------------|-------|
| `pydantic` | `>=2.11.5` | Already in project at `>=2.0`; no conflict |
| `openai` | `>=1.91.0` | Already in project at `>=1.50`; graphiti requires newer version — upgrade floor |
| `tenacity` | `>=9.0.0` | Already in project at `>=8.0`; graphiti requires v9 — upgrade floor |
| `numpy` | `>=1.0.0` | Not currently in project; pulled transitively |
| `diskcache` | `>=5.6.3` | Not currently in project; used by graphiti for embedding caching |
| `posthog` | `>=3.0.0` | Not currently in project; graphiti telemetry (can be silenced) |

**Action required in pyproject.toml:** Bump `openai>=1.91.0` and `tenacity>=9.0.0` to satisfy graphiti's stricter floors.

---

## New Infrastructure: Neo4j

### Docker Compose Addition

Add Neo4j 5.26 Community to `docker-compose.yml`. Version 5.26 is the **minimum required by graphiti-core** (verified from graphiti pyproject.toml: `neo4j>=5.26.0`).

```yaml
neo4j:
  image: neo4j:5.26-community
  environment:
    NEO4J_AUTH: neo4j/pam_password
    NEO4J_PLUGINS: '[]'          # No APOC needed; graphiti uses native indexes
    NEO4J_dbms_memory_heap_max__size: 1G
    NEO4J_dbms_memory_pagecache_size: 512M
  ports:
    - "7474:7474"   # HTTP browser UI
    - "7687:7687"   # Bolt (driver connects here)
  volumes:
    - neo4jdata:/data
  healthcheck:
    test: ["CMD-SHELL", "cypher-shell -u neo4j -p pam_password 'RETURN 1' || exit 1"]
    interval: 10s
    timeout: 5s
    retries: 10
    start_period: 30s
```

**APOC is NOT required.** Graphiti uses Neo4j 5.x native vector indexes and native full-text indexes (both available in Community Edition). APOC full-text procedures are deprecated in Neo4j 5.x. Confirmed by Zep documentation: the three required env vars are only `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`.

**Enterprise Edition is NOT needed.** The `USE_PARALLEL_RUNTIME` flag (Enterprise-only) is an optional optimization, not a requirement. Community Edition handles all Graphiti operations.

---

## New Frontend Dependencies

### Graph Explorer UI

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `@neo4j-nvl/base` | `^1.0.0` | Core GPU-accelerated graph rendering engine (WebGL) | Required peer dependency of the React wrapper. Canvas-based, HNSW-accelerated layout. Free for commercial use without separate license when connecting to Neo4j. |
| `@neo4j-nvl/react` | `^1.0.0` | React components: `BasicNvlWrapper` and `InteractiveNvlWrapper` | Official React wrapper around NVL. Provides prop-driven graph updates, external refs, and `mouseEventCallbacks`. Ships with TypeScript types. Latest version: 1.0.0 (published ~5 months ago; stable API). |
| `@neo4j-nvl/interaction-handlers` | `^1.0.0` | Pan, zoom, drag, hover interactions | Optional but needed for an explorable graph UI. Without it, the graph is static. `InteractiveNvlWrapper` bundles these automatically; install if using `BasicNvlWrapper` with manual interaction wiring. |

**License:** NVL is freely available on npm with no additional licensing fees when connecting to Neo4j. Confirmed by official Neo4j documentation.

**No frontend Neo4j driver needed.** The graph explorer fetches data through the PAM FastAPI backend, not directly from Neo4j. The frontend receives nodes/relationships as JSON from a new `/api/graph/*` endpoint. NVL accepts plain `{ id, labels, properties }` objects — no Neo4j connection required in the browser.

### Frontend Installation

```bash
# In web/ directory
npm install @neo4j-nvl/base @neo4j-nvl/react @neo4j-nvl/interaction-handlers
```

---

## New Python Module: `src/pam/graph/`

Add a new top-level module alongside existing `ingestion`, `retrieval`, `agent`, `api`. This is where all graph-specific logic lives.

### Recommended internal structure

```
src/pam/graph/
    __init__.py
    client.py          # Async Neo4j driver singleton (lifespan-managed via app.state)
    graphiti_service.py # Wraps Graphiti instance; exposes add_episode(), search()
    entity_extractor.py # Custom Pydantic entity schemas for PAM domain
    change_engine.py   # Diff logic: compare new doc vs existing episodes, trigger re-ingestion
    router.py          # FastAPI routes: GET /graph/nodes, GET /graph/edges, GET /graph/search
```

### Integration with existing FastAPI lifespan

```python
# In src/pam/api/app.py lifespan:
from neo4j import AsyncGraphDatabase
from graphiti_core import Graphiti

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Existing startup...
    app.state.neo4j_driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    app.state.graphiti = Graphiti(
        settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
    )
    await app.state.graphiti.build_indices_and_constraints()
    yield
    # Existing shutdown...
    await app.state.neo4j_driver.close()
    await app.state.graphiti.close()
```

**Note:** Graphiti manages its own internal Neo4j connection. The separate `neo4j` driver is only needed for raw Cypher queries in the graph explorer API (e.g., fetching subgraph neighborhoods, running custom traversals outside Graphiti's search API).

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Graph engine | graphiti-core | neo4j-graphrag-python (SimpleKGPipeline) | graphiti handles bi-temporal tracking, incremental episode ingestion, and LLM entity deduplication out of the box. neo4j-graphrag is better for static batch pipelines, not live document update detection. |
| Graph engine | graphiti-core | LangGraph + Neo4j | The project explicitly uses a simple tool-use loop, NOT LangGraph. Introducing LangGraph for the graph layer contradicts the architectural decision and adds significant complexity. |
| Graph DB | Neo4j 5.26 Community | FalkorDB, Kuzu | graphiti supports all three, but Neo4j has the deepest integration, best tooling, HNSW native vector index, and the NVL visualization library is Neo4j-native. FalkorDB/Kuzu are valid alternatives only if Neo4j licensing becomes a concern. |
| Graph visualization | @neo4j-nvl/react | react-force-graph, Sigma.js, Cytoscape.js | NVL is purpose-built for Neo4j data, GPU-accelerated, already used in Neo4j Bloom/Explore, and the simplest integration path. react-force-graph is fine for simple graphs but requires custom data transformation and has no Neo4j-native type support. |
| Neo4j driver | neo4j v6.x | neo4j-driver (legacy) | `neo4j-driver` package is deprecated as of v6.0 with no further updates. Use the `neo4j` package only. |
| LLM for entity extraction | Anthropic (via graphiti extra) | OpenAI | The project is already Anthropic-first. Using `graphiti-core[anthropic]` avoids a second vendor dependency. OpenAI is still pulled in as graphiti's default — but the Anthropic provider is used via `AnthropicClient` wrapper. |

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| LangChain / LangGraph | Architectural decision already made: simple tool-use loop, not orchestration framework. Adding LangChain for graph traversal would split the codebase into two philosophies. | graphiti-core's built-in `search()` + raw Cypher via neo4j driver |
| `neo4j-driver` package | Deprecated as of v6.0, no further updates | `neo4j` package (v6.x) |
| APOC plugin | Not required for graphiti. Neo4j 5.x native full-text and vector indexes handle everything. Adds deployment complexity for no benefit. | Native Neo4j indexes |
| GDS (Graph Data Science) plugin | Only needed for graph ML algorithms (PageRank, community detection at scale). Out of scope for this milestone. | Add only if a future milestone needs graph analytics. |
| Frontend Neo4j Bolt WebSocket connection | Exposes database credentials in the browser; security anti-pattern | Backend API endpoints that return graph JSON |
| `neo4j-graphrag-python` | Overlaps with graphiti-core for this use case; batch-oriented not incremental; adds a redundant library | graphiti-core handles entity extraction, search, and temporal tracking in one package |
| `spacy` / standalone NER | graphiti-core uses LLM-based entity extraction via structured outputs — more flexible than spaCy's pretrained models for business document domains | graphiti's built-in LLM extraction with custom Pydantic schemas |

---

## Version Compatibility

| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `graphiti-core>=0.28` | `neo4j>=5.26.0` (server), `neo4j>=6.1` (Python driver) | Graphiti's own pyproject.toml pins `neo4j>=5.26.0` as the Python driver constraint. The driver version and server version are separate; driver 6.x connects to server 5.26. |
| `graphiti-core>=0.28` | `openai>=1.91.0` | Higher than the project's current `>=1.50` floor; bump pyproject.toml |
| `graphiti-core>=0.28` | `tenacity>=9.0.0` | Higher than the project's current `>=8.0` floor; bump pyproject.toml |
| `graphiti-core>=0.28` | `pydantic>=2.11.5` | Compatible with project's `pydantic>=2.0` |
| `@neo4j-nvl/react@1.0.0` | React 18 | Confirmed peer dependency; existing project uses React 18.3.x |
| `@neo4j-nvl/base@1.0.0` | TypeScript 5.x | Ships with types; project uses TypeScript 5.6.3 |

---

## pyproject.toml Changes

```toml
dependencies = [
    # ... existing deps ...

    # Graph — new additions
    "neo4j>=6.1",
    "graphiti-core[anthropic]>=0.28",

    # Version floor bumps required by graphiti-core
    "openai>=1.91.0",      # was >=1.50
    "tenacity>=9.0.0",     # was >=8.0
]
```

---

## Sources

- [graphiti-core PyPI](https://pypi.org/project/graphiti-core/) — version 0.28.0 current, HIGH confidence
- [getzep/graphiti GitHub pyproject.toml](https://github.com/getzep/graphiti/blob/main/pyproject.toml) — exact dependency versions, HIGH confidence
- [Zep Graphiti Neo4j Configuration docs](https://help.getzep.com/graphiti/configuration/neo-4-j-configuration) — minimum Neo4j version (5.26), APOC not required, HIGH confidence
- [Zep Graphiti Custom Entities docs](https://help.getzep.com/graphiti/core-concepts/custom-entity-and-edge-types) — Pydantic schema patterns for entity extraction, HIGH confidence
- [Neo4j Python Driver 6.1 docs](https://neo4j.com/docs/api/python-driver/current/) — async API, AsyncGraphDatabase, HIGH confidence
- [Neo4j Python Driver PyPI](https://pypi.org/project/neo4j/) — version 6.1.0 released Jan 2026; `neo4j-driver` deprecated, HIGH confidence
- [@neo4j-nvl/react npm](https://www.npmjs.com/package/@neo4j-nvl/react) — version 1.0.0, MEDIUM confidence (npm page inaccessible but confirmed via WebSearch)
- [Neo4j NVL React wrappers docs](https://neo4j.com/docs/nvl/current/react-wrappers/) — BasicNvlWrapper, InteractiveNvlWrapper components, HIGH confidence
- [Neo4j NVL Installation docs](https://neo4j.com/docs/nvl/current/installation/) — npm install @neo4j-nvl/base, free licensing, HIGH confidence
- [Neo4j Docker Hub](https://hub.docker.com/_/neo4j) — 5.26-community image tag, HIGH confidence
- [Zep temporal KG architecture paper (arxiv 2501.13956)](https://arxiv.org/html/2501.13956v1) — bi-temporal model details, HIGH confidence

---

*Stack research for: PAM Context — Knowledge Graph & Temporal Reasoning Milestone*
*Researched: 2026-02-19*
