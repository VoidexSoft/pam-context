# Requirements Archive: v1 Code Quality Cleanup

**Archived:** 2026-02-19
**Status:** SHIPPED

For current requirements, see `.planning/REQUIREMENTS.md`.

---

# Requirements: PAM Context — Code Quality Cleanup

**Defined:** 2026-02-15
**Core Value:** Users can ask natural-language questions about their business documents and get accurate, cited answers from a Claude agent that searches across all ingested knowledge.

## v1 Requirements

Requirements for the cleanup milestone. Each maps to roadmap phases.

### Singleton Lifecycle

- [ ] **SING-01**: CacheService accepts all TTL values via constructor with no settings fallback
- [ ] **SING-02**: Database engine and session factory created in FastAPI lifespan and stored on app.state
- [ ] **SING-03**: Embedder, reranker, search service, and DuckDB service moved from deps.py module globals to app.state via lifespan
- [ ] **SING-04**: deps.py dependency functions read from request.app.state with no module-level singleton state
- [ ] **SING-05**: task_manager.py receives session_factory as explicit parameter instead of importing global
- [ ] **SING-06**: Service constructors accept all config as required params, settings import removed from service modules
- [ ] **SING-07**: ES INDEX_MAPPING in elasticsearch_store.py computed lazily instead of at import time
- [ ] **SING-08**: Stale DuckDB table cache invalidated when files change

### Database Integrity

- [ ] **DB-01**: Index added on Segment.document_id FK column via Alembic migration
- [ ] **DB-02**: Index added on Document.content_hash via Alembic migration
- [ ] **DB-03**: CHECK constraint added on UserProjectRole.role column (viewer/editor/admin)
- [ ] **DB-04**: Migration uses CREATE INDEX CONCURRENTLY to avoid table locks

### API Hardening

- [ ] **API-01**: BaseHTTPMiddleware replaced with pure ASGI middleware to fix SSE streaming buffering
- [ ] **API-02**: response_model added to endpoints in documents.py and admin.py missing OpenAPI schema
- [ ] **API-03**: Pagination added to list_documents endpoint with offset/limit
- [ ] **API-04**: Streaming errors wrapped in SSE format with structured error events
- [ ] **API-05**: revoke_role returns 404 when role doesn't exist instead of 204
- [ ] **API-06**: get_me returns appropriate response when auth is disabled (not 404)
- [ ] **API-07**: get_stats logs warning on entity query failure instead of silently swallowing
- [ ] **API-08**: get_segment uses JOIN instead of 2 sequential queries

### Agent & Retrieval

- [ ] **AGNT-01**: required fields added to GET_DOCUMENT_CONTEXT_TOOL schema
- [ ] **AGNT-02**: _chunk_text leading space on non-first chunks fixed
- [ ] **AGNT-03**: Log in hybrid_search.py emitted after reranking instead of before
- [x] **AGNT-04**: Protocol/ABC defined for search services enabling type-safe polymorphism
- [ ] **AGNT-05**: CostTracker logs warning for unknown model names instead of silent fallback
- [ ] **AGNT-06**: Cache key hash uses full SHA-256 instead of truncated 64-bit

### Frontend & Cleanup

- [x] **FE-01**: React message list uses stable keys instead of array index
- [x] **FE-02**: useCallback added for onClose in SourceViewer to prevent effect churn
- [x] **FE-03**: useIngestionTask uses chained setTimeout instead of setInterval to prevent overlapping polls
- [x] **FE-04**: Dead CitationLink.tsx component removed
- [x] **FE-05**: Dead require_auth function removed from auth.py
- [x] **FE-06**: Unused orig_idx variable removed from openai_embedder.py
- [x] **FE-07**: aria-label added to interactive elements in SearchFilters, DocumentsPage, ChatPage
- [x] **FE-08**: Division by zero guarded in eval print_summary
- [x] **FE-09**: Content-Type: application/json removed from GET requests in client.ts

### Tooling

- [ ] **TOOL-01**: Ruff rules expanded with B, S, SIM, ARG, FAST, PT, RET, PERF, RUF categories
- [x] **TOOL-02**: mypy configuration tightened with check_untyped_defs, plugins, warn_unreachable
- [ ] **TOOL-03**: AssignRoleRequest.role uses Literal type instead of regex pattern
- [ ] **TOOL-04**: test_env_override uses clear=True to prevent CI env leaks

## v2 Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Test Coverage

- **TEST-01**: Tests for cancelStreaming path in useChat hook
- **TEST-02**: Tests for useDocuments, useIngestionTask, useAuth hooks
- **TEST-03**: Tests for markdown.ts processing utilities
- **TEST-04**: Tests for eval module (judges.py JSON parsing, run_eval.py scoring)
- **TEST-05**: Tests for configure_logging() and close_redis() edge cases

### Frontend Infrastructure

- **FEINF-01**: ESLint added to frontend build pipeline
- **FEINF-02**: React Testing Library coverage for all custom hooks

### Production Readiness

- **PROD-01**: Deployment pipeline with Docker and health checks
- **PROD-02**: Redis Sentinel/Cluster support for HA
- **PROD-03**: Full mypy strict mode across codebase

## Out of Scope

| Feature | Reason |
|---------|--------|
| Major architectural refactoring | This is cleanup, not a rewrite. Module boundaries stay the same. |
| New features (connectors, tools, endpoints) | Cleanup milestone should stabilize, not grow surface area. |
| Ruff 0.15+ upgrade | New 2026 formatting style creates massive diffs. Separate PR. |
| config.py/database.py proxy pattern changes | Already correct with lru_cache + reset_*(). Issue #32 is about deps.py. |
| Comprehensive frontend test coverage | Frontend works. Fix specific bugs, defer test infrastructure. |
| Redis Sentinel/Cluster | Stale reference is a singleton lifecycle issue, not an HA issue. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SING-01 | Phase 1 | Pending |
| SING-02 | Phase 1 | Pending |
| SING-03 | Phase 1 | Pending |
| SING-04 | Phase 1 | Pending |
| SING-05 | Phase 1 | Pending |
| SING-06 | Phase 1 | Pending |
| SING-07 | Phase 1 | Pending |
| SING-08 | Phase 1 | Pending |
| TOOL-01 | Phase 1 | Pending |
| TOOL-02 | Phase 5 | Complete |
| DB-01 | Phase 2 | Pending |
| DB-02 | Phase 2 | Pending |
| DB-03 | Phase 2 | Pending |
| DB-04 | Phase 2 | Pending |
| TOOL-03 | Phase 2 | Pending |
| TOOL-04 | Phase 2 | Pending |
| API-01 | Phase 3 | Pending |
| API-02 | Phase 3 | Pending |
| API-03 | Phase 3 | Pending |
| API-04 | Phase 3 | Pending |
| API-05 | Phase 3 | Pending |
| API-06 | Phase 3 | Pending |
| API-07 | Phase 3 | Pending |
| API-08 | Phase 3 | Pending |
| AGNT-01 | Phase 3 | Pending |
| AGNT-02 | Phase 3 | Pending |
| AGNT-03 | Phase 3 | Pending |
| AGNT-04 | Phase 5 | Complete |
| AGNT-05 | Phase 3 | Pending |
| AGNT-06 | Phase 3 | Pending |
| FE-01 | Phase 4 | Complete |
| FE-02 | Phase 4 | Complete |
| FE-03 | Phase 4 | Complete |
| FE-04 | Phase 4 | Complete |
| FE-05 | Phase 4 | Complete |
| FE-06 | Phase 4 | Complete |
| FE-07 | Phase 4 | Complete |
| FE-08 | Phase 4 | Complete |
| FE-09 | Phase 4 | Complete |

**Coverage:**
- v1 requirements: 37 total
- Mapped to phases: 37
- Unmapped: 0 ✓

---
*Requirements defined: 2026-02-15*
*Last updated: 2026-02-15 after initial definition*
