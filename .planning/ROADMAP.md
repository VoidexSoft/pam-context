# Roadmap: PAM Context -- Code Quality Cleanup

## Overview

This milestone stabilizes the PAM Context codebase by fixing 39 findings across 7 GitHub issues. The work proceeds in dependency order: singleton lifecycle fixes first (because every module depends on stable service initialization), then database integrity (highest-impact performance fix), then API and agent hardening (depends on stable startup), and finally frontend cleanup (independent, lowest risk). Each phase is independently shippable and testable against the existing 450+ test suite.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Singleton Lifecycle + Tooling** - Migrate service singletons to app.state and expand linting/type-checking configuration
- [x] **Phase 2: Database Integrity** - Add missing indexes, constraints, and fix test isolation
- [ ] **Phase 3: API + Agent Hardening** - Fix streaming, add response models and pagination, harden agent tools
- [ ] **Phase 4: Frontend + Dead Code Cleanup** - Fix React rendering issues, accessibility, and remove dead code
- [ ] **Phase 5: Audit Gap Closure** - Close partial requirements, remove dead frontend code, wire broken E2E flows

## Phase Details

### Phase 1: Singleton Lifecycle + Tooling
**Goal**: Services initialize reliably via FastAPI lifespan, tests run in full isolation, and expanded linting catches bug patterns across the codebase
**Depends on**: Nothing (first phase)
**Requirements**: SING-01, SING-02, SING-03, SING-04, SING-05, SING-06, SING-07, SING-08, TOOL-01, TOOL-02
**Success Criteria** (what must be TRUE):
  1. All service singletons (embedder, reranker, search service, DuckDB, DB engine, session factory) live on app.state and are created in the FastAPI lifespan -- no module-level globals remain in deps.py
  2. deps.py dependency functions read exclusively from request.app.state with zero module-level singleton state
  3. CacheService, task_manager, and all service constructors accept config as explicit parameters with no hidden settings imports
  4. Running `pytest -p randomly` passes all 450+ tests with no order-dependent failures
  5. Ruff and mypy run with expanded rule sets (B, S, SIM, ARG, FAST, PT, RET, PERF, RUF for Ruff; check_untyped_defs, plugins for mypy) and the codebase passes cleanly
**Plans:** 2 plans

Plans:
- [x] 01-01-PLAN.md — Expand ruff/mypy tooling and make all service constructors accept explicit config
- [x] 01-02-PLAN.md — Migrate singletons to lifespan + app.state, clean deps.py, refactor task_manager

### Phase 2: Database Integrity
**Goal**: Database queries against Segment and Document tables use proper indexes, and role validation is enforced at the database level
**Depends on**: Phase 1
**Requirements**: DB-01, DB-02, DB-03, DB-04, TOOL-03, TOOL-04
**Success Criteria** (what must be TRUE):
  1. PostgreSQL EXPLAIN on queries filtering by Segment.document_id and Document.content_hash shows index scans (not sequential scans)
  2. Inserting a UserProjectRole with an invalid role value (not viewer/editor/admin) is rejected by a CHECK constraint
  3. Alembic migration applies without locking tables (uses CREATE INDEX CONCURRENTLY)
  4. AssignRoleRequest.role uses Literal["viewer", "editor", "admin"] and rejects invalid values at the Pydantic layer
**Plans:** 1 plan

Plans:
- [x] 02-01-PLAN.md — Add indexes, CHECK constraint, Literal role validation, and test isolation fix

### Phase 3: API + Agent Hardening
**Goal**: API endpoints return validated responses with proper OpenAPI schemas, SSE streaming handles errors gracefully, and agent tools have correct schemas
**Depends on**: Phase 1
**Requirements**: API-01, API-02, API-03, API-04, API-05, API-06, API-07, API-08, AGNT-01, AGNT-02, AGNT-03, AGNT-04, AGNT-05, AGNT-06
**Success Criteria** (what must be TRUE):
  1. SSE chat streaming works without buffering delays -- replacing BaseHTTPMiddleware with pure ASGI middleware eliminates the streaming lag
  2. When the LLM API fails mid-stream, the client receives a structured SSE error event (not a silent drop or broken connection)
  3. All list endpoints (documents, users, tasks) use cursor-based pagination with opaque base64 cursors and return `{items, total, cursor}` envelopes
  4. All document and admin endpoints have response_model in their OpenAPI schema (visible in /docs)
  5. Agent tool schemas include required fields, chunk text has no leading-space artifacts, and CostTracker warns on unknown models
**Plans**: 3 plans

Plans:
- [ ] 03-01-PLAN.md — Replace BaseHTTPMiddleware with pure ASGI, add SSE error events, fix _chunk_text
- [ ] 03-02-PLAN.md — Cursor-based pagination, response_model additions, endpoint fixes (revoke_role 404, get_me 501, get_segment JOIN)
- [ ] 03-03-PLAN.md — Agent tool schema fixes, CostTracker warning, cache key hash, SearchService Protocol, hybrid_search log fix

### Phase 4: Frontend + Dead Code Cleanup
**Goal**: React UI renders efficiently without unnecessary re-renders, interactive elements are accessible, and dead code is removed across the full codebase
**Depends on**: Phase 3
**Requirements**: FE-01, FE-02, FE-03, FE-04, FE-05, FE-06, FE-07, FE-08, FE-09
**Success Criteria** (what must be TRUE):
  1. React message list uses stable keys (not array index) -- React DevTools shows no unnecessary unmount/remount cycles during chat
  2. useIngestionTask polling uses chained setTimeout (not setInterval) and cleans up on unmount with no leaked timers
  3. All interactive elements in SearchFilters, DocumentsPage, and ChatPage have aria-label attributes for screen readers
  4. Dead code is removed: CitationLink.tsx, require_auth in auth.py, unused orig_idx in openai_embedder.py, and Content-Type header on GET requests
  5. Eval print_summary handles division by zero without crashing
**Plans**: 2 plans

Plans:
- [ ] 04-01-PLAN.md — React rendering fixes (stable keys, smart scroll, useCallback, setTimeout polling, Content-Type fix, chat aria-labels)
- [ ] 04-02-PLAN.md — Accessibility for remaining components, dead code removal (CitationLink, require_auth), eval guard

### Phase 5: Audit Gap Closure
**Goal**: Close all gaps identified by v1 milestone audit — fix partial requirement implementations, remove dead frontend code, and wire the 2 broken E2E flows
**Depends on**: Phase 3
**Requirements**: TOOL-02, AGNT-04
**Gap Closure**: Closes gaps from v1-MILESTONE-AUDIT.md
**Success Criteria** (what must be TRUE):
  1. mypy runs clean on deps.py with no `no-any-return` errors (via `cast()` on `app.state` accesses)
  2. `RetrievalAgent.__init__` accepts `search_service: SearchService` (Protocol type, not concrete class)
  3. `getAuthStatus()` and `listTasks()` removed from client.ts — no dead API functions remain
  4. SSE `done` event includes `conversation_id` in metadata, and `useChat.ts` preserves it across turns
  5. ChatResponse field names aligned between backend and frontend — non-streaming fallback path functional
**Plans**: 2 plans

Plans:
- [ ] 05-01-PLAN.md — Backend type safety (deps.py cast, Protocol annotations) and conversation_id wiring
- [ ] 05-02-PLAN.md — Frontend: dead code removal, ChatResponse alignment, metrics wiring, expandable details

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Singleton Lifecycle + Tooling | 2/2 | ✓ Complete | 2026-02-16 |
| 2. Database Integrity | 1/1 | ✓ Complete | 2026-02-16 |
| 3. API + Agent Hardening | 0/3 | Not started | - |
| 4. Frontend + Dead Code Cleanup | 0/2 | Not started | - |
| 5. Audit Gap Closure | 0/1 | Not started | - |
