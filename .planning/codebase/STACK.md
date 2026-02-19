# Technology Stack

**Analysis Date:** 2025-02-15

## Languages

**Primary:**
- Python 3.12+ - Backend application, ingestion pipeline, retrieval agent
- TypeScript 5.6.3 - Frontend application
- SQL - PostgreSQL schema and migrations via Alembic

**Secondary:**
- JavaScript - React runtime dependencies (package.json)
- YAML - Configuration files (docker-compose.yml, alembic.ini)
- Markdown - Documentation parsing via Docling

## Runtime

**Environment:**
- Python 3.12 (slim Docker image: `python:3.12-slim`)
- Node.js 18+ (inferred from package.json `"type": "module"` and ES2020 target)

**Package Manager:**
- uv - Python package manager (lockfile: `uv.lock` - 780KB)
- npm/pnpm - JavaScript (dependencies in `web/package.json`)

## Frameworks

**Core Backend:**
- FastAPI 0.115+ - REST API framework
- SQLAlchemy 2.0+ with asyncio - ORM for PostgreSQL
- Pydantic 2.0+ / pydantic-settings - Data validation and settings management
- Alembic 1.13+ - Database migrations

**Frontend:**
- React 18.3.1 - UI framework
- Vite 6.0.3 - Build tool and dev server
- TypeScript 5.6.3 - Type-safe JavaScript
- Tailwind CSS 4.1.18 - Utility-first CSS framework
- React Router 6.28.0 - Client-side routing

**Document Processing:**
- Docling 2.0+ - Layout-aware document parsing (DOCX, PDF, Markdown)
- Sentence-Transformers 3.0+ - Cross-encoder reranking (ms-marco model, ~80MB)

**LLM/AI:**
- Anthropic SDK 0.40+ - Claude API client for agent tool-use loops
- OpenAI SDK 1.50+ - OpenAI embeddings API client (text-embedding-3-large)

**Search & Storage:**
- Elasticsearch 8.15.0 (via Docker) - Vector search with dense_vector mapping, RRF retrieval
- Haystack 2.9+ - Optional retrieval pipeline backend (disabled by default)
- elasticsearch-haystack 2.0+ - Elasticsearch integration for Haystack
- Redis 7.0 (via Docker) - Caching layer for search results, segments, conversation sessions

**Database:**
- PostgreSQL 16-alpine (via Docker) - Primary OLTP database
- psycopg 3.0+ - PostgreSQL async driver with binary support
- DuckDB 1.0+ - Optional in-process SQL analytics over CSV/Parquet/JSON files

**Observability:**
- structlog 24.0+ - Structured logging with correlation IDs
- python-dotenv 1.0+ - Environment variable loading

**Utilities:**
- tenacity 8.0+ - Retry logic with exponential backoff for API calls
- httpx 0.27+ - Async HTTP client
- PyJWT 2.8+ - JWT token encoding/decoding for optional auth
- Google API Python Client 2.0+ - Google Drive/Docs/Sheets API integration
- google-auth-oauthlib 1.0+ - Google OAuth2 authentication flow

## Testing & Development

**Testing:**
- pytest 8.0+ - Test runner
- pytest-asyncio 0.23+ - Async test support
- pytest-cov 5.0+ - Code coverage reporting (target: 80% minimum)
- vitest 4.0.18 - Frontend unit tests (TypeScript/React)
- @testing-library/react 16.3.2 - React component testing
- jsdom 28.0.0 - DOM simulation for frontend tests

**Linting & Formatting:**
- ruff 0.5+ - Python linter/formatter (E, F, I, N, W, UP rules)
- mypy 1.10+ - Python type checker
- pre-commit 3.0+ - Git pre-commit hook framework

**Frontend Dev Tools:**
- @vitejs/plugin-react 4.3.4 - React plugin for Vite
- @tailwindcss/vite 4.1.18 - Tailwind CSS integration
- class-variance-authority 0.7.1 - Variant composition for styling
- lucide-react 0.563.0 - Icon library

**Markdown Rendering:**
- react-markdown 9.0.1 - Render markdown in React
- remark-gfm 4.0.1 - GitHub-flavored markdown plugin
- remark-math 6.0.0 - Math notation support
- rehype-highlight 7.0.2 - Syntax highlighting
- rehype-katex 7.0.1 - KaTeX math rendering
- katex 0.16.28 - Math typesetting

## Configuration

**Environment:**
- `.env` file for all secrets and settings (see `.env.example`)
- Pydantic Settings reads from environment variables with defaults in `src/pam/common/config.py`

**Build Configuration:**
- `pyproject.toml` - Python package metadata, dependencies, tool configs (ruff, pytest, mypy, coverage)
- `web/package.json` - Frontend dependencies and build scripts
- `docker-compose.yml` - Local development services: PostgreSQL, Elasticsearch, Redis
- `Dockerfile` - Multi-layer Docker image for backend (Python 3.12-slim, FastAPI app)
- `alembic.ini` - Database migration config pointing to `alembic/versions/`
- `.pre-commit-config.yaml` - Git hooks for ruff, formatting, YAML validation

**Frontend Configuration:**
- `web/tsconfig.json` - TypeScript compiler options (ES2020 target, strict mode, baseUrl path aliases)
- `tailwind.config.*` - Tailwind CSS configuration (implicit in Vite setup)

## Key Dependencies by Concern

**Async/IO:**
- httpx, psycopg, elasticsearch (async variants), redis.asyncio, anthropic SDK

**Vector Search:**
- elasticsearch (dense_vector, cosine similarity, RRF)
- sentence-transformers (cross-encoder reranking - optional)

**Document Processing:**
- docling (parsing DOCX/PDF/Markdown → structured DoclingDocument)

**LLM Integration:**
- Anthropic: Tool-use loops, streaming, token counting
- OpenAI: Embeddings with batching and in-memory LRU caching

**Authentication:**
- PyJWT (HS256 algorithm, configurable expiry)
- Google OAuth2 (credentials-based, not implemented in Phase 1)

**Caching:**
- Redis (search results TTL 15m, segments 1h, sessions 24h)
- OpenAI embedder: in-memory LRU cache (10k entries, content-hash keyed)

## Platform Requirements

**Development:**
- Python 3.12+
- Node.js 18+ (for web frontend)
- Docker & Docker Compose (for PostgreSQL, Elasticsearch, Redis)
- uv package manager recommended

**Production:**
- Docker container runtime (uvicorn app exposed on port 8000)
- PostgreSQL 16+ database
- Elasticsearch 8.x cluster
- Redis 7+ (optional, for caching)
- OpenAI API access (embeddings)
- Anthropic API access (Claude agent)

## Build Output

**Backend:**
- Single wheel package: `src/pam` (hatchling build backend)
- Docker image entry: `uvicorn pam.api.main:app --host 0.0.0.0 --port 8000`

**Frontend:**
- Static build: `web/dist/` (Vite build target)
- TypeScript → JavaScript transpilation + tree-shaking

---

*Stack analysis: 2025-02-15*
