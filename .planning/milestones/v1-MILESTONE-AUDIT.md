---
milestone: v1
audited: 2026-02-19T12:00:00Z
status: passed
scores:
  requirements: 39/39
  phases: 5/5
  integration: 39/39
  flows: 4/4
gaps:
  requirements: []
  integration: []
  flows: []
tech_debt:
  - phase: 02-database-integrity
    items:
      - "Human verification needed: EXPLAIN queries to confirm index usage on live DB"
      - "Human verification needed: CHECK constraint enforcement on live DB"
  - phase: 03-api-agent-hardening
    items:
      - "Human verification needed: SSE streaming latency in real browser"
      - "Human verification needed: OpenAPI schema rendering in Swagger UI"
      - "Human verification needed: Cursor pagination UI flow"
  - phase: 04-frontend-dead-code-cleanup
    items:
      - "Human verification needed: Smart scroll UX behavior"
      - "Human verification needed: Screen reader accessibility audit"
      - "Human verification needed: Ingestion timer cleanup on unmount"
  - phase: 05-audit-gap-closure
    items:
      - "Non-streaming fallback citation document_id mapped to document_title (low severity, field unused by CitationTooltip)"
      - "Human verification needed: Expandable metrics visual display"
      - "Human verification needed: SSE conversation_id preservation across turns"
      - "Admin user/role management routes have no frontend consumer (pre-existing, out of scope)"
---

# v1 Milestone Audit: Code Quality Cleanup

**Milestone:** v1 — Code Quality Cleanup
**Audited:** 2026-02-19
**Status:** passed
**Overall Score:** 39/39 requirements satisfied across 5/5 phases

## Executive Summary

All 39 v1 requirements are satisfied. All 5 phases passed verification (Phase 1 had a mypy gap that was subsequently closed by Phase 5). Cross-phase integration is sound with all 4 E2E flows fully wired. The previous audit (2026-02-18) identified 2 partial requirements (TOOL-02, AGNT-04) and 2 broken E2E flows — Phase 5 (Audit Gap Closure) resolved all of them.

**Previous audit status:** tech_debt (35/37 requirements, 2 broken flows)
**Current audit status:** passed (39/39 requirements, 0 broken flows)

---

## Phase Verification Summary

| Phase | Status | Score | Gap Summary |
|-------|--------|-------|-------------|
| 1. Singleton Lifecycle + Tooling | gaps_found → **closed** | 4/5 → 5/5 | mypy deps.py errors closed by Phase 5 cast() |
| 2. Database Integrity | passed | 6/6 | None |
| 3. API + Agent Hardening | passed | 5/5 | None |
| 4. Frontend + Dead Code Cleanup | passed | 11/11 | None |
| 5. Audit Gap Closure | passed | 12/12 | Closed all gaps from previous audit |

---

## Requirements Coverage (3-Source Cross-Reference)

### Singleton Lifecycle (Phase 1)

| Req | VERIFICATION | SUMMARY Provides | REQ.md | Final |
|-----|-------------|-----------------|--------|-------|
| SING-01 | Phase 1: ✓ (Truth 3) | 01-01: "All 8 service constructors accept explicit config" | [ ] | **satisfied** |
| SING-02 | Phase 1: ✓ (Truth 1) | 01-02: "Complete lifespan handler creating all 9 singletons" | [ ] | **satisfied** |
| SING-03 | Phase 1: ✓ (Truth 1) | 01-02: "All 9 singletons on app.state" | [ ] | **satisfied** |
| SING-04 | Phase 1: ✓ (Truth 2) | 01-02: "Stateless deps.py with zero module-level globals" | [ ] | **satisfied** |
| SING-05 | Phase 1: ✓ (Truth 3) | 01-02: "task_manager with injected session_factory" | [ ] | **satisfied** |
| SING-06 | Phase 1: ✓ (Truth 3) | 01-01: "All 8 service constructors accept explicit config" | [ ] | **satisfied** |
| SING-07 | Phase 1: ✓ (Artifact) | 01-01: "Lazy get_index_mapping() function" | [ ] | **satisfied** |
| SING-08 | Phase 1: ✓ (Artifact) | 01-01: "DuckDB stale cache detection via _needs_refresh()" | [ ] | **satisfied** |

### Database Integrity (Phase 2)

| Req | VERIFICATION | SUMMARY Provides | REQ.md | Final |
|-----|-------------|-----------------|--------|-------|
| DB-01 | Phase 2: ✓ SATISFIED | 02-01: "ORM index=True on Segment.document_id" | [ ] | **satisfied** |
| DB-02 | Phase 2: ✓ SATISFIED | 02-01: "Migration 005 content_hash index" | [ ] | **satisfied** |
| DB-03 | Phase 2: ✓ SATISFIED | 02-01: "CHECK constraint on role" | [ ] | **satisfied** |
| DB-04 | Phase 2: ✓ SATISFIED | 02-01: "CREATE INDEX CONCURRENTLY" | [ ] | **satisfied** |

### API Hardening (Phase 3)

| Req | VERIFICATION | SUMMARY Provides | REQ.md | Final |
|-----|-------------|-----------------|--------|-------|
| API-01 | Phase 3: ✓ SATISFIED | 03-01: "Pure ASGI middleware" | [ ] | **satisfied** |
| API-02 | Phase 3: ✓ SATISFIED | 03-02: "response_model on all endpoints" | [ ] | **satisfied** |
| API-03 | Phase 3: ✓ SATISFIED | 03-02: "Cursor-based pagination" | [ ] | **satisfied** |
| API-04 | Phase 3: ✓ SATISFIED | 03-01: "Structured SSE error events" | [ ] | **satisfied** |
| API-05 | Phase 3: ✓ SATISFIED | 03-02: "revoke_role 404" | [ ] | **satisfied** |
| API-06 | Phase 3: ✓ SATISFIED | 03-02: "get_me 501 when auth disabled" | [ ] | **satisfied** |
| API-07 | Phase 3: ✓ SATISFIED | 03-02: "get_stats logs warning on failure" | [ ] | **satisfied** |
| API-08 | Phase 3: ✓ SATISFIED | 03-02: "get_segment JOIN via selectinload" | [ ] | **satisfied** |

### Agent & Retrieval (Phase 3 + Phase 5)

| Req | VERIFICATION | SUMMARY Provides | REQ.md | Final |
|-----|-------------|-----------------|--------|-------|
| AGNT-01 | Phase 3: ✓ SATISFIED | 03-03: "Corrected QUERY_DATABASE_TOOL schema" | [ ] | **satisfied** |
| AGNT-02 | Phase 3: ✓ SATISFIED | 03-01: "Fixed _chunk_text trailing-space" | [ ] | **satisfied** |
| AGNT-03 | Phase 3: ✓ SATISFIED | 03-03: "Post-rerank logging" | [ ] | **satisfied** |
| AGNT-04 | Phase 3+5: ✓ SATISFIED | 03-03+05-01: "SearchService Protocol" + "Protocol-typed agent.py" | [x] | **satisfied** |
| AGNT-05 | Phase 3: ✓ SATISFIED | 03-03: "CostTracker unknown model warning" | [ ] | **satisfied** |
| AGNT-06 | Phase 3: ✓ SATISFIED | 03-03: "Full SHA-256 cache key" | [ ] | **satisfied** |

### Frontend & Cleanup (Phase 4)

| Req | VERIFICATION | SUMMARY Provides | REQ.md | Final |
|-----|-------------|-----------------|--------|-------|
| FE-01 | Phase 4: ✓ SATISFIED | 04-01: "Stable React keys via UUID" | [x] | **satisfied** |
| FE-02 | Phase 4: ✓ SATISFIED | 04-01: "useCallback onClose" | [x] | **satisfied** |
| FE-03 | Phase 4: ✓ SATISFIED | 04-01: "Chained setTimeout polling" | [x] | **satisfied** |
| FE-04 | Phase 4: ✓ SATISFIED | 04-02: "CitationLink.tsx deleted" | [x] | **satisfied** |
| FE-05 | Phase 4: ✓ SATISFIED | 04-02: "require_auth removed" | [x] | **satisfied** |
| FE-06 | Phase 4: ✓ SATISFIED | Pre-satisfied | [x] | **satisfied** |
| FE-07 | Phase 4: ✓ SATISFIED | 04-01+04-02: "aria-labels on all elements" | [x] | **satisfied** |
| FE-08 | Phase 4: ✓ SATISFIED | 04-02: "Division-by-zero guard" | [x] | **satisfied** |
| FE-09 | Phase 4: ✓ SATISFIED | 04-01: "Conditional Content-Type" | [x] | **satisfied** |

### Tooling (Phase 1 + Phase 2 + Phase 5)

| Req | VERIFICATION | SUMMARY Provides | REQ.md | Final |
|-----|-------------|-----------------|--------|-------|
| TOOL-01 | Phase 1: ✓ (Truth 5, Ruff) | 01-01: "Expanded ruff rule set" | [ ] | **satisfied** |
| TOOL-02 | Phase 1: ✗ → Phase 5: ✓ | 01-01+05-01: "mypy config" + "cast() in deps.py" | [x] | **satisfied** |
| TOOL-03 | Phase 2: ✓ SATISFIED | 02-01: "Literal type validation" | [ ] | **satisfied** |
| TOOL-04 | Phase 2: ✓ SATISFIED | 02-01: "clear=True test isolation" | [ ] | **satisfied** |

---

## Orphaned Requirements Check

**Result:** No orphaned requirements detected.

All 39 requirements in the REQUIREMENTS.md traceability table appear in at least one phase VERIFICATION.md with explicit status determination. No requirement was assigned but absent from all verifications.

---

## Cross-Phase Integration

### E2E Flow Results

| Flow | Status | Trace |
|------|--------|-------|
| **Chat (SSE streaming)** | Complete | ChatInterface → useChat → streamChatMessage → ASGI middleware (P3) → chat_stream with conversation_id (P5) → agent with SearchService Protocol (P3/P5) → SSE events → frontend done handler preserves conversation_id (P5) → MessageBubble metrics (P5) |
| **Chat (non-streaming fallback)** | Complete | Streaming fails → apiSendMessage → ChatResponse aligned (P5) → useChat reads res.response (P5) → metrics attached → MessageBubble renders |
| **Document ingestion** | Complete | DocumentsPage → ingestFolder → ingest route with injected task_manager (P1) → pipeline with session_factory (P1) → ES store with lazy mapping (P1) → setTimeout polling (P4) → PaginatedResponse list (P3) |
| **Search** | Complete | SearchFilters with aria-labels (P4) → search route with SearchService Protocol (P3/P5) → hybrid_search with SHA-256 cache (P3) → post-rerank log (P3) |

### Previous Audit Broken Flows — Now Resolved

| Previous Issue | Resolution |
|----------------|------------|
| SSE done event missing conversation_id | Phase 5: chat.py injects `conversation_id` into done event; useChat.ts reads `event.conversation_id` |
| ChatResponse field mismatch (response vs message) | Phase 5: Frontend ChatResponse aligned; fallback reads `res.response` |
| RetrievalAgent typed as HybridSearchService | Phase 5: agent.py imports and uses `SearchService` Protocol |
| deps.py mypy no-any-return errors | Phase 5: All app.state accesses wrapped in `cast()` |
| Dead getAuthStatus() and listTasks() in client.ts | Phase 5: Both functions removed |

### Minor Integration Notes

| ID | Severity | Description |
|----|----------|-------------|
| INT-01 | Low | `useChat.ts:170` — non-streaming fallback maps `document_id: c.document_title ?? ""`. Backend citations don't include `document_id` UUID. No visible impact since `CitationTooltip` uses `segment_id`. |
| INT-02 | Info | Admin user/role management routes have no frontend consumer. Pre-existing design gap, out of milestone scope. |

---

## Tech Debt Summary

| Category | Count | Details |
|----------|-------|---------|
| Human verification items | 10 | Runtime behaviors requiring browser/DB testing (see phase VERIFICATIONs) |
| Minor data integrity | 1 | Citation document_id field mapping in fallback path (unused field) |
| Design gap (pre-existing) | 1 | Admin routes without frontend UI |

**Total: 12 items — 0 critical blockers**

---

## REQUIREMENTS.md Checkbox Status

28 of 39 requirements need their checkboxes updated from `[ ]` to `[x]`:
- SING-01 through SING-08, TOOL-01, TOOL-03, TOOL-04, DB-01 through DB-04, API-01 through API-08, AGNT-01 through AGNT-03, AGNT-05, AGNT-06

---

## Conclusion

**Milestone v1 (Code Quality Cleanup) has achieved its definition of done.** All 39 requirements are satisfied across 5 completed phases. The singleton lifecycle is fixed, database integrity is enforced, API endpoints are hardened with proper schemas and pagination, the frontend renders efficiently with accessibility improvements, and all gaps from the initial audit have been closed by Phase 5.

The milestone is ready for completion.

---

_Audited: 2026-02-19_
_Auditor: Claude (milestone-audit orchestrator + gsd-integration-checker)_
_Previous audit: 2026-02-18 (tech_debt → now passed after Phase 5)_
