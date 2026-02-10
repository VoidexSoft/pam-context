# PAM Context — Implementation Plan

## Phasing Strategy

The system is built in **4 phases**, each delivering usable functionality. Each phase builds on the previous one, and the system is usable after Phase 1.

```
Phase 1: Foundation (MVP)           — 4-5 weeks
Phase 2: Full Knowledge Layer       — 3-4 weeks
Phase 3: Knowledge Graph & History  — 2-3 weeks
Phase 4: Production Hardening       — 2-3 weeks
```

---

## Phase 1: Foundation (MVP)

**Goal**: Ingest Google Docs and Markdown, store in Elasticsearch, answer questions with citations.

### 1.1 Project Setup

- [x] Initialize Python monorepo structure
- [x] Set up Docker Compose with Elasticsearch, PostgreSQL (Redis deferred to Phase 2)
- [x] Configure environment variables and secrets management
- [x] Set up CI/CD pipeline (GitHub Actions)

```
pam-context/
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
├── packages/
│   ├── pam-ingestion/       # Ingestion workers
│   │   ├── src/
│   │   │   ├── connectors/  # Source connectors
│   │   │   ├── parsers/     # Document parsers
│   │   │   ├── chunkers/    # Chunking logic
│   │   │   ├── embedders/   # Embedding pipeline
│   │   │   └── stores/      # Storage writers
│   │   └── tests/
│   ├── pam-api/             # FastAPI backend
│   │   ├── src/
│   │   │   ├── routes/      # API endpoints
│   │   │   ├── agent/       # LangGraph agent
│   │   │   ├── retrieval/   # Retrieval logic
│   │   │   ├── auth/        # Authentication
│   │   │   └── models/      # Pydantic models
│   │   └── tests/
│   ├── pam-web/             # React frontend
│   │   ├── src/
│   │   │   ├── components/
│   │   │   ├── pages/
│   │   │   └── hooks/
│   │   └── package.json
│   └── pam-common/          # Shared types, utilities
│       ├── src/
│       │   ├── models/      # Shared data models
│       │   ├── config/      # Configuration
│       │   └── utils/       # Shared utilities
│       └── tests/
├── docs/
├── scripts/                 # Setup, migration, seed scripts
└── infra/                   # Kubernetes manifests (Phase 4)
```

### 1.2 Data Models (PostgreSQL)

- [x] `documents` table — source document registry
- [x] `segments` table — knowledge segments with provenance
- [x] `sync_log` table — ingestion audit trail
- [x] `projects` table — project scoping
- [x] Alembic migrations setup

```sql
-- Core tables
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_type VARCHAR(50) NOT NULL,  -- 'google_doc', 'markdown', 'sheet'
    source_id VARCHAR(500) NOT NULL,   -- Google Doc ID, file path
    source_url TEXT,
    title TEXT NOT NULL,
    owner VARCHAR(200),
    project_id UUID REFERENCES projects(id),
    content_hash VARCHAR(64),          -- SHA-256
    status VARCHAR(20) DEFAULT 'active',
    last_synced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_type, source_id)
);

CREATE TABLE segments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    segment_type VARCHAR(50) NOT NULL, -- 'text', 'table', 'code'
    section_path TEXT,                 -- 'Section 2 > Subsection 2.1'
    position INTEGER NOT NULL,
    version INTEGER DEFAULT 1,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE sync_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id),
    action VARCHAR(50) NOT NULL,       -- 'created', 'updated', 'deleted'
    segments_affected INTEGER,
    details JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
```

### 1.3 Google Docs Connector

- [x] OAuth2 setup with Google Workspace
- [x] Google Drive API: list documents in configured folders
- [ ] Google Drive API: watch for changes (webhooks) *(deferred — manual trigger only for Phase 1)*
- [x] Export Google Docs as DOCX (for Docling processing)
- [x] Content hash comparison for change detection

### 1.4 Docling Parsing Pipeline

- [x] Install and configure Docling with models
- [x] Parse DOCX/PDF → DoclingDocument
- [x] Extract hierarchical sections, tables, code blocks
- [x] HybridChunker configuration (**configurable** token target, default 512, structural awareness)
- [x] Chunk size as environment variable for A/B testing (256 / 512 / 1024)
- [x] Map Docling output to KnowledgeSegment model

### 1.5 Embedding Pipeline

- [x] Abstracted embedding interface (swap models without code changes)
- [x] OpenAI embedding client setup (text-embedding-3-large @ **1536 dims** via Matryoshka truncation)
- [x] Batch embedding with rate limiting and retries
- [x] Embedding cache (avoid re-embedding unchanged segments)

### 1.6 Elasticsearch Setup

- [x] Index template with vector + text fields
- [x] Bulk indexing pipeline for segments
- [x] Basic hybrid search (vector + BM25 + RRF)
- [x] Filter by project, source_type, date

### 1.7 Retrieval Agent (Basic)

> **Framework decision**: Evaluate Claude Agent SDK (simpler, native Claude integration) vs LangGraph (more control, steeper learning curve) before implementation. For Phase 1's single-agent retrieval, a simple tool-use loop or Claude Agent SDK is likely sufficient.

- [x] Evaluate agent framework (Claude Agent SDK vs LangGraph vs simple tool loop) *(chose simple tool-use loop with Anthropic SDK)*
- [x] Agent with single tool: `search_knowledge`
- [x] Hybrid retrieval → top-K segments
- [x] Response generation with Claude (Sonnet 4.5 for simple lookups, Opus for complex reasoning)
- [x] Citation formatting (link back to source document + section)

### 1.8 FastAPI Backend (Basic)

- [x] `POST /api/chat` — conversational Q&A
- [x] `POST /api/search` — direct search
- [x] `GET /api/documents` — list ingested documents
- [x] `POST /api/ingest` — trigger manual ingestion
- [x] Basic error handling and logging

### 1.9 React Frontend (Basic)

- [x] Chat interface with message history
- [x] Citation rendering (clickable links to source)
- [x] Document list view
- [x] Manual ingestion trigger

### 1.10 Evaluation Framework (Minimal)

- [x] Curate 20-30 question/answer pairs from real business documents *(10 pairs created, aligned with seed test docs)*
- [x] Automated retrieval recall@k measurement script
- [x] LLM-as-judge scoring for answer quality (run on evaluation set)
- [ ] CI integration: run evaluation on each deploy, fail on regression

### 1.11 Basic Observability

- [x] Structured logging with structlog (JSON output)
- [x] Request correlation IDs across agent steps
- [x] Log every tool call, retrieval result count, and LLM token usage
- [x] Query latency tracking (p50/p95/p99)
- [x] LLM cost tracking: log token usage per query for spend monitoring

### Phase 1 Deliverable

A working system that:
- Ingests Google Docs and Markdown files
- Parses them with Docling into structured chunks (configurable chunk size)
- Stores in Elasticsearch (vector + BM25) and PostgreSQL (metadata)
- Answers questions with hybrid retrieval and citations
- Basic web UI for interaction
- Retrieval quality measured against curated evaluation set
- Structured logging and cost tracking from day 1

---

## Phase 2: Full Knowledge Layer

**Goal**: Add Google Sheets, reranking, permissions, and richer retrieval.

### 2.1 Google Sheets Connector & Parser

> **High-risk component**: The region detection (table vs. notes vs. config) is the most novel and risky custom component. Run a **dedicated spike/prototype** on 5-10 real sheets before committing to the full implementation.

- [ ] **Spike**: Prototype region detection on real business sheets (1-2 days)
- [ ] Define explicit failure modes: what happens when detection is ambiguous?
- [ ] Google Sheets API: read sheet data with formatting
- [ ] Region detection: table vs. notes vs. config sections
- [ ] Consider LLM-assisted schema inference (have Claude analyze sheet structure)
- [ ] Schema inference per table region
- [ ] Cell notes and named ranges extraction
- [ ] Multi-tab support
- [ ] Convert to KnowledgeSegment with table-specific metadata

### 2.2 Redis Cache Layer

- [ ] Add Redis to Docker Compose
- [ ] Cache frequently accessed segments and retrieval results
- [ ] Session state for multi-turn conversations
- [ ] TTL-based invalidation aligned with sync intervals
- [ ] Replace in-memory caching from Phase 1

### 2.3 Reranking Pipeline

- [ ] Integrate Cohere Rerank API (or self-hosted cross-encoder)
- [ ] Add reranking step after RRF fusion
- [ ] A/B test retrieval quality with and without reranking
- [ ] Configurable reranking model per project

### 2.4 Permission System

- [ ] RBAC model: roles (viewer, editor, admin) per project
- [ ] JWT authentication with Google OAuth2 SSO
- [ ] Permission-scoped retrieval (filter segments by user's projects)
- [ ] API middleware for auth enforcement
- [ ] Admin endpoints for user/project management

### 2.5 Enhanced Agent Tools

- [ ] `query_database` tool — text-to-SQL for analytics databases
  - [ ] BigQuery connector
  - [ ] PostgreSQL analytics connector
  - [ ] SQL generation with schema awareness
  - [ ] Result formatting and citation
- [ ] `get_document_context` tool — fetch full document for deep reading
- [ ] `get_change_history` tool — query sync_log for recent changes

### 2.6 LangExtract Integration (Entity Extraction)

- [ ] Define extraction schemas for business entities:
  - Metric definitions (name, formula, owner, data source)
  - Event tracking specs (event name, properties, trigger)
  - KPI targets (metric, target value, period, owner)
- [ ] Run extraction on Docling output
- [ ] Store extracted entities in PostgreSQL
- [ ] Source grounding: link every entity to its origin segment

### 2.7 Frontend Enhancements

- [ ] Source viewer (click citation → see original context)
- [ ] Admin dashboard (ingestion status, document freshness)
- [ ] Search filters (project, date range, source type)
- [ ] Multi-turn conversation support

### Phase 2 Deliverable

- Google Sheets fully supported as a data source
- Redis cache layer for retrieval results and session state
- Reranked hybrid retrieval with measurable quality improvement
- Permission-scoped access per project
- SQL queries against analytics databases
- Entity extraction populating structured catalog

---

## Phase 3: Knowledge Graph & Temporal Reasoning

**Goal**: Add Neo4j knowledge graph for relationship modeling and "what changed and why" reasoning.

### 3.1 Neo4j Setup

- [ ] Docker service for Neo4j Community
- [ ] Schema design: node types, edge types, constraints
- [ ] Graphiti integration for bi-temporal data model
- [ ] Python driver setup (`neo4j` package + `graphiti-core`)

### 3.2 Entity-to-Graph Pipeline

- [ ] Map extracted entities (from LangExtract) to graph nodes
- [ ] Extract relationships from document context:
  - Metric → defined in → Document
  - Metric → sourced from → DataSource
  - Metric → displayed on → Dashboard
  - Metric → owned by → Team
  - Metric → depends on → Metric
- [ ] Temporal edge creation with valid_from/valid_to
- [ ] Incremental graph updates on document change

### 3.3 Graph-Aware Retrieval

- [ ] `query_graph` agent tool — Cypher queries for relationships
- [ ] "What depends on X?" queries
- [ ] "What changed about X since date Y?" queries
- [ ] Graph context injection into retrieval pipeline

### 3.4 Change Detection & History

- [ ] Diff engine: compare old vs new segments on re-ingestion
- [ ] Classify changes: definition change, ownership change, new metric, deprecated metric
- [ ] Graph edge versioning: close old edges, create new edges with timestamps
- [ ] `get_change_history` enhanced with graph-level changes

### 3.5 Frontend: Knowledge Graph Explorer

- [ ] Visual graph explorer (D3.js or vis.js)
- [ ] Browse metric → definition → dashboard relationships
- [ ] Timeline view: see how an entity evolved over time

### Phase 3 Deliverable

- Knowledge graph modeling business entity relationships
- Temporal reasoning: "what changed and why"
- Visual graph explorer in the UI
- Agent can trace causal chains across documents and data

---

## Phase 4: Production Hardening

**Goal**: Make the system production-ready, reliable, and observable.

### 4.1 Deployment

- [ ] Kubernetes manifests (Deployments, Services, Ingress)
- [ ] Helm chart for configurable deployment
- [ ] Production Elasticsearch cluster (3-node minimum)
- [ ] Database backups (PostgreSQL, Neo4j)
- [ ] Secret management (Vault or cloud KMS)

### 4.2 Advanced Observability

> Basic structured logging, cost tracking, and latency metrics are established in Phase 1. This phase adds production-grade monitoring infrastructure.

- [ ] Metrics (Prometheus): ingestion throughput, retrieval latency, cache hit rate
- [ ] Tracing (OpenTelemetry): end-to-end distributed tracing through agent steps
- [ ] Dashboards (Grafana): system health, freshness, quality metrics
- [ ] Alerting: stale documents, failed ingestions, high error rate, cost anomalies

### 4.3 Reliability

- [ ] Retry logic with exponential backoff (tenacity)
- [ ] Circuit breakers for external APIs (LLM, embedding, Google)
- [ ] Graceful degradation: if graph is down, fall back to search-only
- [ ] Rate limiting on API endpoints
- [ ] Health check endpoints for all services

### 4.4 Quality & Testing

- [ ] Retrieval quality evaluation framework
  - Curated question-answer pairs
  - Automated retrieval recall/precision measurement
  - LLM-as-judge for answer quality
- [ ] Integration tests for full ingestion pipeline
- [ ] Load testing for concurrent query handling
- [ ] Regression tests for parser accuracy

### 4.5 Documentation & Onboarding

- [ ] API documentation (auto-generated from FastAPI)
- [ ] User guide for the web UI
- [ ] Admin guide for adding sources and managing projects
- [ ] Architecture decision records (ADRs) for key choices

### Phase 4 Deliverable

- Production-ready deployment on Kubernetes
- Full observability stack
- Quality evaluation framework
- Documented system ready for team handoff

---

## Milestone Summary

| Phase | Key Outcome | Dependencies |
|---|---|---|
| **Phase 1** | Working MVP: Docs → Search → Q&A with citations | None |
| **Phase 2** | Full knowledge layer: Sheets, SQL, permissions, entities | Phase 1 |
| **Phase 3** | Temporal reasoning: knowledge graph, change tracking | Phase 2 (entity extraction) |
| **Phase 4** | Production-ready with observability and testing | Phase 1-3 |

---

## Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Docling model accuracy on specific doc formats | Medium | Test early with real business docs; fallback to LlamaParse API |
| Elasticsearch resource consumption | Medium | Start with single node; monitor and scale horizontally |
| Google API rate limits | Low | Batch operations, exponential backoff, caching |
| Neo4j complexity for small team | Medium | Defer to Phase 3; system works without it |
| LLM cost at scale | **High** | Cache frequent queries; use Sonnet 4.5 for simple queries, Opus for complex; **monitor token usage per query from Phase 1** — expect $500-1500/mo at 1K queries/day with tool use |
| Embedding model vendor lock-in | Low | Abstracted embedding interface from Phase 1; can swap models |
| Google Sheets region detection | **Medium-High** | Dedicated spike/prototype before full implementation; define failure modes; consider LLM-assisted parsing |
| Chunk size suboptimal for corpus | Medium | Configurable chunk size; A/B test with evaluation framework |

---

## Getting Started (Phase 1, Step 1)

```bash
# Clone and setup
cd pam-context
python -m venv .venv
source .venv/bin/activate

# Install core dependencies
pip install docling langchain langgraph elasticsearch psycopg[binary] \
    redis fastapi uvicorn anthropic openai google-api-python-client \
    google-auth-oauthlib python-dotenv structlog pydantic alembic

# Start infrastructure (Phase 1: no Redis needed)
docker compose up -d elasticsearch postgresql

# Run initial migration
alembic upgrade head

# Start the API server
uvicorn pam_api.main:app --reload
```
