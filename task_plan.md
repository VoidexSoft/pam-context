# Phase 2: Full Knowledge Layer — Implementation Plan

**Goal**: Add Google Sheets, reranking, permissions, Redis caching, enhanced agent tools, entity extraction, and frontend enhancements.

**Dependency**: Phase 1 complete (confirmed: 117 tests, 91% coverage, all routes working)

---

## Phase Overview

| # | Component | Risk | Priority | Status |
|---|-----------|------|----------|--------|
| 2.1 | Google Sheets Connector & Parser | HIGH | High | complete |
| 2.2 | Redis Cache Layer | LOW | High | complete |
| 2.3 | Reranking Pipeline | LOW | Medium | complete |
| 2.4 | Permission System (RBAC + JWT) | MEDIUM | High | complete |
| 2.5 | Enhanced Agent Tools | MEDIUM | Medium | complete |
| 2.6 | LangExtract Entity Extraction | MEDIUM | Lower | complete |
| 2.7 | Frontend Enhancements | LOW | Lower | complete |

**Current test count**: 254 tests (up from 117 in Phase 1)

---

## Implementation Order (Dependency-Aware)

### Wave 1: Infrastructure Foundation ✅
> These unlock capabilities for everything else.

#### Step 2.2 — Redis Cache Layer `status: complete`
- [x] Add Redis 7 to `docker-compose.yml`
- [x] Create `src/pam/common/cache.py` — Redis client wrapper with TTL helpers
- [x] Add Redis config to `src/pam/common/config.py` (REDIS_URL, REDIS_TTL_SECONDS)
- [x] Cache retrieval results in `hybrid_search.py` (hash query → cached results)
- [x] Session state store for multi-turn conversations
- [x] TTL-based invalidation (configurable, default 15 min for search, 1h for segments)
- [x] Health check for Redis in `/api/health`
- [x] Tests: cache hit/miss, TTL expiry, session CRUD, health check

**Files created**: `src/pam/common/cache.py`
**Files modified**: `docker-compose.yml`, `src/pam/common/config.py`, `src/pam/retrieval/hybrid_search.py`, `src/pam/api/main.py`
**Tests added**: 17 tests, total 143 passing

#### Step 2.4 — Permission System (RBAC + JWT) `status: complete`
- [x] DB models: `User`, `Role`, `UserProjectRole` tables + Alembic migration
- [x] JWT token generation/validation utilities
- [x] Google OAuth2 SSO integration (login flow)
- [x] FastAPI middleware for auth enforcement (`src/pam/api/auth.py`)
  - **Auth optional in dev mode**: skip auth when `AUTH_REQUIRED=false` (default in dev)
  - Required in production (`AUTH_REQUIRED=true`)
- [x] RBAC: viewer (read), editor (ingest), admin (manage users/projects)
- [x] Permission-scoped retrieval: filter segments by user's accessible projects
- [x] Admin endpoints: user CRUD, role assignment, project access management
- [x] Login/register frontend pages
- [x] Tests: auth flow, permission checks, scoped retrieval, middleware, dev-mode bypass

**Files created**: `src/pam/api/auth.py`, `src/pam/api/routes/auth.py`, `src/pam/api/routes/admin.py`, `alembic/versions/003_add_users_and_roles.py`
**Files modified**: `src/pam/common/models.py`, `src/pam/common/config.py`, `src/pam/retrieval/hybrid_search.py`
**Tests added**: 25 tests, total 168 passing

---

### Wave 2: Data Layer Expansion ✅
> New connectors and retrieval quality improvements.

#### Step 2.1 — Google Sheets Connector & Parser `status: complete`

**Spike findings**: Documented in `findings.md`. Region detection implemented via heuristics. 10 fixture patterns created covering clean tables, multi-table, notes+table, config, multi-tab, merged cells, mixed, sparse, formulas, and edge cases.

**Implementation**:
- [x] Create mock sheets covering common business patterns (10 patterns)
- [x] Region detection algorithm (table vs notes vs config)
- [x] Schema inference per table region
- [x] Cell notes and named ranges extraction
- [x] Multi-tab support
- [x] Convert to `KnowledgeSegment` with table metadata
- [x] Register connector in ingestion pipeline + API route
- [x] Tests: region detection, schema inference, multi-tab, edge cases

**Files created**: `src/pam/ingestion/connectors/google_sheets.py`, `src/pam/ingestion/connectors/sheets_region_detector.py`, `tests/fixtures/sheets/` (10 fixtures)
**Tests added**: 30 tests, total 198 passing

#### Step 2.3 — Reranking Pipeline (Self-Hosted) `status: complete`
- [x] Abstract reranker interface: `BaseReranker` in `src/pam/retrieval/rerankers/base.py`
- [x] Self-hosted cross-encoder: `src/pam/retrieval/rerankers/cross_encoder.py`
  - Model: `cross-encoder/ms-marco-MiniLM-L-6-v2` (fast, ~80MB, good quality)
  - Uses `sentence-transformers` library, runs on CPU (GPU optional)
  - No external API calls, no API keys needed
- [x] Add reranking step after RRF fusion in `hybrid_search.py`
- [x] Config: `RERANK_ENABLED`, `RERANK_MODEL_NAME` (swappable cross-encoder models)
- [x] Tests: reranker integration, fallback when disabled

**Files created**: `src/pam/retrieval/rerankers/base.py`, `src/pam/retrieval/rerankers/cross_encoder.py`
**Files modified**: `src/pam/retrieval/hybrid_search.py`, `src/pam/common/config.py`
**New dependency**: `sentence-transformers`
**Tests added**: 11 tests, total 209 passing

---

### Wave 3: Intelligence Layer ✅
> Richer agent capabilities and structured extraction.

#### Step 2.5 — Enhanced Agent Tools `status: complete`
- [x] `query_database` tool — DuckDB embedded engine with Parquet/CSV/JSON support, SQL guardrails, citations
- [x] `get_document_context` tool — fetch full document content for deep reading
- [x] `get_change_history` tool — query `sync_log` for recent changes per document/project
- [x] Register new tools in agent tool registry
- [x] Tests: SQL generation safety, tool execution, citation formatting

**Files created**: `src/pam/agent/duckdb_service.py`
**Files modified**: `src/pam/agent/tools.py`, `src/pam/agent/agent.py`, `src/pam/api/deps.py`
**New dependency**: `duckdb`
**Tests added**: 28 tests (test_duckdb_service.py + test_agent_tools.py), total 237 passing

#### Step 2.6 — LangExtract Entity Extraction `status: complete`
- [x] Define extraction schemas (Pydantic models): MetricDefinition, EventTrackingSpec, KPITarget
- [x] Extraction pipeline: LLM-based extractor using Anthropic API
- [x] PostgreSQL storage: `ExtractedEntity` table + Alembic migration
- [x] Source grounding: link entities to origin segment via FK
- [x] Agent tool: `search_entities` for structured entity lookup
- [x] Tests: extraction accuracy, entity storage, source linking

**Files created**: `src/pam/ingestion/extractors/__init__.py`, `src/pam/ingestion/extractors/schemas.py`, `src/pam/ingestion/extractors/entity_extractor.py`, `alembic/versions/004_add_extracted_entities.py`
**Files modified**: `src/pam/common/models.py`, `src/pam/agent/tools.py`, `src/pam/agent/agent.py`
**Tests added**: 17 tests, total 254 passing

---

### Wave 4: Frontend & Polish ✅
> User-facing improvements to leverage new backend capabilities.

#### Step 2.7 — Frontend Enhancements `status: complete`

**2.7.1 — Multi-turn Conversation Persistence**
- [x] `useChat` hook manages `conversationId` and message history (last 20 messages)
- [x] New conversation button in ChatPage
- [x] Filter state (source_type) passed to API

**2.7.2 — Source Viewer**
- [x] Click citation → slide-out panel showing original context with highlight
- [x] Backend endpoint: `GET /api/segments/{id}` in documents router
- [x] `SourceViewer.tsx` component with slide-in animation, metadata, markdown rendering

**2.7.3 — Search Filters**
- [x] Source type toggle (All, Markdown, Google Docs, Google Sheets)
- [x] `SearchFilters.tsx` component with active state styling
- [x] Filter state management in `useChat` hook

**2.7.4 — Admin Dashboard**
- [x] System stats cards (documents, segments, entities, tasks)
- [x] Document status breakdown + entity type breakdown
- [x] Backend endpoint: `GET /api/stats` in documents router
- [x] `AdminDashboard.tsx` page at `/admin` route

**2.7.5 — Login Page + Auth Flow** (optional in dev mode)
- [x] `LoginPage.tsx` with dev login (email/name)
- [x] `useAuth` hook with JWT token management
- [x] Conditional auth in `App.tsx`

**Files created**: `web/src/components/SourceViewer.tsx`, `web/src/components/SearchFilters.tsx`, `web/src/pages/AdminDashboard.tsx`, `web/src/pages/LoginPage.tsx`, `web/src/hooks/useAuth.ts`
**Files modified**: `web/src/pages/ChatPage.tsx`, `web/src/pages/DocumentsPage.tsx`, `web/src/api/client.ts`, `web/src/App.tsx`
**Frontend builds clean**: 207 modules, no TypeScript errors

---

## Errors Encountered
| Error | Resolution |
|-------|------------|
| SQLAlchemy relationship assignment with mock objects | Simplified test mock strategy to avoid ORM relationship validation |

---

## Key Decisions Log
| Decision | Rationale | Date |
|----------|-----------|------|
| Implementation order: Redis → Auth → Sheets → Rerank → Tools → Extract → Frontend | Redis is foundational; Auth security-critical; Sheets needs spike | 2026-02-11 |
| Auth optional in dev mode | Easier local dev; required in production only | 2026-02-11 |
| Self-hosted cross-encoder for reranking | No external API dependency; ms-marco-MiniLM-L-6-v2 | 2026-02-11 |
| DuckDB with Parquet preferred format | Self-hosted, zero infra; Parquet for columnar perf | 2026-02-11 |
| LLM-based entity extraction (Anthropic API) | Flexible schema, no additional ML model dependency | 2026-02-12 |

---

## Verification Criteria
- [x] All new features have unit tests (254 tests, >85% coverage maintained)
- [x] Existing Phase 1 tests still pass
- [x] Docker Compose starts cleanly with Redis added
- [x] Auth middleware enforces permissions on all protected routes
- [ ] Eval framework shows no quality regression after reranking integration
- [x] Frontend builds without errors, new pages render correctly (Wave 4)
