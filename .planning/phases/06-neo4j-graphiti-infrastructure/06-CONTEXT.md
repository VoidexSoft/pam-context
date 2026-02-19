# Phase 6: Neo4j + Graphiti Infrastructure - Context

**Gathered:** 2026-02-19
**Status:** Ready for planning

<domain>
## Phase Boundary

Stand up Neo4j graph database, configure Graphiti engine, lock entity type schema, and wire service lifecycle into existing FastAPI patterns. All subsequent phases (7-9) depend on this infrastructure being operational. No graph queries, no UI visualization, no ingestion pipeline changes — just the foundation.

</domain>

<decisions>
## Implementation Decisions

### Entity type taxonomy
- **7 entity types** for a game studio domain: Person, Team, Project, Technology, Process, Concept, Asset
- Person: employees, stakeholders, partners
- Team: departments, squads, project teams
- Project: game titles, internal tools, prototypes
- Technology: engines, SDKs, backend systems, analytics tools, platforms
- Process: workflows, pipelines, LiveOps procedures, analytics workflows
- Concept: game design ideas, mechanics, features
- Asset: art, audio, code asset types/categories
- Implemented as Pydantic models, importable from `src/pam/graph/`
- Documents about game design → extract Concept + Project entities
- Documents about config/architecture → extract Technology entities
- Documents about analytics/LiveOps → extract Process + Technology entities

### Episode modeling
- One Graphiti episode per **chunk** (not per document) — finer-grained temporal tracking
- Bi-temporal timestamps: valid_time = document `modified_at`, transaction_time = ingestion time
- Re-ingestion uses **invalidate + replace**: old episode edges get `t_invalid` set, new episode creates fresh edges
- Full traceability: each episode stores `document_id` and `chunk_id` back-references

### Graph availability policy
- **Hard dependency**: app won't start without Neo4j — single `docker compose up` brings everything up
- Neo4j Community Edition
- Neo4j status included in existing `/health` endpoint alongside postgres and elasticsearch
- Docker volume: persistent by default, ephemeral via `--profile test`

### NVL frontend prep
- Install `@neo4j-nvl` packages in web/ project
- Wire up `VITE_GRAPH_ENABLED` feature flag
- Add `/graph` route with placeholder component
- Feature flag behavior: nav item **visible but disabled** (grayed out with tooltip) when `VITE_GRAPH_ENABLED=false`
- Placeholder page shows **graph status summary**: Neo4j connection status + entity counts + last sync time
- New `GET /api/graph/status` backend endpoint (not reusing /health) — returns Neo4j status, entity counts, last sync time

### Claude's Discretion
- Neo4j version selection and Docker image tag
- Graphiti client configuration details
- GraphitiService internal implementation
- Exact Pydantic model field definitions for entity types
- Frontend component structure and styling for placeholder page

</decisions>

<specifics>
## Specific Ideas

- Domain is a **game studio** — taxonomy optimized for game development knowledge (design docs, config data, backend architecture, analytics, LiveOps)
- The taxonomy should be extensible — new types can be added in future phases without breaking existing data
- Status summary page is useful even before Phase 9 builds the full graph explorer — gives early visibility into graph health

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 06-neo4j-graphiti-infrastructure*
*Context gathered: 2026-02-19*
