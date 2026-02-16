# Project State: PAM Context

## Project Reference

See: .planning/PROJECT.md (updated 2026-02-15)

**Core value:** Users can ask natural-language questions about their business documents and get accurate, cited answers
**Current focus:** Phase 3 — API + Agent Hardening

## Current Phase

**Phase 3: API + Agent Hardening**
Status: In progress
Plans: 2/3 complete (03-01, 03-03 done)

## Milestone Progress

| Phase | Status | Plans | Progress |
|-------|--------|-------|----------|
| 1. Singleton Lifecycle + Tooling | ✓ Complete | 2/2 | 100% |
| 2. Database Integrity | ✓ Complete | 1/1 | 100% |
| 3. API + Agent Hardening | ◑ In progress | 2/3 | 67% |
| 4. Frontend + Dead Code Cleanup | ○ Not started | 0/TBD | 0% |

## Key Decisions

| Decision | Phase | Rationale |
|----------|-------|-----------|
| Keep config.py/database.py proxy pattern | 1 | Already correct with lru_cache + reset_*(). Only deps.py globals need refactoring. |
| Use lifespan + app.state for service singletons | 1 | FastAPI-recommended pattern, already partially used for ES/Redis clients. |
| Store anthropic_api_key/agent_model on app.state | 1 | Avoids importing settings in deps.py, keeps deps fully stateless. |
| ping_redis() accepts client parameter | 1 | Removes need for module-level Redis global in cache.py. |
| CREATE INDEX CONCURRENTLY for migrations | 2 | Avoids table locks on production data. |
| Single migration 005 for CHECK + CONCURRENT index | 2 | CHECK constraint first (transactional), then autocommit_block for index. |
| Literal type over Field(pattern=...) for role | 2 | Better mypy, OpenAPI enum schema, clearer error messages. |
| ORM index=True to sync models with DB schema | 2 | Keeps models.py as source of truth even for indexes created in earlier migrations. |
| Replace BaseHTTPMiddleware with pure ASGI | 3 | Fixes SSE streaming buffering. Well-documented Starlette limitation. |
| Structured SSE error with data + message fields | 3 | Machine-readable for frontend parsing, human-readable for display. |
| No done event after SSE error | 3 | Frontend handles cleanup in finally block without needing done after error. |
| Trailing-space chunking in _chunk_text | 3 | Eliminates leading-space artifacts on non-first SSE token events. |
| Protocol over ABC for SearchService | 3 | Structural subtyping without inheritance changes to existing services. |
| runtime_checkable for SearchService Protocol | 3 | Enables isinstance() checks at runtime if needed. |
| Empty required list for QUERY_DATABASE_TOOL | 3 | Explicit empty list rather than missing key; handler validates. |

### Blockers/Concerns

None currently.

## Performance Metrics

| Phase | Plan | Duration | Tasks | Files |
|-------|------|----------|-------|-------|
| 01 | 01 | 18min | 2 | 29 |
| 01 | 02 | 7min | 2 | 10 |
| 02 | 01 | 3min | 2 | 3 |
| 03 | 01 | 4min | 2 | 4 |
| 03 | 03 | 2min | 2 | 6 |

---
Last activity: 2026-02-16 - Plan 03-01 complete (pure ASGI middleware, structured SSE error events, trailing-space chunk text)
