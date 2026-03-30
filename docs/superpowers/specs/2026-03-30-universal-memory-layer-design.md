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
| Multi-agent routing | Single agent, 8 tools | Supervisor + pluggable specialist agent modules |
| Data Agent toolset | Single `query_database` tool | Progressive context building: Column Finder, Value Finder, Table Rules, Execute Query (Finch-style) |
| Query-time authorization | API-level auth only | Security Service checks per table/column/metric permissions |
| LLM Gateway | Direct Anthropic/OpenAI calls | Abstraction layer for model flexibility + cost tracking |
| Output/Export | None | Format results + export to Google Sheets or other outputs |

## Architecture

```
                                                    ┌──────────────────────────┐
                                                    │   External Data Sources  │
                                                    │  DBs, APIs, S3, Webhooks │
                                                    └─────┬──────┬──────┬──────┘
                                                          │      │      │
                                                       ingest  live   push
                                                          │    query    │
┌─────────────────────────────────────────────────────────│──────│──────│───┐
│                        LLM Clients                      │      │      │   │
│   Claude Code, Cursor, ChatGPT, Custom Agents, Apps     │      │      │   │
└──────────┬────────────────────────────────┬─────────────│──────│──────│───┘
           │                                │             │      │      │
     ┌─────▼──────┐                   ┌─────▼─────┐       │      │      │
     │ MCP Server │                   │ REST API  │       │      │      │
     │ (stdio/SSE)│                   │ (FastAPI) ◄───────┘      │      │
     └─────┬──────┘                   └─────┬──┬──┘              │      │
           │                                │  │  webhook push───┘      │
           │                                │  └────────────────────────┘
     ┌─────▼────────────────────────────────▼───────────────────────┐
     │                                                              │
     │  ┌────────────────┐  ┌───────────────────────────────────┐   │
     │  │ LLM Gateway    │  │ Security Service                  │   │
     │  │ model routing, │  │ query-time auth per               │   │
     │  │ cost tracking  │  │ table/column/metric               │   │
     │  └───────┬────────┘  └──────────────┬────────────────────┘   │
     │          │                          │                        │
     │  ┌───────▼──────────────────────────▼────────────────────┐   │
     │  │              Supervisor Agent                         │   │
     │  │         (intent routing & orchestration)              │   │
     │  └──┬─────────┬─────────┬─────────┬─────────┬───────────┘   │
     │     │         │         │         │         │               │
     │  ┌──▼───┐ ┌───▼──┐ ┌───▼────┐ ┌──▼─────┐ ┌▼────────┐     │
     │  │ Doc  │ │Graph │ │ Data   │ │Insight │ │ Report  │ ... │
     │  │Agent │ │Agent │ │ Agent  │ │ Agent  │ │ Agent   │     │
     │  │      │ │      │ │        │ │        │ │         │     │
     │  │search│ │graph │ │col_find│ │run_var │ │run_tpl  │     │
     │  │getdoc│ │entits│ │val_find│ │compare │ │export   │     │
     │  │smart │ │histor│ │tbl_rule│ │anomaly │ │summary  │     │
     │  │      │ │      │ │exec_sql│ │        │ │         │     │
     │  │BUILTIN │BUILTIN│ │ext_db──┼────────────── live query    │
     │  │      │ │      │ │ext_api │ │OPTIONAL│ │OPTIONAL │     │
     │  └──┬───┘ └──┬───┘ └──┬─────┘ └──┬─────┘ └┬────────┘     │
     │     │        │        │          │        │               │
     │  ┌──▼────────▼────────▼──────────▼────────▼──────────────┐     │
     │  │              Intelligence Layer                     │     │
     │  │                                                     │     │
     │  │  ┌──────────────┐  ┌─────────────────────────────┐  │     │
     │  │  │  Semantic    │  │  Terminology Resolution     │  │     │
     │  │  │  Metadata    │  │  & Query Expansion          │  │     │
     │  │  │  • Glossary  │  └─────────────────────────────┘  │     │
     │  │  │  • Aliases   │  ┌─────────────────────────────┐  │     │
     │  │  │  • Schema    │  │  Fact Extraction Engine     │  │     │
     │  │  │    hints     │  │  • Facts → Memory           │  │     │
     │  │  │  • Fuzzy     │  │  • Terms → Glossary         │  │     │
     │  │  │    matching  │  │  • Relations → Graph        │  │     │
     │  │  └──────────────┘  │  • Prefs → Memory           │  │     │
     │  │                    └─────────────────────────────┘  │     │
     │  └─────────────────────────────────────────────────────┘     │
     │                              │                               │
     │  ┌───────────────────────────▼─────────────────────────┐     │
     │  │               Core Services                         │     │
     │  │                                                     │     │
     │  │  ┌──────────┐  ┌────────────┐  ┌──────────────┐     │     │
     │  │  │ Memory   │  │ Knowledge  │  │ Conversation │     │     │
     │  │  │ Service  │  │ Service    │  │ Service      │     │     │
     │  │  └──────────┘  └────────────┘  └──────────────┘     │     │
     │  │                                                     │     │
     │  │  ┌──────────────────────────────────────────────┐   │     │
     │  │  │       Context Assembly Engine                │   │     │
     │  │  │       (exposed as a service)                 │   │     │
     │  │  └──────────────────────────────────────────────┘   │     │
     │  └─────────────────────────────────────────────────────┘     │
     │                              │                               │
     │  ┌───────────────────────────▼────────────────────────┐      │
     │  │                 Storage Layer                      │      │
     │  │  ┌────┐  ┌────┐  ┌───────┐  ┌───────┐  ┌──────┐    │      │
     │  │  │ PG │  │ ES │  │ Neo4j │  │ Redis │  │DuckDB│    │      │
     │  │  └────┘  └────┘  └───────┘  └───────┘  └──────┘    │      │
     │  └────────────────────────────────────────────────────┘      │
     └──────────────────────────────────────────────────────────────┘
```

**Data flow:**
- **LLM clients** enter via MCP/REST → LLM Gateway routes model calls → Security Service checks permissions → Supervisor classifies intent and routes to the appropriate agent module → results merge through Context Assembly
- **Agent modules** are pluggable — built-in (Doc, Graph, Data) ship with PAM, optional (Insight, Report) are enabled per-project, custom agents can be registered via plugin pattern
- **Data Agent** builds context progressively (Column Finder → Value Finder → Table Rules → Execute Query) before generating SQL — Finch-style
- **Ingest connectors** pull from external DBs/APIs/S3 → data stored as documents in PAM
- **Live queries** — Data Agent connects to external databases at query time, authorized by Security Service
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

### Phase 7 — Modular Agent Architecture

Evolves PAM's single agent into a Finch-style supervisor with **pluggable agent modules**.

#### Agent Module Interface

Each agent is a self-contained module that registers with the Supervisor:

```python
class AgentModule(ABC):
    name:          str          # "data_agent"
    description:   str          # Used by Supervisor for routing decisions
    intents:       list[str]    # ["data_retrieval", "sql_assistance"]
    tools:         list[Tool]   # Tools this agent can use
    system_prompt: str          # Specialized prompt for this domain
    enabled:       bool         # Can be toggled per-project
    can_delegate:  list[str]    # Other agents it can call (e.g., Data Agent)
```

#### Supervisor Agent

Routes queries to the right module based on intent classification:

```
User query → Supervisor
               │
    1. Classify intent (rules + LLM fallback)
    2. Match intent to registered agent modules
    3. Check Security Service for permissions
    4. Route to specialist (or multiple in parallel)
    5. Collect results → Context Assembly Engine
```

The Supervisor discovers available agents **dynamically** from the registry — no hardcoded routing.

#### Built-in Agent Modules (ship with PAM)

**Document Agent:**

| Intent | Tools | Description |
|--------|-------|-------------|
| `knowledge_lookup` | `search_knowledge`, `smart_search` | Full-text + semantic search across documents |
| `policy_search` | `get_document_context` | Retrieve specific document content |

**Graph Agent:**

| Intent | Tools | Description |
|--------|-------|-------------|
| `relationship_query` | `search_knowledge_graph`, `graph_neighbors` | Find entity relationships |
| `temporal_query` | `get_entity_history` | Track entity changes over time |
| `entity_exploration` | `graph_neighbors` | Explore entity neighborhoods |

**Data Agent (Finch-style progressive context building):**

Instead of a single `query_external_db` tool, the Data Agent uses 4 specialized tools to build context step-by-step before generating SQL:

```
User: "What was GBs in US&C last quarter?"
                    │
              Data Agent
                    │
    ┌───────────────┼───────────────────┐
    ▼               ▼                   ▼
Column Finder   Value Finder       Table Rules
"GBs" →         "US&C" →           finance_datamart →
gross_bookings  megaregion_name    required: accounting_date
(2 tables)      = "US & Canada"    default: rate_type = USD
                                   example queries...
    └───────────────┼───────────────────┘
                    ▼
            Execute Query Tool
    SELECT SUM(gross_bookings)...
                    │
                    ▼
            Response with:
            • NL explanation of question → SQL mapping
            • Generated SQL with comments
            • Results (+ optional export link)
```

| Intent | Tools | Description |
|--------|-------|-------------|
| `data_retrieval` | `column_finder` | Find columns matching a concept across registered data sources. Searches schema hints + glossary aliases. Returns: table, column, type, alias matches. |
| | `value_finder` | Find actual values matching a filter term. Searches column value aliases from schema hints. Returns: table, column, matching values. |
| | `table_rules` | Get business rules for a table: required columns, default values, example queries, relationships. |
| | `execute_query` | Generate and run SQL/API query using assembled context. Validates against Security Service. Returns results + optional export. |
| `sql_assistance` | `column_finder`, `table_rules` | Help users understand schema and write their own queries |

**Data Source Selector:** Before the Data Agent's tools execute, a metadata-matching step selects the right data source and query language (SQL, MDX, REST) based on the question — not hardcoded.

#### Optional Agent Modules (enable per-project)

**Insight Agent:**

| Intent | Tools | Description |
|--------|-------|-------------|
| `variance_explanation` | `run_variance_analysis` | Explain why a metric changed between periods |
| `trend_analysis` | `detect_trend`, `compare_periods` | Identify and explain trends |
| `metric_comparison` | `compare_metrics` | Compare metrics across dimensions |

Delegates to Data Agent for data retrieval, then applies analytical reasoning.

**Report Agent:**

| Intent | Tools | Description |
|--------|-------|-------------|
| `report_generation` | `run_report_template` | Execute predefined report templates (P&L, activity, etc.) |
| `executive_summary` | `generate_summary` | Create concise summaries from data |
| `data_export` | `export_to_sheets` | Export results to Google Sheets or other formats |

**Visualization Agent:**

| Intent | Tools | Description |
|--------|-------|-------------|
| `chart_generation` | `create_chart` | Generate charts from query results |
| `suggest_visual` | `suggest_visualization` | Recommend best visualization type for data |

#### Agent Registration & Configuration

**Via config (static):**
```python
# .env
ENABLED_AGENTS=["document", "graph", "data", "insight", "report"]
```

**Via admin API (per-project, dynamic):**
```
POST   /api/admin/projects/{id}/agents           — Enable/disable agent for project
GET    /api/admin/projects/{id}/agents           — List enabled agents for project
GET    /api/agents                                — List all registered agent modules
GET    /api/agents/{name}                         — Get agent module details (intents, tools)
```

**Custom agent plugin pattern:**
```python
from pam.agent.base import AgentModule

class ComplianceAgent(AgentModule):
    name = "compliance"
    description = "Answers compliance and regulatory questions"
    intents = ["compliance_check", "regulation_lookup"]
    tools = [search_regulations, check_policy]
    system_prompt = "You are a compliance specialist..."

# Register in config
CUSTOM_AGENT_MODULES=["myorg.agents.ComplianceAgent"]
```

#### Cross-cutting: LLM Gateway

Abstraction layer between agents and LLM providers:

```python
class LLMGateway:
    async def complete(prompt, model_preference, ...) -> Response
```

**Responsibilities:**
- Model routing: different agents can use different models (e.g., Haiku for classification, Sonnet for SQL generation, Opus for complex reasoning)
- Cost tracking: per-agent, per-project token usage
- Rate limiting: per-model quotas
- Fallback: if primary model is unavailable, route to backup
- Audit logging: all LLM calls logged with agent, intent, tokens

#### Cross-cutting: Security Service

Query-time authorization beyond API-level auth:

```python
class SecurityService:
    async def check_access(user, resource, action) -> bool
```

**Checks:**
- Can this user access this data source?
- Can this user see this table/column? (column-level security)
- Can this user use this agent module?
- Rate limiting per user per agent

Integrates with existing RBAC (UserProjectRole) and extends to data-source-level permissions.

#### Key Behaviors

- **Pluggable:** New agent modules can be added without modifying core code
- **Delegation:** Agents can delegate to each other (Insight Agent → Data Agent for data retrieval)
- **Parallel execution:** Supervisor can invoke multiple agents in parallel for complex queries
- **Focused prompts:** Each agent has a specialized system prompt and limited tools → better accuracy
- **Fallback:** If a specialist can't answer, Supervisor tries another
- **Progressive context:** Data Agent builds context step-by-step (Column Finder → Value Finder → Table Rules → Execute) before generating queries
- **Context merge:** Results from all agents merge through the Context Assembly Engine

## Phasing Summary

| Phase | Track | Effort | Key Deliverable |
|-------|-------|--------|-----------------|
| 1 — MCP Server | Integration | Small-Medium | Any LLM client can use PAM |
| 2 — Memory CRUD | Integration | Medium | Store/retrieve discrete facts |
| 3 — Conversational Memory | Intelligence | Medium | Stateful cross-session context |
| 4 — Semantic Metadata | Intelligence | Medium | Domain-aware retrieval (Finch-style) |
| 5 — Fact Extraction | Intelligence | Medium-Large | Self-improving memory |
| 6 — External Data | Integration | Medium-Large | DB connectors, live query, webhooks |
| 7 — Modular Agents | Intelligence | Large | Pluggable agents, Finch-style Data Agent, LLM Gateway, Security Service |

Context-as-a-Service ships incrementally across all phases.

## Design Principles

- **Thin access layers:** MCP and REST share core services — no logic duplication
- **Pluggable agents:** Agent modules are self-contained, registerable, and configurable per-project
- **Progressive context building:** Data Agent discovers schema step-by-step before generating queries (Finch pattern)
- **Security at query time:** Security Service checks permissions per data source/table/column, not just API auth
- **Model flexibility:** LLM Gateway abstracts model routing, cost tracking, and fallback
- **Incremental value:** Each phase is usable independently
- **Existing patterns:** Follows PAM's established patterns (Pydantic Settings, SQLAlchemy, FastAPI DI, structlog)
- **Backward compatible:** All existing endpoints and behaviors remain unchanged
