# Codebase Structure

**Analysis Date:** 2026-02-15

## Directory Layout

```
pam-context/
├── src/pam/                          # Main Python package (single package, not monorepo)
│   ├── __init__.py
│   ├── api/                          # FastAPI application and routes
│   │   ├── main.py                   # App factory, lifespan, middleware
│   │   ├── deps.py                   # FastAPI dependency injection (services)
│   │   ├── auth.py                   # Auth flow (Google OAuth, JWT)
│   │   ├── middleware.py             # Correlation ID, request logging
│   │   └── routes/                   # Endpoint handlers (6 modules)
│   │       ├── chat.py               # POST /api/chat, /api/chat/stream
│   │       ├── search.py             # POST /api/search
│   │       ├── documents.py          # GET/POST /api/documents
│   │       ├── ingest.py             # POST /api/ingest, GET /api/ingest/{task_id}
│   │       ├── admin.py              # Admin endpoints (delete, reset)
│   │       └── auth.py               # Auth endpoints (login, callback)
│   ├── agent/                        # Retrieval agent and tools
│   │   ├── agent.py                  # RetrievalAgent class (tool-use loop)
│   │   ├── tools.py                  # Tool definitions (JSON schemas)
│   │   └── duckdb_service.py         # DuckDB query service for analytics
│   ├── ingestion/                    # Document ingestion pipeline
│   │   ├── pipeline.py               # IngestionPipeline orchestrator
│   │   ├── task_manager.py           # Background task lifecycle
│   │   ├── connectors/               # Document source adapters
│   │   │   ├── base.py               # BaseConnector abstract class
│   │   │   ├── markdown.py           # Markdown file connector
│   │   │   ├── google_docs.py        # Google Docs API connector
│   │   │   └── google_sheets.py      # Google Sheets connector (with region detector)
│   │   ├── parsers/                  # Document format parsers
│   │   │   └── docling_parser.py     # Docling (DOCX, PDF, Markdown)
│   │   ├── chunkers/                 # Document chunking strategies
│   │   │   └── hybrid_chunker.py     # Docling HybridChunker wrapper
│   │   ├── embedders/                # Embedding model interfaces
│   │   │   ├── base.py               # BaseEmbedder abstract class
│   │   │   └── openai_embedder.py    # OpenAI text-embedding-3-large
│   │   ├── extractors/               # Entity extraction (stub)
│   │   │   └── schemas.py            # Schema definitions
│   │   └── stores/                   # Storage backends
│   │       ├── postgres_store.py     # PostgreSQL writer (authoritative)
│   │       └── elasticsearch_store.py # Elasticsearch writer (search index)
│   ├── retrieval/                    # Search and ranking services
│   │   ├── hybrid_search.py          # ES RRF hybrid search (legacy)
│   │   ├── haystack_search.py        # Optional Haystack 2.x pipeline
│   │   ├── types.py                  # SearchQuery, SearchResult schemas
│   │   └── rerankers/                # Ranking models
│   │       ├── base.py               # BaseReranker abstract class
│   │       └── cross_encoder.py      # Cross-encoder reranker
│   └── common/                       # Shared utilities
│       ├── models.py                 # SQLAlchemy ORM + Pydantic schemas
│       ├── config.py                 # Pydantic Settings (env vars)
│       ├── database.py               # Async SQLAlchemy engine/session
│       ├── logging.py                # structlog configuration
│       ├── cache.py                  # Redis CacheService
│       ├── haystack_adapter.py       # PAM ↔ Haystack type conversions
│       └── utils.py                  # SQL injection prevention, etc.
├── web/                              # React 18 TypeScript frontend
│   ├── src/
│   │   ├── main.tsx                  # Entry point, renders App
│   │   ├── App.tsx                   # Root component with routing
│   │   ├── index.css                 # Global styles (Tailwind)
│   │   ├── pages/                    # Page components
│   │   │   ├── ChatPage.tsx
│   │   │   ├── DocumentsPage.tsx
│   │   │   └── AdminPage.tsx
│   │   ├── components/               # Reusable UI components
│   │   │   ├── ChatInterface.tsx     # Main chat UI
│   │   │   ├── DocumentList.tsx      # Document browser
│   │   │   ├── SearchFilters.tsx     # Filter controls
│   │   │   ├── MessageBubble.tsx     # Chat message display
│   │   │   ├── CitationLink.tsx      # Citation UI
│   │   │   ├── SourceViewer.tsx      # Document viewer
│   │   │   ├── chat/                 # Chat-specific components
│   │   │   │   ├── CitationTooltip.tsx
│   │   │   │   └── CodeBlock.tsx
│   │   │   └── ui/                   # Base UI primitives (button, tooltip)
│   │   ├── hooks/                    # React custom hooks
│   │   │   ├── useChat.ts            # Chat API integration
│   │   │   ├── useChat.test.ts       # Hook tests
│   │   │   ├── useDocuments.ts       # Document list
│   │   │   ├── useAuth.ts            # Auth state
│   │   │   ├── useIngestionTask.ts   # Task polling
│   │   │   └── useMarkdownComponents.tsx # Markdown rendering
│   │   ├── api/                      # API client layer
│   │   │   └── client.ts             # Fetch wrapper, auth headers
│   │   ├── lib/                      # Utilities
│   │   └── utils/                    # Markdown, formatting
│   ├── vite.config.ts
│   ├── package.json
│   └── tsconfig.json
├── tests/                            # Python test suite (pytest)
│   ├── test_api/                     # API route tests
│   ├── test_agent/                   # Agent tests
│   ├── test_ingestion/               # Ingestion pipeline tests
│   ├── test_retrieval/               # Search tests
│   ├── test_common/                  # Config, logging tests
│   ├── fixtures/                     # Shared test data
│   │   └── sheets/                   # Google Sheets fixtures
│   └── conftest.py                   # pytest fixtures (database, ES)
├── alembic/                          # Database migrations
│   ├── env.py                        # Migration environment
│   ├── alembic.ini                   # Config
│   └── versions/                     # Migration scripts (*.py)
├── scripts/                          # Utility scripts
├── docs/                             # Markdown documentation
├── eval/                             # Evaluation harness
│   ├── questions.json                # Test questions
│   ├── run_eval.py                   # Evaluation runner
│   └── judges.py                     # Judge models
├── test_docs/                        # Test document fixtures
├── .github/                          # GitHub Actions workflows
├── .planning/                        # GSD planning documents
├── docker-compose.yml                # Local infra (PG, ES, Redis)
├── Dockerfile                        # Container image
├── pyproject.toml                    # Python project config
├── uv.lock                           # Dependency lock file
├── .env.example                      # Example environment variables
└── .gitignore                        # Git exclusions
```

## Directory Purposes

**`src/pam/`:**
- Purpose: Main package containing all business logic
- Contains: API, agent, ingestion, retrieval, common modules
- Key files: Hundreds of .py files organized by functional area
- Entry point: `api/main.py` exports `create_app()` and `app` instance

**`src/pam/api/`:**
- Purpose: HTTP API layer using FastAPI
- Contains: Route handlers, dependency injection, middleware, auth
- Key files: `main.py` (app factory), `routes/*.py` (6 endpoint modules)
- Patterns: Depends() for service injection, FastAPI lifespan context manager

**`src/pam/agent/`:**
- Purpose: Claude-powered retrieval agent with tool-use loop
- Contains: Agent class, tool definitions, DuckDB analytics service
- Key files: `agent.py` (~180 line imperative loop), `tools.py` (5 tool schemas)
- Dependency: Per-request instantiation via `get_agent()` in deps.py

**`src/pam/ingestion/`:**
- Purpose: Multi-stage pipeline from raw documents to searchable knowledge
- Contains: Pipeline orchestrator, connectors (3), parser (1), chunker (1), embedder (1), stores (2)
- Key files: `pipeline.py` (main flow), `task_manager.py` (background lifecycle)
- Pattern: Connector → Parser → Chunker → Embedder → Stores (PG then ES)

**`src/pam/ingestion/connectors/`:**
- Purpose: Source adapters for different document types
- Contains: Markdown files, Google Docs, Google Sheets
- Pattern: BaseConnector with `list_documents()`, `fetch_document()`, `get_content_hash()`

**`src/pam/ingestion/parsers/`:**
- Purpose: Convert raw bytes to structured documents
- Contains: DoclingParser using Docling library (layout-aware)
- Output: DoclingDocument objects (headings, text, tables, figures)

**`src/pam/ingestion/chunkers/`:**
- Purpose: Split documents into semantic chunks for embedding
- Contains: HybridChunker wrapper around Docling's chunker
- Output: ChunkResult with content, hash, section_path, segment_type, position

**`src/pam/ingestion/embedders/`:**
- Purpose: Generate vector embeddings for chunks
- Contains: BaseEmbedder, OpenAIEmbedder
- Pattern: `embed_texts()` async method; optional `embed_texts_with_cache()` override
- Cache: Content hash → embedding vector (memory-backed in OpenAI embedder)

**`src/pam/ingestion/stores/`:**
- Purpose: Write chunks to persistent storage
- Contains: PostgresStore (authoritative), ElasticsearchStore (search index)
- Write order: PG first (with transaction), then ES (best-effort)

**`src/pam/retrieval/`:**
- Purpose: Search and ranking over indexed documents
- Contains: HybridSearchService (legacy ES RRF), HaystackSearchService (optional), rerankers
- Key decision: Use legacy or Haystack backend controlled by `USE_HAYSTACK_RETRIEVAL` env var

**`src/pam/common/`:**
- Purpose: Shared models, configuration, utilities
- Contains: ORM models, Pydantic config, logging, database, cache, type conversions
- Key files: `models.py` (all ORM classes), `config.py` (Settings)

**`web/src/`:**
- Purpose: React 18 frontend for user interaction
- Contains: Pages, components, hooks, API client, styles
- Organization: Feature-based (pages/, components/, hooks/)
- Styling: Tailwind CSS + custom CSS in index.css

**`tests/`:**
- Purpose: pytest test suite for Python backend
- Contains: Tests organized by module (test_api, test_agent, test_ingestion, test_retrieval, test_common)
- Fixtures: Database fixtures in conftest.py, test data in fixtures/
- Run: `pytest` or `pytest tests/test_api/` for specific module

**`alembic/`:**
- Purpose: Database schema version control
- Contains: Migration scripts in versions/ directory
- Usage: `alembic upgrade head` before first run, `alembic revision --autogenerate` after schema changes

**`eval/`:**
- Purpose: Evaluation harness for Q&A quality
- Contains: questions.json (test cases), run_eval.py (runner), judges.py (evaluation models)

## Key File Locations

**Entry Points:**

| File | Purpose |
|------|---------|
| `src/pam/api/main.py` | FastAPI app factory, `create_app()` and `app` instance |
| `web/src/main.tsx` | React entry point, renders `<App />` |
| `alembic/env.py` | Database migration environment |
| `scripts/` | Utility scripts (if any) |

**Configuration:**

| File | Purpose |
|------|---------|
| `src/pam/common/config.py` | Pydantic Settings with all env vars (OpenAI, Anthropic, DB URLs, feature flags) |
| `.env.example` | Example .env file template |
| `pyproject.toml` | Python dependencies, project metadata |
| `web/vite.config.ts` | Vite build config |

**Core Logic:**

| File | Purpose |
|------|---------|
| `src/pam/ingestion/pipeline.py` | Orchestrator for ingestion flow (connects all stages) |
| `src/pam/agent/agent.py` | Retrieval agent with tool-use loop and citation tracking |
| `src/pam/retrieval/hybrid_search.py` | Hybrid search combining BM25 + kNN via ES RRF |
| `src/pam/common/models.py` | All 10 SQLAlchemy ORM models (Document, Segment, User, etc.) |

**Testing:**

| File | Purpose |
|------|---------|
| `tests/conftest.py` | pytest fixtures: async database, Elasticsearch, temporary folders |
| `tests/test_ingestion/` | Pipeline, connector, parser, chunker tests |
| `tests/test_retrieval/` | Search service tests (hybrid search, caching) |
| `tests/test_agent/` | Agent tool execution tests |
| `tests/test_api/` | Route handler tests (chat, search, ingest endpoints) |
| `tests/test_common/` | Config, logging, model tests |

## Naming Conventions

**Python Files:**
- Modules: `snake_case.py` (e.g., `hybrid_search.py`, `docling_parser.py`)
- Classes: `PascalCase` (e.g., `RetrievalAgent`, `HybridSearchService`)
- Functions/methods: `snake_case` (e.g., `embed_texts`, `ingest_document`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_TOOL_ITERATIONS`, `SYSTEM_PROMPT`)

**TypeScript/React Files:**
- Components: `PascalCase.tsx` (e.g., `ChatInterface.tsx`, `CitationLink.tsx`)
- Hooks: `useXxx.ts` (e.g., `useChat.ts`, `useAuth.ts`)
- Utils: `snake_case.ts` (e.g., `markdown.ts`)
- Type files: `.d.ts` for global types (e.g., `vite-env.d.ts`)

**Directories:**
- Functional areas: `snake_case/` (e.g., `ingestion/`, `retrieval/`, `connectors/`)
- Feature grouping: `PascalCase/` for component families (e.g., `chat/` for chat-specific components)

**Environment Variables:**
- Format: `UPPER_SNAKE_CASE` (e.g., `DATABASE_URL`, `OPENAI_API_KEY`, `USE_HAYSTACK_RETRIEVAL`)

**Database:**
- Tables: `plural_snake_case` (e.g., `documents`, `segments`, `users`)
- Columns: `snake_case` (e.g., `content_hash`, `source_id`, `created_at`)
- Constraints: `uq_table_col` (unique), `fk_parent_id` (foreign key)

**API Endpoints:**
- Format: `/api/{resource}` or `/api/{resource}/{id}` (RESTful)
- Examples:
  - `POST /api/chat` — conversational Q&A
  - `POST /api/search` — semantic search
  - `GET /api/documents` — list documents
  - `POST /api/ingest` — start ingestion task
  - `GET /api/ingest/{task_id}` — poll task status
  - `GET /api/health` — health check

## Where to Add New Code

**New API Endpoint:**
- Create handler function in `src/pam/api/routes/{feature}.py`
- Add route to router: `@router.get("/path")` or `@router.post("/path")`
- Inject dependencies via `Depends()` (services from `deps.py`)
- Import route in `src/pam/api/main.py` and `app.include_router()`
- Example: `src/pam/api/routes/chat.py`

**New Ingestion Connector:**
- Create `src/pam/ingestion/connectors/{source_name}.py`
- Implement `BaseConnector`: `list_documents()`, `fetch_document()`, `get_content_hash()`
- Return `DocumentInfo` (for list) and `RawDocument` (for fetch)
- Use in `IngestionPipeline.__init__()` to select connector per source_type
- Example: `src/pam/ingestion/connectors/google_docs.py`

**New Retrieval Tool:**
- Add tool schema to `src/pam/agent/tools.py` (name, description, input_schema)
- Append to `ALL_TOOLS` list
- Implement handler in `src/pam/agent/agent.py._execute_tool()` method
- Example: `search_knowledge`, `get_document_context`, `query_database`

**New Database Model:**
- Create class in `src/pam/common/models.py` inheriting from `Base`
- Define columns with `Mapped[]` type annotations
- Add relationships if needed
- Create Alembic migration: `alembic revision --autogenerate -m "description"`
- Example: See `Document`, `Segment`, `User` classes

**New Frontend Component:**
- Create `.tsx` file in `web/src/components/` (or feature subdirectory)
- Use hooks from `web/src/hooks/` for API calls and state
- Import API client from `web/src/api/client.ts`
- Add to relevant page in `web/src/pages/`
- Style with Tailwind classes + `index.css`
- Example: `web/src/components/ChatInterface.tsx`

**New Hook (React):**
- Create `web/src/hooks/useXxx.ts`
- Fetch from API via `api/client.ts`
- Return state and handlers
- Use in components via `const { data, loading, error } = useXxx()`
- Example: `web/src/hooks/useChat.ts`

**New Test:**
- Create `tests/test_{module}/test_{feature}.py`
- Use fixtures from `conftest.py` (async_db_session, es_client, etc.)
- Run with: `pytest tests/test_{module}/test_{feature}.py`
- Example: `tests/test_ingestion/test_pipeline.py`

## Special Directories

**`.planning/`:**
- Purpose: GSD planning documents (auto-generated)
- Contains: ARCHITECTURE.md, STRUCTURE.md, CONVENTIONS.md, TESTING.md, STACK.md, INTEGRATIONS.md, CONCERNS.md
- Generated: No (checked in after first generation)
- Committed: Yes

**`.github/`:**
- Purpose: GitHub Actions CI/CD workflows
- Contains: YAML workflow files
- Generated: No
- Committed: Yes

**`alembic/versions/`:**
- Purpose: Database migration history
- Contains: Python migration files (auto or hand-written)
- Generated: Partly (auto-generated via `alembic revision --autogenerate`)
- Committed: Yes (migrations are version control)

**`test_docs/`:**
- Purpose: Sample documents for manual testing
- Contains: Markdown files, PDFs (if any)
- Generated: No
- Committed: Yes

**`web/dist/`:**
- Purpose: Built React SPA output
- Contains: Minified JS, CSS, HTML
- Generated: Yes (via `npm run build`)
- Committed: No (in .gitignore)

**`web/node_modules/`:**
- Purpose: NPM dependencies
- Generated: Yes (via `npm install`)
- Committed: No (in .gitignore)

**`.venv/`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`:**
- Purpose: Python development artifacts
- Generated: Yes
- Committed: No (in .gitignore)

---

*Structure analysis: 2026-02-15*
