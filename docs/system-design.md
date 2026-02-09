# PAM Context — System Design

## 1. Vision

PAM Context is a **Business Knowledge Layer for LLMs** — a system that transforms scattered business documents, spreadsheets, and data systems into a reliable, structured "source of truth" for AI-assisted reasoning and decision-making.

The goal is to make LLMs behave less like chatbots and more like:

> *A senior analyst who knows the docs, understands the data, remembers history, and can explain decisions clearly.*

---

## 2. High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        PAM Context                              │
│                                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Layer 1: Data Sources & Ingestion                        │  │
│  │  Google Docs | Google Sheets | Markdown | Databases       │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Layer 2: Parsing & Structuring                           │  │
│  │  Docling (layout, tables, OCR) → HybridChunker            │  │
│  │  Google Sheets API → Custom structured parser              │  │
│  │  LangExtract (optional entity extraction)                  │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Layer 3: Knowledge Stores (Hybrid)                       │  │
│  │                                                           │  │
│  │  ┌─────────────┐ ┌──────────┐ ┌────────┐ ┌───────────┐  │  │
│  │  │ Elasticsearch│ │PostgreSQL│ │Neo4j + │ │ Redis     │  │  │
│  │  │ (vector +   │ │(catalog, │ │Graphiti│ │ (cache)   │  │  │
│  │  │  BM25)      │ │ metadata,│ │(temporal│ │           │  │  │
│  │  │             │ │ versions)│ │ KG)    │ │           │  │  │
│  │  └─────────────┘ └──────────┘ └────────┘ └───────────┘  │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Layer 4: Retrieval & Reasoning                           │  │
│  │  LangGraph Agent Orchestration                             │  │
│  │  Hybrid retrieval (RRF) + Reranking + Tool use             │  │
│  └─────────────────────────┬─────────────────────────────────┘  │
│                            ↓                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Layer 5: LLM Applications                                │  │
│  │  Business Q&A | Debugging Assistant | Analytics Copilot    │  │
│  │  FastAPI backend + React frontend                          │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Layer Details

### 3.1 Layer 1: Data Sources & Ingestion

Responsible for connecting to business data sources and pulling raw content.

#### Data Sources

| Source Type | Examples | Connector |
|---|---|---|
| Unstructured docs | Google Docs, PDFs, DOCX, PPTX | Google Drive API, file watchers |
| Semi-structured | Google Sheets (metrics, configs, tracking plans) | Google Sheets API (custom parser) |
| Structured data | BigQuery, PostgreSQL, Snowflake | SQL connectors (direct query) |
| Markdown/local | Runbooks, ADRs, notes | File system watcher (chokidar) |

#### Sync Strategy

- **Google Drive**: Webhook-based change notifications (Drive API `changes.watch`) for near-real-time sync. Fallback to polling every 5 minutes.
- **Databases**: On-demand query (no sync — queried live by the agent at retrieval time).
- **Local files**: File system watcher for immediate detection.
- **Deduplication**: Content hash (SHA-256) per document. Only changed documents trigger re-processing.

#### Ingestion Pipeline

```
Source → Connector → Raw Content + Metadata → Content Hash Check
                                                    ↓
                                          Changed? → Yes → Layer 2
                                                   → No  → Skip
```

---

### 3.2 Layer 2: Parsing & Structuring

Transforms raw content into AI-ready knowledge segments.

#### Primary Parser: Docling

Used for all document types except Google Sheets.

- **Layout analysis**: DocLayNet model identifies page structure, reading order
- **Table extraction**: TableFormer model — 97.9% accuracy on complex tables
- **OCR**: Built-in support for scanned PDFs and images
- **Output**: DoclingDocument (structured JSON) preserving hierarchical sections (H1/H2/H3), tables, figures, code blocks

#### Google Sheets Parser: Custom

Google Sheets require special handling because they contain mixed content:

```python
# Conceptual structure
SheetSegment:
  - type: "table" | "notes" | "config" | "metrics"
  - headers: list[str]
  - rows: list[dict]
  - inferred_schema: dict  # column types, relationships
  - cell_notes: dict       # annotations
  - named_ranges: list
  - metadata: {sheet_name, tab_name, owner, last_modified}
```

Strategy:
1. Pull sheet data via Google Sheets API (preserving formatting, merged cells, named ranges)
2. Detect regions: table regions (contiguous headers + data rows) vs. note regions (free text)
3. Infer schema per table region (column types, nullable, enums)
4. Generate structured segments with full provenance

#### Chunking: Docling HybridChunker

- Semantic + token-aware chunking
- Respects document hierarchy (never splits mid-section)
- Enriches chunks with structural metadata (parent section, position, type)
- Configurable max token size (target: 512 tokens per chunk for embedding)

#### Entity Extraction: LangExtract (Optional, Phase 2)

After Docling produces structured text, LangExtract can extract business entities:
- Metric definitions (name, formula, owner, data source)
- KPI schemas
- Event tracking definitions
- Ownership and responsibility mappings

These feed into the Knowledge Graph (Layer 3D).

#### Output: Knowledge Segments

```typescript
interface KnowledgeSegment {
  id: string;                    // stable UUID
  content: string;               // chunk text
  content_hash: string;          // SHA-256 for change detection
  embedding: number[];           // vector embedding

  // Provenance
  source_type: "doc" | "sheet" | "markdown" | "database";
  source_id: string;             // Google Doc ID, file path, etc.
  source_url: string;            // link back to original
  source_section: string;        // "Section 3.2 > Table 1"

  // Metadata
  owner: string;
  project: string;
  tags: string[];
  created_at: datetime;
  updated_at: datetime;
  version: number;

  // Structure
  segment_type: "text" | "table" | "code" | "image_caption";
  parent_segment_id: string | null;
  position: number;              // order within document
}
```

---

### 3.3 Layer 3: Knowledge Stores

Four specialized stores, each optimized for a different retrieval pattern.

#### A. Elasticsearch — Semantic + Lexical Search

Serves as the **primary retrieval engine**, handling both vector similarity and keyword search in one system.

- **Vector search**: dense embeddings via `dense_vector` field type with HNSW indexing
- **BM25 search**: full-text search on content, titles, metadata fields
- **Hybrid search**: native support for combining vector + BM25 scores
- **Filtering**: by project, owner, source_type, tags, date ranges

Index mapping:
```json
{
  "mappings": {
    "properties": {
      "content": { "type": "text", "analyzer": "standard" },
      "embedding": { "type": "dense_vector", "dims": 1536, "similarity": "cosine" },
      "source_type": { "type": "keyword" },
      "project": { "type": "keyword" },
      "owner": { "type": "keyword" },
      "tags": { "type": "keyword" },
      "updated_at": { "type": "date" },
      "segment_type": { "type": "keyword" }
    }
  }
}
```

**Why Elasticsearch over separate vector DB + BM25:**
- Native hybrid search (no external fusion needed)
- Mature, battle-tested at scale
- One system to operate instead of two
- Strong metadata filtering capabilities alongside vector search

> **Note**: For teams wanting an even simpler Phase 1, pgvector + pg_trgm in PostgreSQL is a viable alternative that eliminates a service. Elasticsearch becomes clearly beneficial at scale (>5-10M vectors) or when advanced BM25 tuning is needed.

#### B. PostgreSQL — Metadata & Catalog Store

The **system of record** for all documents, segments, and relationships.

Tables:
- `documents` — source documents with metadata, sync status, content hash
- `segments` — knowledge segments with provenance, version history
- `projects` — project scoping and configuration
- `permissions` — who can access what
- `sync_log` — ingestion audit trail
- `change_history` — tracks what changed, when, and in which document

Key capabilities:
- Full version history of every segment
- Permission-scoped queries (project-level, team-level)
- Audit trail for all ingestion activity
- Dashboard for monitoring freshness and coverage

#### C. Neo4j + Graphiti — Temporal Knowledge Graph

Models **relationships and their evolution over time**.

Node types:
- `Metric` (name, current_definition, formula)
- `Document` (title, source, type)
- `Dashboard` (name, tool, url)
- `DataSource` (database, table, schema)
- `Team` / `Person` (owner, role)
- `Event` (tracking event name, properties)

Edge types:
- `DEFINED_IN` (Metric → Document)
- `SOURCED_FROM` (Metric → DataSource)
- `DISPLAYED_ON` (Metric → Dashboard)
- `OWNED_BY` (Metric → Team)
- `DEPENDS_ON` (Metric → Metric)
- `TRACKS` (Event → DataSource)

**Temporal aspect (Graphiti bi-temporal model):**
- Every edge has `valid_from` and `valid_to` timestamps
- Enables queries like:
  - "How was DAU defined 3 months ago?"
  - "When did the data source for this metric change?"
  - "What relationships changed this week?"

#### D. Redis — Cache Layer (Phase 2+)

- Cache frequently accessed segments and retrieval results
- Session state for multi-turn conversations
- TTL-based invalidation aligned with sync intervals

> **Phase 1**: Use in-memory caching (e.g. `cachetools` or `lru_cache`) to keep infrastructure minimal. Introduce Redis when multi-instance scaling or persistent session state is required.

---

### 3.4 Layer 4: Retrieval & Reasoning

The **brain-facing interface** — an agent that orchestrates multi-step retrieval and reasoning.

> **Framework choice**: LangGraph provides the most control for complex state machines and multi-agent workflows. However, for a single-agent retrieval system, the **Claude Agent SDK** (or a simple tool-use loop) may be sufficient and significantly simpler. Evaluate complexity needs before committing — start simple, upgrade if needed.

#### Agent Architecture

```
User Query
    ↓
┌─────────────────────────────────────────┐
│           LangGraph Agent               │
│                                         │
│  State: {query, context[], citations[]} │
│                                         │
│  Tools:                                 │
│  ├── search_knowledge(query, filters)   │
│  │   → Elasticsearch hybrid search      │
│  │   → RRF fusion + reranking           │
│  │                                       │
│  ├── query_graph(question)              │
│  │   → Neo4j Cypher queries             │
│  │   → Temporal relationship lookups     │
│  │                                       │
│  ├── query_database(sql, target_db)     │
│  │   → Live SQL to BigQuery/Postgres     │
│  │   → Returns data + query as citation  │
│  │                                       │
│  ├── get_document_context(doc_id)       │
│  │   → Full document with sections       │
│  │                                       │
│  ├── get_change_history(entity, range)  │
│  │   → What changed in a time period     │
│  │                                       │
│  └── check_permissions(user, resource)  │
│      → Permission validation             │
│                                         │
│  Policies:                              │
│  - Every claim must have a citation     │
│  - Numeric claims must come from SQL    │
│  - Textual claims must cite doc/section │
│  - Never hallucinate metric definitions │
└─────────────────────────────────────────┘
    ↓
Response + Citations
```

#### Hybrid Retrieval Pipeline

```
Query
  ↓
  ├── Vector search (Elasticsearch dense_vector)
  ├── BM25 search (Elasticsearch full-text)
  └── Graph lookup (Neo4j — if entity/relationship query)
  ↓
Reciprocal Rank Fusion (RRF)
  ↓
Reranking (Cohere Rerank or cross-encoder)
  ↓
Permission filtering
  ↓
Top-K segments with citations
```

#### Reasoning Patterns

| Query Type | Strategy |
|---|---|
| "How is X defined?" | Knowledge search → cite document section |
| "Why did X drop?" | Graph lookup (dependencies) → change history → SQL for data → synthesize |
| "What changed last week?" | Change history query → graph diff → summarize |
| "Show me X metric" | SQL query → format result → cite query + source |
| "Compare X before and after" | Temporal graph query → two-point SQL → diff |

---

### 3.5 Layer 5: LLM Applications

#### Backend: FastAPI

- `/api/chat` — Multi-turn conversation with the knowledge layer
- `/api/search` — Direct knowledge search (non-conversational)
- `/api/ingest` — Trigger manual ingestion for a source
- `/api/status` — System health, freshness, sync status
- `/api/admin` — Document management, permissions, project config

#### Frontend: React

- Chat interface with citation rendering
- Source viewer (click citation → see original document context)
- Admin dashboard (ingestion status, document catalog, freshness)
- Knowledge graph explorer (visual relationships)

#### LLM: Claude (Sonnet 4.5 / Opus 4.6)

- Primary reasoning model
- Tool use for agent workflows
- Long context window for multi-document synthesis

---

## 4. Data Flow — End to End

```
1. Google Doc is updated
       ↓
2. Drive webhook fires → Ingestion service detects change
       ↓
3. Content hash compared → Document has changed
       ↓
4. Docling parses document → DoclingDocument (structured JSON)
       ↓
5. HybridChunker produces knowledge segments
       ↓
6. Segments embedded (text-embedding-3-large @ 1536 dims via Matryoshka truncation)
       ↓
7. Parallel writes:
   ├── Elasticsearch: segments + embeddings + BM25 index
   ├── PostgreSQL: metadata, version history, audit log
   └── Neo4j: entity relationships extracted from segments
       ↓
8. User asks: "Why did conversion drop last week?"
       ↓
9. LangGraph Agent:
   a. search_knowledge("conversion rate definition") → finds doc citation
   b. query_graph("conversion", "dependencies") → finds related metrics
   c. get_change_history("conversion", "last_week") → finds definition change
   d. query_database("SELECT date, conversion_rate FROM ...") → gets actual data
   e. Synthesizes answer with citations
       ↓
10. Response: "Conversion dropped 12% because the tracking definition
    changed on Jan 15 [Doc: Tracking Plan v3, Section 2.1].
    The event 'purchase_complete' was renamed to 'checkout_success'
    [Change Log: Jan 15]. Before the change, 7-day avg was 3.2%;
    after, it's 2.8% [SQL: analytics.conversion_daily]."
```

---

## 5. Deployment Architecture

```
┌──────────────────────────────────────────────────┐
│  Docker Compose (Development / Staging)           │
│  Kubernetes (Production)                          │
│                                                   │
│  Phase 1 Services:                                │
│  ├── pam-api        (FastAPI, agent)              │
│  ├── pam-web        (React frontend)              │
│  ├── pam-ingestion  (Sync workers, Docling)       │
│  ├── elasticsearch  (Vector + BM25 store)         │
│  └── postgresql     (Catalog + metadata)          │
│                                                   │
│  Added in Phase 2+:                               │
│  ├── pam-scheduler  (Cron jobs, webhook listener) │
│  └── redis          (Cache + session store)       │
│                                                   │
│  Added in Phase 3+:                               │
│  └── neo4j          (Knowledge graph)             │
└──────────────────────────────────────────────────┘
```

---

## 6. Security & Access Control

- **Project-scoped access**: Every segment belongs to a project; users only see segments from their projects
- **Permission model**: RBAC with roles (viewer, editor, admin) per project
- **API authentication**: JWT tokens via OAuth2 (Google Workspace SSO)
- **Data at rest**: Elasticsearch encryption, PostgreSQL encryption
- **Audit logging**: All queries and access logged in PostgreSQL

---

## 7. Evaluation & Observability

Quality measurement and system observability should be present **from Phase 1**, not deferred.

### Retrieval Quality (Phase 1+)

- Maintain a curated set of **20-30 question/answer pairs** from real business documents
- Automated retrieval recall/precision measurement on each deploy
- Track metrics: retrieval recall@k, answer faithfulness, citation accuracy
- Use LLM-as-judge for answer quality scoring on the evaluation set

### Observability (Phase 1+)

- **Structured logging** (structlog → JSON) from day 1
- **Request tracing**: log every agent step (tool calls, retrieval results, LLM calls) with correlation IDs
- **Basic metrics**: query latency (p50/p95/p99), ingestion throughput, error rates
- **Cost tracking**: log token usage per query to monitor LLM spend

### Advanced Observability (Phase 4)

- Prometheus + Grafana dashboards
- OpenTelemetry distributed tracing
- Alerting on stale documents, failed ingestions, latency spikes

### Chunking Strategy

Chunk size is a critical retrieval hyperparameter. The system should support **configurable chunk sizes** from the start:
- Default: 512 tokens (good balance of specificity and context)
- Plan to A/B test 256 vs 512 vs 1024 tokens using the evaluation framework
- Measure retrieval recall at each size to find the optimal setting for the specific document corpus
