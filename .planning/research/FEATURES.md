# Feature Landscape: Code Quality Cleanup Milestone

**Domain:** Code quality stabilization for a Python/FastAPI knowledge retrieval system
**Researched:** 2026-02-15
**Source material:** 7 open GitHub issues (#32, #36, #37, #38, #39, #40, #43) totaling ~40 findings

## Table Stakes

Must-fix items. Ignoring these degrades correctness, performance, or testability. Grouped by theme.

### Database Integrity & Performance

| Feature | Why Expected | Complexity | Issue | Notes |
|---------|--------------|------------|-------|-------|
| Add index on `Segment.document_id` FK | PostgreSQL does NOT auto-index FK columns. CASCADE deletes and segment listing queries degrade linearly with row count. | Low | #39 | Alembic migration. This is the highest-impact single fix -- every document view and delete operation hits this. |
| Add index on `Document.content_hash` | Pipeline dedup lookups by content_hash do full table scan. | Low | #39 | Alembic migration. |
| Add composite index on `Document(source_type, source_id)` | Already has a unique constraint (`uq_documents_source`) which implicitly creates an index. Verify -- may already be covered. | Low | #39 | Check if UniqueConstraint auto-creates index (it does in PostgreSQL). If so, this is a no-op. |
| Add `CHECK` constraint on `UserProjectRole.role` | DB column accepts any string up to 20 chars. Direct SQL inserts can introduce invalid roles (`viewer`/`editor`/`admin`). | Low | #39 | Alembic migration. |

**Confidence:** HIGH -- PostgreSQL FK indexing behavior is well-documented. UniqueConstraint does create an implicit index, so `source_type+source_id` likely needs no additional index.

### API Correctness

| Feature | Why Expected | Complexity | Issue | Notes |
|---------|--------------|------------|-------|-------|
| Add `response_model` to endpoints missing it | 5+ endpoints return plain dicts. No OpenAPI schema, no response validation, no documentation. | Low | #43 | `routes/documents.py:16,25,60`, `routes/admin.py:90,113,119`. Create Pydantic response models. |
| Add pagination to `list_documents` | Returns ALL documents. Pattern already exists in `ingest.py` but not applied here. Will break with >100 docs. | Med | #43 | Standard `offset`/`limit` pattern. |
| Fix `revoke_role` to return 404 when role doesn't exist | Returns 204 even when nothing was deleted. Silent failure is a bug. | Low | #43 | Add `rowcount` check after DELETE. |
| Fix `get_me` returning 404 when auth disabled | Semantically incorrect. 404 means "resource not found", not "feature disabled". | Low | #43 | Return 200 with null user or 501 Not Implemented. |
| Fix streaming error not wrapped in SSE format | Errors before generator entry produce broken/unreadable streams on the frontend. | Med | #43 | Wrap error in `data: {"type": "error", ...}\n\n` format. |
| Fix `get_stats` silently swallowing entity query failures | Bare `except Exception` returns empty dict with no indication of failure. | Low | #43 | Log warning (already partially done with `exc_info=True`) and include error indicator in response. |
| Use JOIN instead of 2 sequential queries in `get_segment` | Makes 2 DB roundtrips for segment + parent document. Unnecessary -- can use `joinedload`. | Low | #43 | SQLAlchemy `joinedload(Segment.document)`. |

**Confidence:** HIGH -- these are all verified by reading the actual source code.

### Agent Robustness

| Feature | Why Expected | Complexity | Issue | Notes |
|---------|--------------|------------|-------|-------|
| Add `required` fields to tool schemas | `GET_DOCUMENT_CONTEXT_TOOL` and `QUERY_DATABASE_TOOL` lack `required` in `input_schema`. Claude can call them with no arguments, producing confusing error paths. | Low | #37 | Add `"required": ["document_title"]` (or make at-least-one logic explicit). `QUERY_DATABASE_TOOL` already has `required: ["sql"]` -- verify. |
| Handle unexpected `stop_reason` (e.g., `max_tokens`) | Already partially handled (warning logged, fallback text returned). Verify streaming path also handles it. | Low | #37 | Code review shows this IS handled as of the proxy fix. Mark as verified/done if so. |
| Fix `_chunk_text` leading space on non-first chunks | Every chunk after the first starts with `" "`, causes rendering quirks in frontend. | Low | #37 | Fix the join logic to not prepend space. |

**Confidence:** HIGH -- verified by reading `tools.py` and `agent.py`.

### Singleton & Initialization Hygiene

| Feature | Why Expected | Complexity | Issue | Notes |
|---------|--------------|------------|-------|-------|
| Fix `INDEX_MAPPING` computed at import time | `elasticsearch_store.py:18` uses `settings.embedding_dims` at import, baking in the value. Forces settings init at import. | Med | #36 | Make it a function or classmethod. Touches ES index creation flow. |
| Fix stale DuckDB table cache | `_tables` cached after first `register_files()`. Files added/removed later are invisible until restart. | Low | #37 | Add cache invalidation or lazy re-scan. |
| Fix search service singleton holding stale Redis reference | If Redis reconnects, cached service has old client. | Med | #43 | Either re-fetch Redis on each call or add reconnect awareness. |

**Confidence:** HIGH -- the `settings` proxy pattern (#32) was already fixed in commit `2263074`. The remaining singleton issues are in ES store, DuckDB, and search service singletons in `deps.py`.

### Observability & Correctness

| Feature | Why Expected | Complexity | Issue | Notes |
|---------|--------------|------------|-------|-------|
| Fix log emitted before reranking | `hybrid_search.py:128`: result count logged before reranker truncates, misleading for debugging. | Low | #38 | Move log after reranker step. |
| Update `CostTracker` hardcoded pricing | Pricing for Claude models hardcoded "as of 2025". Unknown models silently fall back to Sonnet pricing. | Low | #39 | Log warning for unknown models. Consider making pricing configurable or fetching from a mapping. |
| Fix `test_env_override` missing `clear=True` | CI environment variables leak into test. | Low | #39 | Add `clear=True` to `mock.patch.dict`. |

**Confidence:** HIGH -- verified in source.

### BaseHTTPMiddleware Streaming Breakage

| Feature | Why Expected | Complexity | Issue | Notes |
|---------|--------------|------------|-------|-------|
| Convert `BaseHTTPMiddleware` to pure ASGI middleware | `BaseHTTPMiddleware` buffers streaming responses. Known Starlette issue -- breaks SSE streaming for `/chat/stream`. | Med | #43 | Starlette docs explicitly recommend pure ASGI middleware for streaming. The middleware is simple (correlation ID + request logging) so conversion is straightforward. |

**Confidence:** HIGH -- this is a well-documented Starlette/FastAPI issue confirmed by official docs.

## Differentiators

Nice improvements. Not blocking correctness but raise code quality materially.

### Code Hygiene

| Feature | Value Proposition | Complexity | Issue | Notes |
|---------|-------------------|------------|-------|-------|
| Add `Protocol` for search services | `deps.py:67` returns `HybridSearchService` type even when returning `HaystackSearchService`. No shared interface. Adding a Protocol enables type-safe polymorphism. | Low | #38 | Define `SearchService(Protocol)` with `search()` method. |
| Remove dead `CitationLink` component | `CitationLink.tsx` not imported anywhere. Dead code clutters codebase. | Low | #40 | Delete file. |
| Remove dead `require_auth` function | `auth.py:82-90`: Comment says "return placeholder" but actually raises 403. Never called by any route. | Low | #43 | Delete or document why it exists. |
| Remove unused `orig_idx` variable in `openai_embedder.py` | Unpacked but never used. | Low | #36 | One-line fix. |
| Use `Literal["viewer", "editor", "admin"]` instead of regex for `AssignRoleRequest.role` | More self-documenting. Regex pattern works but `Literal` is idiomatic Pydantic. | Low | #39 | One-line change. |

### Frontend Stability

| Feature | Value Proposition | Complexity | Issue | Notes |
|---------|-------------------|------------|-------|-------|
| Fix React array index keys for messages | `ChatInterface.tsx:57`: Fragile if messages are filtered/reordered during streaming. | Low | #40 | Use message ID or content hash as key. |
| Fix `useCallback` missing for `onClose` in `SourceViewer` | Arrow function recreated every render, causing effect churn. | Low | #40 | Wrap with `useCallback`. |
| Fix overlapping poll requests in `useIngestionTask` | `setInterval` fires regardless of previous call completing. Can stack requests. | Low | #40 | Use chained `setTimeout` instead. |
| Fix `Content-Type: application/json` on GET requests | Unnecessary but harmless. Technically incorrect per HTTP spec. | Low | #40 | Remove header for GET methods. |

### Test Coverage Gaps

| Feature | Value Proposition | Complexity | Issue | Notes |
|---------|-------------------|------------|-------|-------|
| Add tests for `configure_logging()` | Thin wrapper but a smoke test catches breakage. | Low | #39 | One test. |
| Add tests for `close_redis()` edge cases | Calling when already `None` is untested. | Low | #39 | One test. |
| Add test for empty chunk list in pipeline | No test for this edge case. | Low | #36 | One test. |
| Add tests for `cancelStreaming` path in `useChat` | Untested async cancellation. | Med | #40 | Frontend test. |
| Add tests for `useDocuments`, `useIngestionTask`, `useAuth` hooks | Zero test coverage. | Med | #40 | Frontend tests. |
| Add tests for `markdown.ts` processing utilities | Zero test coverage. | Low | #40 | Frontend tests. |
| Add tests for eval module (`judges.py`, `run_eval.py`) | JSON parsing fallback and scoring logic untested. | Med | #40 | Python tests. |

### Credential & Cache Safety

| Feature | Value Proposition | Complexity | Issue | Notes |
|---------|-------------------|------------|-------|-------|
| Share credentials between Google Drive and Sheets services | `google_sheets.py:37-51`: Creates separate `Credentials` per service. Could race on token refresh. | Med | #36 | Refactor to share a single credentials instance. |
| Validate `credentials_path` in `GoogleSheetsConnector` | Unlike `GoogleDocsConnector`, no check for `None`. | Low | #36 | Add validation. |
| Increase cache key hash to full SHA-256 | `cache.py:48`: `sha256()[:16]` gives 64-bit entropy. Fine for short TTL but unnecessary truncation. | Low | #38 | Use full hex digest or at least 128 bits (32 chars). |

### Accessibility

| Feature | Value Proposition | Complexity | Issue | Notes |
|---------|-------------------|------------|-------|-------|
| Add `aria-label` to interactive elements | `SearchFilters.tsx`, `DocumentsPage.tsx`, `ChatPage.tsx`. Minor accessibility concern. | Low | #40 | Add labels to buttons, inputs. |

### Eval Robustness

| Feature | Value Proposition | Complexity | Issue | Notes |
|---------|-------------------|------------|-------|-------|
| Fix division by zero in `print_summary` | Empty `questions.json` causes `ZeroDivisionError`. | Low | #40 | Guard division. |
| Improve keyword overlap heuristic | 20% threshold produces false positives. | Med | #40 | Acknowledged as simple heuristic. Improve or document acceptable false positive rate. |

## Anti-Features

Things to deliberately NOT do during this cleanup milestone.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Major architectural refactoring | This is a cleanup milestone, not a rewrite. Changing module boundaries or data flow risks introducing new bugs and scope creep. | Fix the specific issues identified. Save architectural changes for a feature milestone. |
| Adding new features (new tools, new connectors, new API endpoints) | Cleanup milestone should stabilize what exists, not grow the surface area. New features dilute focus and add untested code. | Document feature ideas in backlog issues. |
| Migrating from `structlog` to another logging framework | The logging stack works. CostTracker pricing is the only issue, and that's a data update, not a framework swap. | Update pricing data. Log warnings for unknown models. |
| Adding Redis Sentinel or Redis Cluster support | The stale Redis reference issue is about reconnection handling in a singleton, not about Redis HA. | Fix the singleton lifecycle. |
| Rewriting the agent tool loop | The tool loop works correctly. Issues are cosmetic (spacing in `_chunk_text`) or defensive (missing `required` fields). | Make targeted fixes. |
| Converting all endpoints to use `response_model` at once | Some endpoints return complex nested structures (e.g., `get_stats`). Forcing Pydantic models for everything adds busywork. | Add `response_model` where it provides real value (list endpoints, CRUD endpoints). Leave complex stats responses as documented dicts if needed. |
| Adding comprehensive frontend test coverage | Frontend tests for hooks and components are a differentiator, not table stakes for a backend-focused cleanup. The frontend works. | Fix the specific React bugs (keys, useCallback, polling). Add hook tests only if time permits. |
| Replacing `BaseHTTPMiddleware` with a third-party middleware framework | The fix is converting 2 simple middleware classes to pure ASGI. No framework needed. | Write pure ASGI middleware directly following Starlette docs. |
| Adding type: ignore removal campaign | The `# type: ignore[assignment]` comments on proxy objects are intentional design choices. Removing them requires redesigning the proxy pattern. | Leave them. They're documented. |
| Full Alembic migration squash | Multiple migrations exist and work. Squashing risks breaking existing deployments. | Add new migration for indexes and constraints. |

## Feature Dependencies

```
Database indexes (Alembic migration) --> No dependencies, can be done first
   |
   +--> [Independent] response_model additions
   +--> [Independent] pagination on list_documents
   +--> [Independent] dead code removal

BaseHTTPMiddleware fix --> Streaming error SSE format fix (both touch streaming path)

Protocol for search services --> Independent, but should be done before any search refactoring

Tool schema required fields --> Independent, low risk

Singleton fixes (ES mapping, DuckDB cache, search service) --> Somewhat interdependent
   |
   +--> ES INDEX_MAPPING fix (touches elasticsearch_store.py init)
   +--> DuckDB stale cache (touches duckdb_service.py)
   +--> Search service stale Redis (touches deps.py)

Frontend fixes --> All independent of each other, all independent of backend fixes
```

## Priority Recommendation

### Phase 1: Foundation fixes (do first)

1. **Database indexes** -- Highest impact, lowest risk. Single Alembic migration.
2. **BaseHTTPMiddleware conversion** -- Fixes streaming breakage. Prerequisite for SSE error handling fix.
3. **Tool schema `required` fields** -- Prevents silent agent failures.
4. **ES `INDEX_MAPPING` import-time fix** -- Removes surprising init behavior.

### Phase 2: API hardening

5. **`response_model` additions** -- Better OpenAPI docs, response validation.
6. **Pagination on `list_documents`** -- Prevents unbounded queries.
7. **Fix `get_segment` to use JOIN** -- Simple optimization.
8. **Fix `revoke_role`, `get_me`, `get_stats` correctness** -- Small bug fixes.
9. **Streaming error SSE format** -- Depends on middleware fix from Phase 1.

### Phase 3: Agent & retrieval polish

10. **Fix `_chunk_text` spacing** -- Cosmetic but visible to users.
11. **Fix log ordering in hybrid_search** -- Observability improvement.
12. **Add `Protocol` for search services** -- Type safety improvement.
13. **Fix stale DuckDB cache, stale Redis reference** -- Robustness improvements.
14. **Update CostTracker pricing** -- Keep cost estimates accurate.

### Phase 4: Frontend & cleanup

15. **React key, useCallback, polling fixes** -- Low risk, high code quality.
16. **Remove dead code** -- CitationLink, require_auth, unused variable.
17. **Accessibility labels** -- Quick wins.
18. **Credential sharing in Google connectors** -- Med complexity, lower priority.

### Defer: Test coverage gaps, eval improvements

19. **Test coverage gaps** -- Address opportunistically when touching related code. Do not make a separate "write tests" phase.
20. **Eval improvements** -- Nice to have but eval tooling is secondary to production stability.

## Sources

- GitHub Issues #32, #36, #37, #38, #39, #40, #43 (primary source -- all findings verified against actual source code)
- [FastAPI Advanced Middleware docs](https://fastapi.tiangolo.com/advanced/middleware/) -- BaseHTTPMiddleware limitations
- [Starlette Middleware docs](https://www.starlette.io/middleware/) -- Pure ASGI middleware pattern
- [CYBERTEC: Index your Foreign Key](https://www.cybertec-postgresql.com/en/index-your-foreign-key/) -- PostgreSQL FK indexing
- [FastAPI Best Practices (zhanymkanov)](https://github.com/zhanymkanov/fastapi-best-practices) -- response_model, dependency injection patterns
- Codebase files: `src/pam/common/config.py`, `src/pam/common/database.py`, `src/pam/common/cache.py`, `src/pam/common/models.py`, `src/pam/api/deps.py`, `src/pam/api/routes/documents.py`, `src/pam/api/routes/chat.py`, `src/pam/api/middleware.py`, `src/pam/agent/tools.py`, `src/pam/agent/agent.py`, `src/pam/ingestion/stores/elasticsearch_store.py`, `src/pam/common/logging.py`
