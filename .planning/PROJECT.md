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
- ✓ Service singletons via FastAPI lifespan + app.state with full test isolation — v1
- ✓ Database indexes (content_hash, FK) and CHECK constraints via concurrent migration — v1
- ✓ Pure ASGI middleware for unbuffered SSE streaming with structured error events — v1
- ✓ Cursor-based pagination on all list endpoints — v1
- ✓ SearchService Protocol for type-safe search backend polymorphism — v1
- ✓ Agent tool schema correctness, SHA-256 cache keys, post-rerank logging — v1
- ✓ React rendering fixes (stable keys, smart scroll, setTimeout polling) — v1
- ✓ Accessibility (aria-labels on all interactive elements) — v1
- ✓ Dead code removal across backend and frontend — v1
- ✓ Expanded ruff/mypy tooling with strict configuration — v1

### Active

- [ ] Neo4j + Graphiti bi-temporal knowledge graph — v2.0
- [ ] LLM-driven entity extraction with auto-discovered schemas — v2.0
- [ ] Entity-to-graph pipeline mapping extracted entities to Neo4j nodes and temporal edges — v2.0
- [ ] Graph-aware retrieval agent tool (query_graph) for relationship and temporal queries — v2.0
- [ ] Change detection diff engine with semantic change classification and graph edge versioning — v2.0
- [ ] Visual graph explorer UI via @neo4j-nvl/react — v2.0

### Out of Scope

- Major new features — direction TBD after cleanup
- Auth hardening beyond current JWT/OAuth — deferred
- Production deployment pipeline — deferred
- Mobile app — web-first
- Comprehensive frontend test coverage — deferred to v2 (TEST-01 through TEST-05)
- ESLint for frontend build pipeline — deferred to v2 (FEINF-01, FEINF-02)
- Full mypy strict mode — deferred to v2 (PROD-03)

## Context

v1 Code Quality Cleanup is shipped. The codebase has 5,304 LOC Python and 2,818 LOC TypeScript with 450+ passing tests. All 39 findings from the code review campaign (7 GitHub issues) have been resolved across 5 phases. The singleton lifecycle is fixed, database integrity is enforced, API endpoints are hardened with proper schemas and pagination, the frontend renders efficiently with accessibility improvements, and all integration gaps are closed.

Tech stack: Python 3.12 + FastAPI + SQLAlchemy async + Elasticsearch 8.x + PostgreSQL 16 + React 18 + TypeScript + Vite + Tailwind. Infrastructure: Docker Compose with PG, ES, Redis.

## Constraints

- **Tech stack**: Python 3.12 + FastAPI + SQLAlchemy async + Elasticsearch 8.x + PostgreSQL 16 + React 18 + TypeScript (established, not changing)
- **Testing**: Must maintain 450+ passing tests; new work should include tests
- **Backward compatibility**: API contracts and frontend behavior are stable

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Simple agent loop over LangGraph | Lower complexity, easier to debug, ~180 lines | ✓ Good |
| Dual-store PG + ES | PG as source of truth, ES for search; graceful degradation if ES fails | ✓ Good |
| Haystack as optional backend | Flexibility without forcing migration; toggled via env var | — Pending |
| Module-level singletons → lifespan + app.state | Quick to implement originally, but blocked testing. Migrated in v1 to FastAPI lifespan. | ✓ Good (resolved) |
| No auth in Phase 1 | Simplified initial development | ✓ Good |
| Synchronous ingestion | Simple but blocks on large document sets | — Pending |
| Pure ASGI over BaseHTTPMiddleware | BaseHTTPMiddleware buffers SSE streams. Well-documented Starlette limitation. | ✓ Good |
| Protocol over ABC for SearchService | Structural subtyping without inheritance changes to existing services | ✓ Good |
| Cursor-based pagination over OFFSET | O(1) seek, stable under concurrent writes, no skip penalty | ✓ Good |
| cast() over type: ignore for app.state | Explicit types, zero mypy suppression | ✓ Good |
| conversation_id generated at API layer | Keeps agent stateless; chat.py generates UUID, not agent.py | ✓ Good |

---
*Last updated: 2026-02-19 after v2.0 milestone start*
