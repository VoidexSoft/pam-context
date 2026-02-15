# PAM Context

## What This Is

A Business Knowledge Layer for LLMs. PAM Context ingests documents (Markdown, Google Docs, Google Sheets), parses them with Docling, stores them in Elasticsearch and PostgreSQL, and answers questions with citations via a Claude-powered retrieval agent. It includes a React frontend for chat, document management, and search.

## Core Value

Users can ask natural-language questions about their business documents and get accurate, cited answers from a Claude agent that searches across all ingested knowledge.

## Requirements

### Validated

- ✓ Document ingestion pipeline with Markdown, Google Docs, Google Sheets connectors — Phase 1
- ✓ Layout-aware parsing via Docling with hybrid chunking — Phase 1
- ✓ OpenAI embedding pipeline with content-hash caching — Phase 1
- ✓ Dual-store architecture: PostgreSQL (authoritative) + Elasticsearch (search index) — Phase 1
- ✓ Hybrid search with RRF combining BM25 + kNN vectors — Phase 1
- ✓ Optional Haystack 2.x retrieval backend — Phase 1
- ✓ Optional cross-encoder reranking — Phase 1
- ✓ Redis-backed search result caching — Phase 1
- ✓ Claude-powered retrieval agent with tool-use loop (search, document context, change history, DB query, entity search) — Phase 1
- ✓ FastAPI backend with chat, search, documents, ingest, admin, auth routes — Phase 1
- ✓ SSE streaming for chat responses — Phase 1
- ✓ React frontend with chat interface, document management, search filters, citation tooltips — Phase 1
- ✓ Structured logging with correlation IDs via structlog — Phase 1
- ✓ Optional JWT auth with Google OAuth2 flow — Phase 1
- ✓ Evaluation framework with question sets and judges — Phase 1
- ✓ Background ingestion tasks with status polling — Phase 1
- ✓ DuckDB integration for SQL analytics over data files — Phase 1
- ✓ Entity extraction and search — Phase 1

### Active

- [ ] Fix module-level singletons blocking testing and reconfiguration (GH #32)
- [ ] Fix ingestion code quality issues — chunk gaps, credentials, import-time settings (GH #36)
- [ ] Fix agent code quality issues — chunk text spacing, stale DuckDB cache, tool schemas (GH #37)
- [ ] Fix retrieval code quality issues — log ordering, cache key entropy, missing Protocol (GH #38)
- [ ] Fix common module issues — missing DB indexes, cost tracker staleness, role validation (GH #39)
- [ ] Fix frontend + eval issues — React keys, dead code, accessibility, eval edge cases (GH #40)
- [ ] Fix API issues — response models, dead code, pagination, streaming errors (GH #43)

### Out of Scope

- Major new features — direction TBD after cleanup
- Auth hardening beyond current JWT/OAuth — deferred
- Production deployment pipeline — deferred
- Mobile app — web-first

## Context

Phase 1 is complete with all 11 steps implemented. The codebase has 450+ passing tests. A code review campaign identified 7 GitHub issues (1 important, 6 minor) totaling ~40 individual findings across all modules. The immediate goal is stabilizing and cleaning up the existing code before deciding on the next direction.

The codebase follows established patterns: SQLAlchemy with Mapped[] types, Pydantic Settings, structlog with correlation IDs, FastAPI dependency injection, and content-hash deduplication.

## Constraints

- **Tech stack**: Python 3.12 + FastAPI + SQLAlchemy async + Elasticsearch 8.x + PostgreSQL 16 + React 18 + TypeScript (established, not changing)
- **Testing**: Must maintain 450+ passing tests; new fixes should include tests where practical
- **Backward compatibility**: Fixes should not break existing API contracts or frontend behavior

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Simple agent loop over LangGraph | Lower complexity, easier to debug, ~180 lines | ✓ Good |
| Dual-store PG + ES | PG as source of truth, ES for search; graceful degradation if ES fails | ✓ Good |
| Haystack as optional backend | Flexibility without forcing migration; toggled via env var | — Pending |
| Module-level singletons | Quick to implement but blocks testing (GH #32) | ⚠️ Revisit |
| No auth in Phase 1 | Simplified initial development | ✓ Good |
| Synchronous ingestion | Simple but blocks on large document sets | — Pending |

---
*Last updated: 2026-02-15 after initialization*
