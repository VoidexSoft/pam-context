# External Integrations

**Analysis Date:** 2025-02-15

## APIs & External Services

**LLM & Embeddings:**
- **Claude API (Anthropic)** - Agent reasoning and response generation
  - SDK/Client: `anthropic>=0.40`
  - Auth: `ANTHROPIC_API_KEY` environment variable
  - Model: `AGENT_MODEL=claude-sonnet-4-5-20250514` (configurable)
  - Implementation: `src/pam/agent/agent.py` RetrievalAgent class
  - Features: Tool-use loop, streaming responses, token counting
  - Cost tracking: Via `CostTracker` (logs input/output tokens, latency)

- **OpenAI Embeddings API** - Text-to-vector conversion for semantic search
  - SDK/Client: `openai>=1.50`
  - Auth: `OPENAI_API_KEY` environment variable
  - Model: `EMBEDDING_MODEL=text-embedding-3-large` (configurable, 1536 dims)
  - Implementation: `src/pam/ingestion/embedders/openai_embedder.py`
  - Features: Batched requests (batch size 100), retry with exponential backoff, in-memory LRU cache (10k entries, content-hash keyed)
  - Cost tracking: Tokens counted and logged per embedding batch

**Google Workspace APIs:**
- **Google Drive API v3** - Enumerate and list documents
  - Client: `google-api-python-client>=2.0`
  - Auth: `google-auth-oauthlib>=1.0` (OAuth2 credentials flow)
  - Credentials: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
  - Implementation: `src/pam/ingestion/connectors/google_docs.py`, `src/pam/ingestion/connectors/google_sheets.py`
  - Scope: List Google Docs in folders, export as DOCX for parsing
  - Note: Phase 1 uses manual trigger only (no webhooks)

## Data Storage

**Databases:**
- **PostgreSQL 16** - Primary OLTP database
  - Connection: `DATABASE_URL=postgresql+psycopg://pam:pam@localhost:5432/pam_context` (env var)
  - Client: `psycopg[binary]>=3.0` (async-capable driver)
  - ORM: SQLAlchemy 2.0+ with async session factory in `src/pam/common/database.py`
  - Schema: Managed via Alembic migrations in `alembic/versions/`
  - Key Tables: `documents`, `segments`, `users`, `user_project_roles`, `extracted_entities`, `sync_log`, `ingestion_tasks`, `projects`
  - JSONB columns: `segments.metadata`, `extracted_entities.entity_data`, `sync_log.details` (for extensible metadata)

- **Elasticsearch 8.15** - Vector search index
  - Connection: `ELASTICSEARCH_URL=http://localhost:9200` (env var)
  - Client: `elasticsearch[async]>=8.0`
  - Index: `pam_segments` (configurable via `ELASTICSEARCH_INDEX`)
  - Index Mapping: Haystack-compatible schema with nested `meta.*` metadata
    - Fields: `content` (text), `embedding` (dense_vector, cosine similarity), `meta.segment_id`, `meta.document_id`, `meta.source_type`, `meta.source_url`, `meta.document_title`, `meta.section_path`, etc.
  - Bulk Indexing: Via bulk API with `refresh="wait_for"` (synchronous ingestion)
  - Search Methods: Reciprocal Rank Fusion (RRF) combining kNN + BM25 in `src/pam/retrieval/hybrid_search.py`
  - Optional Backend: Haystack 2.9+ pipeline (disabled by default, enable via `USE_HAYSTACK_RETRIEVAL=true`)

**Caching:**
- **Redis 7** - Multi-purpose cache
  - Connection: `REDIS_URL=redis://localhost:6379/0` (env var)
  - Client: `redis[hiredis]>=5.0` (async, with C parser for speed)
  - Implementation: `src/pam/common/cache.py` CacheService class
  - Data Retained:
    - Search results: TTL 15 minutes (`REDIS_SEARCH_TTL=900`)
    - Segment metadata: TTL 1 hour (`REDIS_SEGMENT_TTL=3600`)
    - Conversation sessions: TTL 24 hours (`REDIS_SESSION_TTL=86400`)
  - Cache Keys: Deterministic SHA256-based keys for search (16-char digest)
  - Fallback: Optional (app works without Redis, logs warning on connection failure)

**Analytics:**
- **DuckDB 1.0+** - Optional in-process SQL over data files
  - Implementation: `src/pam/agent/duckdb_service.py`
  - Supported Formats: CSV, Parquet, JSON
  - Configuration: `DUCKDB_DATA_DIR` (base directory for registered files), `DUCKDB_MAX_ROWS=1000` (query limit)
  - Access: Via agent tool `query_database` (executes SQL, returns results as formatted table)
  - Note: Not deployed to cloud; local files only

## Authentication & Identity

**Auth Provider:**
- **Custom JWT** (Phase 1, optional)
  - Implementation: `src/pam/api/routes/auth.py`
  - Algorithm: HS256 (configurable via `JWT_ALGORITHM`)
  - Secret: `JWT_SECRET` (min 32 chars when `AUTH_REQUIRED=true`)
  - Expiry: `JWT_EXPIRY_HOURS=24` (configurable)
  - Database: User table in PostgreSQL with email uniqueness constraint
  - Tokens: Bearer token in `Authorization: Bearer <token>` header
  - Status: Optional (disabled by default: `AUTH_REQUIRED=false`; Phase 1 has no built-in login UI)

- **Google OAuth2** (Prepared, not implemented in Phase 1)
  - Credentials: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
  - Callback: `/api/auth/callback`
  - Purpose: User creation/linking via Google identity

**Authorization:**
- RBAC model in PostgreSQL: `user_project_roles` table with roles (viewer, editor, admin)
- Middleware: Not enforced in Phase 1 (see warning in `src/pam/api/main.py` lifespan)

## Monitoring & Observability

**Error Tracking:**
- Not integrated (no Sentry, Datadog, etc.)
- Errors logged via structlog to stderr

**Logs:**
- **structlog** for structured JSON logging
  - Configuration: `src/pam/common/logging.py` (log level via `LOG_LEVEL` env var, defaults to INFO)
  - Correlation IDs: Via `contextvars` per-request (middleware `CorrelationIdMiddleware` in `src/pam/api/middleware.py`)
  - Cost tracking: Token usage and latencies logged for LLM/embedding calls via `CostTracker`
  - Test markers: `pytest.mark.integration` for tests requiring external services (ES, PG)

**Performance Metrics:**
- Token counting: Anthropic and OpenAI API responses include usage metadata
- Latency tracking: Per-API call latencies in milliseconds logged to structlog

## CI/CD & Deployment

**Hosting:**
- Docker container deployment (backend at port 8000)
- Assumes PostgreSQL, Elasticsearch, Redis available (env vars configure URLs)
- Frontend: Static SPA build deployable to CDN/web server

**CI Pipeline:**
- `.pre-commit-config.yaml` - Local git hooks (ruff format/lint on commit)
- `.github/` directory exists (workflows not examined in this analysis)

## Environment Configuration

**Critical Environment Variables:**
- `DATABASE_URL` - PostgreSQL connection string (async driver)
- `ELASTICSEARCH_URL` - Elasticsearch cluster endpoint
- `OPENAI_API_KEY` - OpenAI API key (secret)
- `ANTHROPIC_API_KEY` - Anthropic API key (secret)
- `REDIS_URL` - Redis connection string
- `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` - Google OAuth2 credentials (if using Google connectors)
- `AUTH_REQUIRED` - Boolean: enforce JWT auth on all routes (default false)
- `JWT_SECRET` - HS256 signing key (min 32 chars if auth required)
- `EMBEDDING_MODEL` - OpenAI model name (default: text-embedding-3-large)
- `AGENT_MODEL` - Claude model name (default: claude-sonnet-4-5-20250514)
- `CHUNK_SIZE_TOKENS` - Docling chunk size for ingestion (default: 512)
- `USE_HAYSTACK_RETRIEVAL` - Boolean: enable Haystack backend (default false)
- `RERANK_ENABLED` - Boolean: enable cross-encoder reranking (default false)
- `RERANK_MODEL` - Cross-encoder model (default: cross-encoder/ms-marco-MiniLM-L-6-v2)
- `DUCKDB_DATA_DIR` - Directory for analytics data files (optional)
- `LOG_LEVEL` - Logging level (default: INFO)
- `CORS_ORIGINS` - JSON list of allowed origins (default: ["http://localhost:5173"])

**Secrets Location:**
- `.env` file (Git-ignored, see `.gitignore`)
- See `.env.example` for template with placeholders

## Webhooks & Callbacks

**Incoming:**
- `/api/auth/callback` - Google OAuth2 redirect URI
- No other webhooks in Phase 1 (connectors use manual trigger)

**Outgoing:**
- None (no push notifications or external event dispatch)

## Document Connectors

**Implemented:**
- **Markdown Files** - Local filesystem path ingestion via `MarkdownConnector`
- **Google Docs** - Via Drive API export-as-DOCX workflow
- **Google Sheets** - Listed documents via Sheets API (data ingestion prep)
- **Folders** - Recursive directory scanner via `FolderConnector` with `INGEST_ROOT` path validation

**Parsing Pipeline:**
- Raw bytes → `docling.DocumentConverter` → `DoclingDocument` (structured)
- Chunking: `docling.HybridChunker` (hybrid text + layout chunking)
- Embedding: OpenAI embeddings API with batching/caching
- Storage: PostgreSQL (document + segments) + Elasticsearch (indexed segments)

## Data Format Compatibility

**Supported Input Formats:**
- DOCX (Microsoft Word) - via Docling
- PDF - via Docling
- Markdown (.md) - via Docling
- JSON, CSV, Parquet - for DuckDB analytics (optional)

**API Response Formats:**
- JSON - All REST endpoints
- Server-Sent Events (SSE) - Streaming agent responses (`/api/chat/stream` endpoint)

## Feature Flags & Optional Components

- `USE_HAYSTACK_RETRIEVAL` - Toggle legacy hybrid_search vs. Haystack 2.x pipeline
- `RERANK_ENABLED` - Enable/disable cross-encoder reranking post-search
- `AUTH_REQUIRED` - Toggle authentication enforcement
- `DUCKDB_DATA_DIR` - Enable/disable analytics query tool
- Redis optional - App gracefully degrades without cache (warning logged)

---

*Integration audit: 2025-02-15*
