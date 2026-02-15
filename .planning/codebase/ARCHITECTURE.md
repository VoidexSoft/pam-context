# Architecture

**Analysis Date:** 2026-02-15

## Pattern Overview

**Overall:** Multi-layer business knowledge system with clear separation between ingestion, retrieval, and presentation.

**Key Characteristics:**
- Async-first Python backend (FastAPI + SQLAlchemy) with dual-store architecture (PostgreSQL + Elasticsearch)
- Tool-based agent loop using Anthropic SDK for knowledge retrieval with citations
- Document-centric data model: raw documents → parsed chunks → embeddings → hybrid search
- Per-request service instantiation for thread-safe agent use across concurrent requests
- Modular ingestion pipeline with composable connectors, parsers, chunkers, and embedders

## Layers

**Presentation Layer:**
- Purpose: User-facing interfaces for chat and document management
- Location: `web/` (React 18 + TypeScript)
- Contains: Chat interface, document list, search filters, citation tooltips, streaming SSE handlers
- Depends on: API routes in `/api/*`
- Used by: End users

**API/Routing Layer:**
- Purpose: HTTP endpoints orchestrating requests and responses
- Location: `src/pam/api/routes/*.py` (chat, search, documents, ingest, admin, auth)
- Contains: Request/response schemas, endpoint handlers, streaming logic
- Depends on: Agent, Search Service, Auth, Database
- Entry points:
  - `POST /api/chat` — conversational Q&A with citations
  - `POST /api/chat/stream` — streaming chat via SSE
  - `POST /api/search` — semantic search with optional filtering
  - `GET/POST /api/documents` — document CRUD
  - `POST /api/ingest` — submit ingestion task
  - `GET /api/health` — service health check

**Agent Layer:**
- Purpose: Tool-use loop implementing Claude-driven knowledge retrieval
- Location: `src/pam/agent/agent.py`
- Contains: `RetrievalAgent` class managing multi-turn tool interactions, citation tracking
- Depends on: Search Service, Embedder, DuckDB Service, Database
- Tools exposed: `search_knowledge`, `get_document_context`, `get_change_history`, `query_database`, `search_entities`
- Pattern: Simple imperative loop (~180 lines), NOT LangGraph; state held in message history

**Retrieval Layer:**
- Purpose: Search and ranking over indexed documents
- Location: `src/pam/retrieval/`
- Contains:
  - `HybridSearchService`: Legacy RRF-based ES search combining BM25 + kNN vectors
  - `HaystackSearchService`: Optional Haystack 2.x pipeline backend (toggled via `USE_HAYSTACK_RETRIEVAL`)
  - `CrossEncoderReranker`: Optional cross-encoder reranking (toggled via `RERANK_ENABLED`)
  - `CacheService`: Redis-backed search result caching
- Depends on: Elasticsearch, PostgreSQL (for Haystack), Redis (optional)
- Used by: Agent, Search routes

**Ingestion Layer:**
- Purpose: Multi-stage pipeline converting raw documents to searchable knowledge
- Location: `src/pam/ingestion/`
- Contains: Pipeline orchestrator, connectors, parsers, chunkers, embedders, stores
- Flow:
  1. **Connectors** (`connectors/`): List and fetch raw documents from sources (Markdown, Google Docs, Google Sheets)
  2. **Parser** (`parsers/docling_parser.py`): Convert to DoclingDocument (layout-aware)
  3. **Chunker** (`chunkers/hybrid_chunker.py`): Split into semantic chunks with section paths
  4. **Embedder** (`embedders/openai_embedder.py`): Generate vector embeddings (cached by content hash)
  5. **Stores**: Write to PostgreSQL (authoritative) then Elasticsearch (search index)
- Depends on: External APIs (Google, OpenAI), Docling library
- Used by: Ingest routes, background task manager

**Data Layer:**
- Purpose: Persistent storage and state management
- Location: `src/pam/common/database.py`, `src/pam/common/models.py`
- Contains:
  - PostgreSQL ORM models: `Document`, `Segment`, `Project`, `User`, `IngestionTask`, `SyncLog`, `ExtractedEntity`
  - Elasticsearch index mapping with nested metadata under `meta.*` (Haystack-compatible)
  - Redis caching for search results and session state
- Depends on: SQLAlchemy async, psycopg, elasticsearch-py, redis
- Used by: All layers reading/writing data

**Configuration/Common Layer:**
- Purpose: Shared utilities and configuration
- Location: `src/pam/common/`
- Contains:
  - `config.py`: Pydantic Settings with env var validation (database URL, API keys, feature flags)
  - `logging.py`: structlog configuration with correlation IDs via contextvars
  - `cache.py`: Redis client and CacheService wrapper
  - `utils.py`: Helpers like `escape_like` for SQL injection prevention
  - `database.py`: Lazy-initialized async engine and session factory with proxy pattern
- Depends on: Pydantic, structlog, sqlalchemy
- Used by: All layers

## Data Flow

**Document Ingestion:**

1. Client calls `POST /api/ingest` with folder path
2. Ingest route creates `IngestionTask` record, spawns background task via `asyncio.create_task()`
3. Background task runs `IngestionPipeline.ingest_all()`:
   - Connector lists documents from source
   - For each document:
     - Fetch raw content, compute SHA-256 hash
     - Skip if hash matches existing document
     - Parse with Docling → DoclingDocument
     - Chunk with HybridChunker → list[ChunkResult]
     - Embed chunks with OpenAIEmbedder (batched, cached by content hash)
     - Build KnowledgeSegment objects with embeddings
     - Write to PostgreSQL (document + segments)
     - Commit transaction (PG is authoritative)
     - Attempt write to Elasticsearch (if fails, logs error but doesn't fail overall)
     - Log sync event to sync_log table
4. Task status polls via `GET /api/ingest/{task_id}` update UI in real-time

**Document Search/Retrieval:**

1. Client calls `POST /api/chat` with question
2. Chat route depends on `get_agent()` which instantiates fresh `RetrievalAgent` per request
3. RetrievalAgent enters tool-use loop (max 5 iterations):
   - Sends question + message history to Claude with ALL_TOOLS available
   - Claude chooses tools and parameters based on question
   - Agent executes tool:
     - **search_knowledge**: Embed query, call HybridSearchService.search() (RRF on ES), extract citations
     - **get_document_context**: Query PostgreSQL for full document, fetch segments by title/source_id
     - **get_change_history**: Query sync_log for recent ingestion events
     - **query_database**: Execute read-only SQL on DuckDB-registered data files (CSV/Parquet/JSON)
     - **search_entities**: Search ExtractedEntity table by type/term
   - Appends tool results to message history, loops until Claude stops with `end_turn`
4. Agent returns AgentResponse with answer text, citations, token usage
5. Chat route returns ChatResponse or streams via SSE with citation events

**Search Result Caching:**

- HybridSearchService checks Redis cache before querying Elasticsearch
- Cache key includes query, top_k, source_type, project, date range
- TTL: 15 minutes (configurable via REDIS_SEARCH_TTL)
- Cache invalidated on re-ingestion of same document

**State Management:**

- **Request state**: Agent instance + DB session per request (FastAPI Depends)
- **Message history**: Maintained in-memory by client, passed in ChatRequest
- **Background task state**: Persisted in IngestionTask table, polled via API
- **Configuration state**: Loaded from .env into Settings on app startup (cached via @lru_cache)

## Key Abstractions

**BaseConnector:**
- Purpose: Document source abstraction
- Examples: `MarkdownConnector`, `GoogleDocsConnector`, `GoogleSheetsConnector`
- Pattern: Async methods `list_documents()`, `fetch_document()`, `get_content_hash()`
- Location: `src/pam/ingestion/connectors/base.py` and implementations

**BaseEmbedder:**
- Purpose: Embedding model abstraction
- Examples: `OpenAIEmbedder`
- Pattern: `embed_texts()`, optional `embed_texts_with_cache()` override
- Location: `src/pam/ingestion/embedders/base.py` and implementations

**BaseReranker:**
- Purpose: Reranking model abstraction
- Examples: `CrossEncoderReranker`
- Pattern: `rerank()` method takes search results and returns reranked list
- Location: `src/pam/retrieval/rerankers/base.py` and implementations

**KnowledgeSegment (ORM model):**
- Purpose: Represents a single indexed text chunk with embedding
- Fields: content, content_hash, embedding, source_type, source_id, source_url, section_path, segment_type, position, document_id
- Location: `src/pam/common/models.py`
- Used by: Ingestion stores, retrieval results

**SearchResult (Pydantic model):**
- Purpose: Standardized retrieval result with metadata
- Fields: segment_id, content, score, source_url, source_id, section_path, document_title, segment_type
- Location: `src/pam/retrieval/types.py`
- Used by: Agent, search routes, client citation display

**AgentResponse (dataclass):**
- Purpose: Final answer with citations and usage
- Fields: answer, citations (list[Citation]), token_usage, latency_ms, tool_calls
- Location: `src/pam/agent/agent.py`
- Used by: Chat route to build ChatResponse

## Entry Points

**Web Frontend:**
- Location: `web/src/main.tsx`
- Renders: `<App />` (React component tree)
- Bootstrap: Vite dev server or built SPA in `web/dist/`

**FastAPI Backend:**
- Location: `src/pam/api/main.py`
- Entry: `create_app()` factory function returns FastAPI instance with lifespan, middleware, routes
- Startup: Initializes Elasticsearch client, creates index if needed; Redis optional; cleans orphaned tasks
- Shutdown: Closes ES client, Redis connection
- Command: `uvicorn pam.api.main:app --host 0.0.0.0 --port 8000`

**Database Migrations:**
- Location: `alembic/` directory with `env.py` and `versions/`
- Command: `alembic upgrade head` to apply all migrations
- Used by: Ingest routes (check DB schema exists before use)

**Background Ingestion:**
- Location: `src/pam/ingestion/task_manager.py`
- Triggered by: `/api/ingest` route calling `spawn_ingestion_task()`
- Execution: `asyncio.create_task()` in FastAPI event loop (not a separate queue/worker)

## Error Handling

**Strategy:** Async exception propagation with structured logging and graceful degradation.

**Patterns:**

- **Ingestion**: Each document errors logged but pipeline continues; IngestionResult includes `error` field; ES write failure doesn't fail overall (PG is source of truth)
- **Agent**: Tool execution errors caught, formatted as tool result text; max iterations trigger fallback response
- **API routes**: HTTPException for validation/auth errors; 500 for unexpected exceptions; logged with structlog
- **Streaming**: SSE generators yield error events on exception; client receives partial response
- **Search**: Cache miss gracefully falls back to ES query; ES timeout returns cached results or empty list

**Logging:**
- Framework: structlog with JSON output in production
- Correlation ID: Injected via `CorrelationIdMiddleware` using contextvars; propagated to all logs within a request
- Key events: pipeline_fetch, pipeline_complete, pipeline_error, agent_tool_call, hybrid_search_cache_hit, docling_parse_error
- Location: `src/pam/common/logging.py` for configuration

## Cross-Cutting Concerns

**Logging:**
- Structured JSON via structlog; correlation IDs track requests end-to-end
- Level control: LOG_LEVEL env var

**Validation:**
- Pydantic models for all API request/response bodies and config
- SQLAlchemy constraint validation (unique constraints on documents.source_type + source_id)
- SQL injection prevention via `escape_like()` utility and parameterized queries

**Authentication:**
- Optional (controlled by AUTH_REQUIRED env var)
- Google OAuth2 flow via routes in `auth.py`
- JWT token validation in `get_current_user()` dependency
- User scopes tied to projects via UserProjectRole model (Phase 2 feature, mostly stubbed)

**Caching:**
- Search results: Redis with 15-min TTL
- Embeddings: Memory via OpenAIEmbedder.embed_texts_with_cache() (uses content hash)
- Services: Module-level singletons with async lock pattern (embedder, reranker, search service, duckdb service)

**Performance:**
- Async I/O throughout: database, ES, embeddings API
- Connection pooling: SQLAlchemy pool_size=5, max_overflow=10
- Batch embedding: Chunks embedded in single API call to OpenAI
- Lazy initialization: Services created on first use, cached (thread-safe via asyncio.Lock)

---

*Architecture analysis: 2026-02-15*
