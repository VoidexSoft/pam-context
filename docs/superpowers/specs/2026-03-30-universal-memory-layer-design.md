# PAM Context: Universal Memory Layer for LLM Clients

**Date:** 2026-03-30
**Status:** Approved
**Inspiration:** Uber Finch, Mem0, Zep, LangMem, MCP Memory Server

## Vision

PAM Context evolves from a knowledge base with a chat UI into a **universal memory layer** that any LLM client can connect to. It processes, stores, and serves knowledge through two access patterns: REST API for application integration and MCP Server for direct LLM client access.

## Current Capabilities

| Tier | Features |
|------|----------|
| **Tier 1 — Core knowledge** | Chat (with citations), hybrid search, smart search (mode routing), document listing & segment retrieval |
| **Tier 2 — Knowledge graph** | Entity listing, neighborhood exploration, entity history, graph status & sync logs |
| **Tier 3 — Ingestion & admin** | Folder/GitHub/sync ingestion, task monitoring, user/role management, system stats |

## Gap Analysis

| Capability | Current State | Target State |
|------------|--------------|--------------|
| MCP Server for LLM clients | None | SSE + stdio MCP server with 13+ tools |
| Memory CRUD API | Ingest-only, no discrete facts | Add/search/update/delete memories with semantic dedup |
| Conversational memory | No conversation storage | Multi-session conversation storage + fact extraction |
| Context-as-a-Service | Internal only (agent context assembly) | Public API returning token-budgeted context blocks |
| Semantic metadata layer | Raw documents only | Curated glossary with alias resolution (Finch-style) |
| Fact extraction | None | Auto-extraction from documents + conversations |
| Multi-agent routing | Single agent, 8 tools | Supervisor + specialist agents (Document, Graph, Data) |

## Architecture

```
                                                    ┌──────────────────────────┐
                                                    │   External Data Sources   │
                                                    │  DBs, APIs, S3, Webhooks │
                                                    └─────┬──────┬──────┬──────┘
                                                          │      │      │
                                                       ingest  live   push
                                                          │    query    │
┌─────────────────────────────────────────────────────────│──────│──────│───┐
│                        LLM Clients                      │      │      │   │
│   Claude Code, Cursor, ChatGPT, Custom Agents, Apps    │      │      │   │
└──────────┬───────────────────────────────┬──────────────│──────│──────│───┘
           │                               │              │      │      │
     ┌─────▼─────┐                   ┌─────▼─────┐       │      │      │
     │ MCP Server │                   │ REST API  │       │      │      │
     │ (stdio/SSE)│                   │ (FastAPI) ◄───────┘      │      │
     └─────┬─────┘                   └─────┬──┬──┘              │      │
           │                               │  │  webhook push───┘      │
           │                               │  └────────────────────────┘
     ┌─────▼───────────────────────────────▼────────────────────────┐
     │                                                               │
     │  ┌───────────────────────────────────────────────────────┐   │
     │  │              Supervisor Agent                          │   │
     │  │         (intent routing & orchestration)               │   │
     │  └────┬─────────────────┬───────────────────┬────────────┘   │
     │       │                 │                   │                │
     │  ┌────▼────┐      ┌────▼────┐         ┌────▼─────────┐     │
     │  │  Doc    │      │  Graph  │         │  Data        │     │
     │  │  Agent  │      │  Agent  │         │  Agent       │     │
     │  │         │      │         │         │              │     │
     │  │search   │      │graph    │         │query_db      │     │
     │  │get_doc  │      │entities │         │query_ext_db ─┼──── live query
     │  │smart    │      │history  │         │query_ext_api │     │
     │  └────┬────┘      └────┬────┘         └────┬─────────┘     │
     │       │                │                   │                │
     │  ┌────▼────────────────▼───────────────────▼──────────┐    │
     │  │              Intelligence Layer                     │    │
     │  │                                                     │    │
     │  │  ┌──────────────┐  ┌─────────────────────────────┐ │    │
     │  │  │  Semantic    │  │  Terminology Resolution     │ │    │
     │  │  │  Metadata    │  │  & Query Expansion          │ │    │
     │  │  │  • Glossary  │  └─────────────────────────────┘ │    │
     │  │  │  • Aliases   │  ┌─────────────────────────────┐ │    │
     │  │  │  • Schema    │  │  Fact Extraction Engine     │ │    │
     │  │  │    hints     │  │  • Facts → Memory           │ │    │
     │  │  │  • Fuzzy     │  │  • Terms → Glossary         │ │    │
     │  │  │    matching  │  │  • Relations → Graph         │ │    │
     │  │  └──────────────┘  │  • Prefs → Memory            │ │    │
     │  │                    └─────────────────────────────┘ │    │
     │  └────────────────────────────────────────────────────┘    │
     │                              │                             │
     │  ┌───────────────────────────▼────────────────────────┐    │
     │  │               Core Services                         │    │
     │  │                                                     │    │
     │  │  ┌──────────┐  ┌────────────┐  ┌──────────────┐   │    │
     │  │  │ Memory   │  │ Knowledge  │  │ Conversation │   │    │
     │  │  │ Service  │  │ Service    │  │ Service      │   │    │
     │  │  └──────────┘  └────────────┘  └──────────────┘   │    │
     │  │                                                     │    │
     │  │  ┌──────────────────────────────────────────────┐  │    │
     │  │  │       Context Assembly Engine                 │  │    │
     │  │  │       (exposed as a service)                  │  │    │
     │  │  └──────────────────────────────────────────────┘  │    │
     │  └────────────────────────────────────────────────────┘    │
     │                              │                             │
     │  ┌───────────────────────────▼────────────────────────┐    │
     │  │                 Storage Layer                       │    │
     │  │  ┌────┐  ┌────┐  ┌───────┐  ┌───────┐  ┌──────┐  │    │
     │  │  │ PG │  │ ES │  │ Neo4j │  │ Redis │  │DuckDB│  │    │
     │  │  └────┘  └────┘  └───────┘  └───────┘  └──────┘  │    │
     │  └────────────────────────────────────────────────────┘    │
     └────────────────────────────────────────────────────────────┘
```

**Data flow:**
- **LLM clients** enter via MCP/REST → Supervisor routes to specialist agents → results merge through Context Assembly
- **Ingest connectors** pull from external DBs/APIs/S3 → data stored as documents in PAM
- **Live queries** — Data Agent connects to external databases at query time via `query_ext_db`/`query_ext_api`
- **Webhooks** — external systems push events to PAM's REST API → ingested on arrival

Both MCP and REST are thin access layers. No logic duplication.

## Track 1: Integration Layer

### Phase 1 — MCP Server

Expose PAM's existing + new capabilities as MCP tools. SSE (remote) + stdio (local) transport.

**MCP Tools:**

| MCP Tool | Maps To | Description |
|----------|---------|-------------|
| `pam_search` | Hybrid search | Search knowledge base with filters |
| `pam_smart_search` | Smart search | Keyword extraction + mode-routed search |
| `pam_get_document` | Document fetch | Get full document content |
| `pam_query_data` | DuckDB SQL | Query structured data files |
| `pam_graph_search` | Graph relationship search | Find entity relationships |
| `pam_graph_neighbors` | Neighborhood query | Explore 1-hop subgraph |
| `pam_entity_history` | Temporal history | Get entity changes over time |
| `pam_remember` | Memory Service (Phase 2) | Store a fact, preference, or observation |
| `pam_recall` | Memory Service (Phase 2) | Retrieve relevant memories for a query |
| `pam_forget` | Memory Service (Phase 2) | Delete a specific memory |
| `pam_get_context` | Context-as-a-Service | Get assembled, token-budgeted context block |
| `pam_ingest` | Ingestion trigger | Trigger document ingestion |
| `pam_list_documents` | Document listing | Browse available documents |
| `pam_query_external_db` | **NEW** Live Query (Phase 6) | Run SQL against registered external databases |
| `pam_query_external_api` | **NEW** Live Query (Phase 6) | Call registered external REST APIs |
| `pam_list_data_sources` | **NEW** Data Source Registry (Phase 6) | List available external data sources |

**MCP Resources:**
- `pam://stats` — System stats (doc count, entity count)
- `pam://entities/{type}` — Entity listing by type
- `pam://glossary` — Domain terminology (Phase 4)
- `pam://data-sources` — Available external data sources (Phase 6)

### Phase 2 — Memory CRUD API

**REST Endpoints (`/api/memory`):**

```
POST   /memory              — Store a memory (fact, preference, observation)
GET    /memory/search       — Semantic search across memories
GET    /memory/{memory_id}  — Get specific memory
PUT    /memory/{memory_id}  — Update a memory
DELETE /memory/{memory_id}  — Delete a memory
GET    /memory/user/{user_id} — List all memories for a user
```

**Memory Data Model:**

```
Memory {
  id:          UUID
  user_id:     UUID          — who this memory belongs to
  project_id:  UUID          — scope
  type:        enum          — [fact, preference, observation, conversation_summary]
  content:     text          — the memory itself
  source:      text          — where it came from (conversation, document, manual)
  metadata:    JSONB         — flexible key-value
  embedding:   vector        — for semantic retrieval
  importance:  float (0-1)   — for ranking
  created_at:  timestamp
  updated_at:  timestamp
  expires_at:  timestamp     — optional TTL
}
```

**Key behaviors (inspired by Mem0):**
- On `POST /memory`, PAM deduplicates — cosine similarity > 0.9 against existing memories triggers an update rather than insert. The LLM merges the old and new content.
- Importance scoring: `importance = 0.5 * recency + 0.3 * access_frequency + 0.2 * explicit_weight`. Decays over time unless accessed.
- Optional TTL for ephemeral memories (conversation context that expires)

### Context-as-a-Service API (ships incrementally)

```
POST /api/context/assemble
```

**Request:**
```json
{
  "query": "What is our Q1 revenue target?",
  "user_id": "uuid",
  "token_budget": 8000,
  "include": ["documents", "memories", "graph", "glossary"],
  "mode": "auto"
}
```

**Response:**
```json
{
  "context_block": "## Relevant Knowledge\n...\n## User Context\n...",
  "token_count": 6420,
  "sources": ["..."],
  "retrieval_mode": "factual",
  "mode_confidence": 0.92
}
```

Evolves across phases:
- Phase 1: documents + graph
- Phase 2: + memories
- Phase 3: + conversation history
- Phase 4: + terminology resolution
- Phase 6: supervisor selects optimal assembly strategy

## Track 2: Intelligence Layer

### Phase 3 — Conversational Memory

**Data Model:**

```
Conversation {
  id:           UUID
  user_id:      UUID
  project_id:   UUID
  started_at:   timestamp
  last_active:  timestamp
}

Message {
  id:              UUID
  conversation_id: UUID
  role:            enum [user, assistant, system]
  content:         text
  metadata:        JSONB (model, token count, latency)
  created_at:      timestamp
}
```

**Automatic fact extraction pipeline:**
After each conversation turn, a background process:
1. Scans the exchange for extractable facts/preferences
2. Compares against existing memories (dedup)
3. Stores new facts via the Memory Service
4. Updates importance scores on accessed memories

**Conversation summarization:**
When conversations exceed a configurable length, PAM generates compressed summaries stored as `conversation_summary` type memories. Old messages can be archived while the summary persists.

### Phase 4 — Semantic Metadata Layer

Finch-inspired domain intelligence. A curated layer of terminology that sits between raw documents and retrieval.

**Term Data Model:**

```
Term {
  id:           UUID
  project_id:   UUID
  canonical:    text       — "Gross Bookings"
  aliases:      text[]     — ["GBs", "gross books", "total bookings"]
  definition:   text       — "Total fare amount before deductions..."
  category:     text       — "metric", "team", "product", "acronym"
  metadata:     JSONB
  embedding:    vector
}
```

**Retrieval integration:**
1. User query: "What's the GBs target?"
2. Terminology resolution expands "GBs" → "Gross Bookings" via fuzzy alias match
3. Expanded query feeds into search, improving recall
4. Response uses canonical term with alias noted

**Population strategies:**
- Auto-extraction during document ingestion
- Manual curation via admin API
- Learning from user corrections

**REST Endpoints (`/api/glossary`):**

```
POST   /api/glossary           — Add term
GET    /api/glossary/search    — Fuzzy search terms
GET    /api/glossary           — List terms (paginated)
PUT    /api/glossary/{id}      — Update term
DELETE /api/glossary/{id}      — Delete term
POST   /api/glossary/resolve   — Resolve aliases in a query string
```

### Phase 5 — Fact Extraction Engine

Unified LLM-powered extraction pipeline for facts, terms, relationships, and preferences.

**Extraction types:**

| Type | Source | Output | Example |
|------|--------|--------|---------|
| Facts | Conversations | Memory Service | "User prefers Python over JS" |
| Terms | Documents | Glossary Store | "GBs = Gross Bookings" |
| Relationships | Documents + Conversations | Graph (Graphiti) | "Alice leads the Payments team" |
| Preferences | Conversations | Memory Service (type=preference) | "User wants concise answers" |

**Pipeline:**
```
Input (text) → LLM Extractor (Haiku) → Dedup/Merge → Store
                    │
                    ├─ Facts → Memory Service
                    ├─ Terms → Glossary Store
                    ├─ Relationships → Graph (Graphiti)
                    └─ Preferences → Memory Service
```

Runs asynchronously after ingestion or conversation turns. Configurable per-project.

### Phase 6 — External Data Integration

Three patterns for connecting PAM to external data sources.

**Architecture:**
```
┌──────────────────────────────────────────────────────┐
│                 External Data Sources                  │
│  Internal DBs, Snowflake, APIs, S3, Salesforce, etc  │
└───┬──────────────────┬───────────────────┬───────────┘
    │                  │                   │
    ▼                  ▼                   ▼
┌────────┐      ┌────────────┐      ┌──────────┐
│ Ingest │      │ Live Query │      │ Webhook  │
│ (pull) │      │ (at query  │      │ (push)   │
│        │      │  time)     │      │          │
└───┬────┘      └─────┬──────┘      └────┬─────┘
    │                 │                  │
    ▼                 ▼                  ▼
┌───────────────────────────────────────────────┐
│              PAM Core Services                 │
│  stored as     queried by       ingested on   │
│  documents     Data Agent       arrival        │
└───────────────────────────────────────────────┘
```

#### Pattern 1: Ingest (pull data in)

Best for slow-changing reference data. Extends PAM's existing connector pattern.

**New connectors:**

| Connector | Source | Use Case |
|-----------|--------|----------|
| `DatabaseConnector` | PostgreSQL, MySQL | Product catalogs, org charts, config tables |
| `APIConnector` | REST/GraphQL endpoints | Internal services, CRM records |
| `S3Connector` | AWS S3 / GCS / Azure Blob | CSV, Parquet, JSON from data lakes |
| `AnalyticsConnector` | BI tool exports | Metric definitions, dashboard configs |

All follow the existing `BaseConnector` interface:
```python
class BaseConnector(ABC):
    async def list_documents() -> list[DocumentInfo]
    async def fetch_document(source_id: str) -> RawDocument
    async def get_content_hash(source_id: str) -> str
```

**DatabaseConnector specifics:**
- Config defines tables/queries to ingest, not raw DB access
- Each row or query result becomes a document segment
- Content hash on query result for change detection on re-sync
- Scheduled re-sync via existing `/ingest/sync` endpoint

```python
# Config example
DATABASE_SOURCES=[
  {
    "name": "product_catalog",
    "dsn": "postgresql://...",
    "query": "SELECT id, name, description, category FROM products",
    "schedule": "daily"
  }
]
```

#### Pattern 2: Live Query (query at request time)

Best for real-time data and large datasets. Finch-style — Data Agent runs SQL at query time.

**New agent tools for the Data Agent:**

| Tool | Target | Example |
|------|--------|---------|
| `query_external_db` | SQL databases (PG, MySQL, Snowflake, BigQuery) | "What's Q1 revenue?" → generates + runs SQL |
| `query_external_api` | REST endpoints | "How many active users?" → calls internal API |

**Data Source Registry:**
```
DataSource {
  id:              UUID
  project_id:      UUID
  name:            text          — "analytics_warehouse"
  type:            enum          — [postgres, mysql, snowflake, bigquery, rest_api]
  connection:      JSONB (encrypted) — DSN or endpoint URL + auth
  schema_hint:     text          — table/column descriptions for the LLM
  allowed_tables:  text[]        — whitelist (security)
  read_only:       bool          — always true for live query
  created_at:      timestamp
}
```

**Safety controls:**
- Read-only connections enforced at driver level
- Table/schema whitelist — agent can only query allowed tables
- Query validation: block DDL, DML, multi-statement
- Timeout per query (configurable, default 30s)
- Row limit per result (configurable, default 1000)
- Credentials encrypted at rest, never exposed to LLM

**Schema hints** (Finch-style semantic layer):
```json
{
  "tables": {
    "orders": {
      "description": "Customer orders",
      "columns": {
        "gmv": { "alias": ["GBs", "gross bookings"], "description": "Gross merchandise value in USD" },
        "region": { "alias": ["market"], "values": { "US&C": "US and Canada", "EMEA": "Europe" } }
      }
    }
  }
}
```

These schema hints integrate with the Semantic Metadata Layer (Phase 5) — column aliases become terms in the glossary.

**REST Endpoints (`/api/data-sources`):**

```
POST   /api/data-sources              — Register a data source
GET    /api/data-sources              — List data sources
GET    /api/data-sources/{id}         — Get data source (connection redacted)
PUT    /api/data-sources/{id}         — Update data source
DELETE /api/data-sources/{id}         — Remove data source
POST   /api/data-sources/{id}/test    — Test connectivity
GET    /api/data-sources/{id}/schema  — Discover tables/columns
```

#### Pattern 3: Webhook (push data in)

Best for event-driven updates from systems that support webhooks.

**Webhook endpoint:**
```
POST /api/ingest/webhook/{source_name}
```

**Request:**
```json
{
  "event": "deal_closed",
  "data": {
    "account": "Acme Corp",
    "amount": 50000,
    "owner": "alice@company.com"
  },
  "timestamp": "2026-03-30T10:00:00Z"
}
```

**Behaviors:**
- Each webhook source has a registered schema + project mapping
- Incoming data is converted to a document segment and ingested
- Optionally triggers fact extraction (feeds Memory Service + Graph)
- HMAC signature verification for security
- Idempotency key to prevent duplicate processing

**Webhook Registry:**
```
WebhookSource {
  id:           UUID
  project_id:   UUID
  name:         text          — "salesforce_deals"
  secret:       text          — HMAC signing key
  transform:    JSONB         — mapping rules (event fields → document fields)
  auto_extract: bool          — trigger fact extraction on arrival
  created_at:   timestamp
}
```

**REST Endpoints (`/api/webhooks`):**

```
POST   /api/webhooks              — Register a webhook source
GET    /api/webhooks              — List webhook sources
DELETE /api/webhooks/{id}         — Remove webhook source
GET    /api/webhooks/{id}/logs    — Recent webhook deliveries
```

### Phase 7 — Multi-Agent Query Router

Evolves PAM's single agent into a Finch-style supervisor pattern.

**Agent architecture:**
```
┌──────────────────────┐
│   Supervisor Agent    │
│  (routes to specialist│
│   based on intent)    │
└──┬─────┬─────┬───────┘
   │     │     │
   ▼     ▼     ▼
┌─────┐┌─────┐┌─────┐
│Doc  ││Graph││Data │
│Agent││Agent││Agent│
└─────┘└─────┘└─────┘
```

| Agent | Tools | Best For |
|-------|-------|----------|
| **Supervisor** | Routes only, no direct retrieval | Intent classification, decomposition |
| **Document Agent** | `search_knowledge`, `get_document_context`, `smart_search` | Factual lookups, document Q&A |
| **Graph Agent** | `search_knowledge_graph`, `get_entity_history`, `graph_neighbors` | Relationship queries, temporal questions |
| **Data Agent** | `query_database`, `query_external_db`, `query_external_api`, `search_entities` | Metric lookups, live data queries, structured data |

**Key behaviors:**
- Supervisor can invoke multiple specialists in parallel for complex queries
- Each specialist has a focused system prompt and fewer tools → better accuracy
- Data Agent uses schema hints + glossary for accurate SQL generation
- Fallback: if a specialist can't answer, supervisor tries another
- Context from all specialists merges through the Context Assembly Engine

## Phasing Summary

| Phase | Track | Effort | Key Deliverable |
|-------|-------|--------|-----------------|
| 1 — MCP Server | Integration | Small-Medium | Any LLM client can use PAM |
| 2 — Memory CRUD | Integration | Medium | Store/retrieve discrete facts |
| 3 — Conversational Memory | Intelligence | Medium | Stateful cross-session context |
| 4 — Semantic Metadata | Intelligence | Medium | Domain-aware retrieval (Finch-style) |
| 5 — Fact Extraction | Intelligence | Medium-Large | Self-improving memory |
| 6 — External Data | Integration | Medium-Large | DB connectors, live query, webhooks |
| 7 — Multi-Agent Router | Intelligence | Large | Finch-like orchestration |

Context-as-a-Service ships incrementally across all phases.

## Design Principles

- **Thin access layers:** MCP and REST share core services — no logic duplication
- **Incremental value:** Each phase is usable independently
- **YAGNI:** No speculative features; each capability maps to a concrete user need
- **Existing patterns:** Follows PAM's established patterns (Pydantic Settings, SQLAlchemy, FastAPI DI, structlog)
- **Backward compatible:** All existing endpoints and behaviors remain unchanged
