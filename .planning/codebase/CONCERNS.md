# Codebase Concerns

**Analysis Date:** 2026-02-15

## Tech Debt

**Module-level singleton instances:**
- Issue: Global instances in `src/pam/api/deps.py` (`_embedder`, `_reranker`, `_search_service`, `_duckdb_service`) managed with asyncio locks. Risk of stale state if config changes after startup, and double-check locking pattern is subtle (requires careful code review on any modifications).
- Files: `src/pam/api/deps.py:44-118`
- Impact: Difficult to test (requires manual cache clearing), potential for shared state bugs if modules are reused across contexts
- Fix approach: Consider dependency injection or factory patterns with proper cleanup. Document singleton lifetime explicitly.

**Broad exception handling:**
- Issue: Pervasive `except Exception:` handlers catch all errors including transient failures and programming bugs, making diagnostics harder. 20+ instances across codebase.
- Files: `src/pam/ingestion/pipeline.py:126,137`, `src/pam/agent/agent.py:340`, `src/pam/retrieval/hybrid_search.py:113`, `src/pam/common/database.py:65`, and 15+ others
- Impact: Silent failures logged only as "error" with no traceback context for API errors, search failures, or ingestion errors
- Fix approach: Replace with specific exception handlers (e.g., `except (TimeoutError, ConnectionError):`). Add structured exception types for domain-specific errors.

**Hardcoded request limits:**
- Issue: Magic numbers throughout code without centralized config:
  - `MAX_TOOL_ITERATIONS = 5` in `src/pam/agent/agent.py:47`
  - `max_tokens=4096` hardcoded in 3 places in agent
  - `top_k=10` hardcoded in `src/pam/agent/agent.py:383`
  - `num_candidates = top_k * 10` in `src/pam/retrieval/hybrid_search.py:96`
- Files: `src/pam/agent/agent.py:47,115,240,303`, `src/pam/retrieval/hybrid_search.py:96`, `src/pam/agent/duckdb_service.py:35`
- Impact: Can't tune performance without code changes, different limits inconsistently applied
- Fix approach: Move all limits to `src/pam/common/config.py` (Settings class). Add docstrings explaining rationale.

**Google API credential handling:**
- Issue: Lazy-init pattern in `GoogleDocsConnector._get_service()` and `GoogleSheetsConnector._get_sheets_service()` doesn't validate credentials exist until first use. No retry logic for transient auth failures.
- Files: `src/pam/ingestion/connectors/google_docs.py:29-43`, `src/pam/ingestion/connectors/google_sheets.py:40-58`
- Impact: Ingestion tasks fail silently if credentials invalid. Errors only logged when document fetch attempted.
- Fix approach: Validate credentials during connector initialization. Add exponential backoff for Google API rate limits (currently none).

**Insecure default JWT secret:**
- Issue: Default `jwt_secret = "dev-secret-change-in-production-32b"` only validates via `model_validator` when `AUTH_REQUIRED=true`. Dev mode uses weak secret.
- Files: `src/pam/common/config.py:35,72-81`
- Impact: Dev instances with `AUTH_REQUIRED=false` don't trigger validation. If accidentally deployed with auth enabled, weak secret breaks security.
- Fix approach: Always validate JWT secret length (>= 32 chars). Add startup warning if default secret used in any mode.

## Known Bugs

**Segment ID UUID fallback generates non-deterministic IDs:**
- Symptoms: When ES document lacks `meta.segment_id`, code falls back to `uuid.uuid5(uuid.NAMESPACE_URL, hit["_id"])`, but re-indexing the same document creates new UUIDs instead of reusing old ones.
- Files: `src/pam/retrieval/hybrid_search.py:131-137`
- Trigger: After re-ingestion, search results reference different segment IDs even for unchanged segments
- Workaround: Ensure ES always contains `meta.segment_id` in ingestion pipeline (currently done in `src/pam/ingestion/pipeline.py`, so rare)

**Stale ingestion task recovery incomplete:**
- Symptoms: Orphaned "running" tasks from previous crashes are marked failed at startup, but memory registry `_running_tasks` in `src/pam/ingestion/task_manager.py:30` may still reference dead asyncio tasks
- Files: `src/pam/ingestion/task_manager.py:30`, `src/pam/api/main.py:55-62`
- Trigger: Server crash during ingestion, then restart
- Workaround: Manual cleanup of `_running_tasks` not needed in practice (tasks garbage collected), but lingering references could cause edge case bugs if task status is queried while cleanup in flight

**Elasticsearch failures after PostgreSQL commit:**
- Symptoms: If ES indexing fails after PG commit in pipeline, documents are in PG but missing from search index. No automatic re-sync mechanism.
- Files: `src/pam/ingestion/pipeline.py:122-132`
- Trigger: ES cluster goes down mid-ingestion, or ES field mapping incompatible with indexed data
- Workaround: Manual re-ingestion required. Consider adding "reindex" endpoint to `src/pam/api/routes/admin.py`

**Cache key generation doesn't normalize queries:**
- Symptoms: Queries "revenue" and "revenue " (with trailing space) generate different cache keys, causing cache misses on identical searches.
- Files: `src/pam/common/cache.py:47-62`
- Trigger: User enters query with accidental whitespace
- Workaround: Manual cache invalidation. Fix in next iteration: `query.strip()` before key generation

## Security Considerations

**DuckDB SQL injection guard incomplete:**
- Risk: Regex `_FORBIDDEN_PATTERNS` in `src/pam/agent/duckdb_service.py:16-20` blocks INSERT/UPDATE/DELETE/DROP, but doesn't prevent:
  - COPY TO / COPY FROM (could read/write files)
  - Comments (-- comment with DROP inside)
  - String escaping tricks (e.g., 'DROP'||'  TABLE'  to bypass regex)
- Files: `src/pam/agent/duckdb_service.py:16-20,79-91`
- Current mitigation: Whitelist-only approach would be safer, but codebase uses blacklist
- Recommendations:
  1. Use DuckDB's read-only connection mode if available
  2. Add COPY pattern to forbidden list
  3. Strip comments before validation
  4. Consider running DuckDB in subprocess with file descriptors (no file system access)

**Auth disabled by default in development:**
- Risk: `AUTH_REQUIRED=false` makes all admin routes fully open (create/delete documents, assign roles, trigger ingestion)
- Files: `src/pam/api/main.py:48-53`, `src/pam/api/routes/admin.py` (all routes lack auth checks when AUTH_REQUIRED=false)
- Current mitigation: Warning logged at startup
- Recommendations:
  1. Require explicit `ALLOW_UNAUTHENTICATED_ADMIN=true` to disable auth
  2. Add role-based access checks even when auth disabled (for defense-in-depth)
  3. Fail-open on auth config errors (reject requests instead of allowing)

**Google API credentials stored in plain files:**
- Risk: `credentials_path` parameters in GoogleDocsConnector/GoogleSheetsConnector point to JSON files on disk containing OAuth2 tokens with file system permissions
- Files: `src/pam/ingestion/connectors/google_docs.py:37-38`, `src/pam/ingestion/connectors/google_sheets.py:46,56`
- Current mitigation: Relies on OS file permissions
- Recommendations:
  1. Support credential reading from environment variables (for 12-factor compliance)
  2. Rotate credentials periodically
  3. Use short-lived access tokens (refresh tokens stored separately)

**Role-based access control (RBAC) bypassed if auth disabled:**
- Risk: When `AUTH_REQUIRED=false`, `require_role()` in `src/pam/api/auth.py:97-133` returns None without checking roles
- Files: `src/pam/api/auth.py:97-133`, `src/pam/api/routes/documents.py` (uses require_role but bypassed)
- Impact: Development/testing mode has no access control on projects
- Recommendations: Add role-checking even in disabled-auth mode for staging environments

## Performance Bottlenecks

**Embedding API calls not batched optimally:**
- Problem: `OpenAIEmbedder.embed_texts_with_cache()` embeds all chunks in a single API call. If 500+ chunks in large document, could exceed token limits or timeout.
- Files: `src/pam/ingestion/embedders/openai_embedder.py` (not examined; inferred from `src/pam/ingestion/pipeline.py:79`)
- Cause: No client-side batching; relies on OpenAI to auto-split
- Improvement path: Implement chunked batching (e.g., 100 texts per API call) with concurrency control

**Search response always loads full content into memory:**
- Problem: `HybridSearchService.search()` fetches top_k results and loads all content for cache, even if only snippets needed for response
- Files: `src/pam/retrieval/hybrid_search.py:159-168`
- Cause: Cache stores full SearchResult objects (including `content` field)
- Improvement path: Lazy-load content only when rendering response; cache metadata separately from content

**Ingestion task progress updates cause N database commits:**
- Problem: Each document triggers callback in `src/pam/ingestion/task_manager.py:109-138` which commits status update. Large ingestions with 100+ docs = 100+ commits.
- Files: `src/pam/ingestion/task_manager.py:109-138` (on_progress callback)
- Cause: Callback updates task record after each document
- Improvement path: Batch progress updates (e.g., every 10 documents or 1 second). Trade off latency for throughput.

**Reranking runs synchronously in search path:**
- Problem: `HybridSearchService.search()` calls `await self.reranker.rerank()` synchronously, blocking results until cross-encoder finishes
- Files: `src/pam/retrieval/hybrid_search.py:154-156`
- Cause: ReRanker uses CPU-bound models (cross-encoder inference)
- Improvement path: Move reranking to background task if user can tolerate slightly stale results; cache reranked results

## Fragile Areas

**Agent streaming response state machine:**
- Files: `src/pam/agent/agent.py:209-342`
- Why fragile: Complex state tracking with `answer_already_emitted`, `tool_call_count`, and multiple yield paths. Hard to trace all possible code paths.
  - Phase A (tool-use loop), Phase B (streaming final answer), Phase C (citations) can interact in unintuitive ways
  - Test coverage: `tests/test_agent/test_agent.py:535` (only 535 lines for 566-line agent)
- Safe modification: Add explicit state enum (`AnsweringPhase` with TOOL_LOOP, ANSWERING, DONE). Add assertions at phase boundaries.
- Test coverage: Missing tests for:
  - Streaming with zero tools (direct answer)
  - Streaming with max_tokens hit mid-tool-use
  - Streaming with tool returning empty results
  - Streaming error scenarios (ES down, LLM timeout)

**PostgreSQL-Elasticsearch consistency assumption:**
- Files: `src/pam/ingestion/pipeline.py:118-132`
- Why fragile: Code assumes PG is always in sync with ES due to commit order (PG first, then ES). If ES fails after PG commit, inconsistency isn't detected. Search returns outdated results.
- Safe modification: Add reconciliation logic:
  1. After successful PG commit, record which documents changed
  2. On ES indexing error, log doc IDs to a "failed_to_index" queue
  3. Add admin endpoint to re-sync from queue
- Test coverage: No tests for ES failure scenarios in `tests/test_ingestion/test_pipeline.py:261`

**Google Sheets region detection algorithm:**
- Files: `src/pam/ingestion/connectors/sheets_region_detector.py:201` (large file)
- Why fragile: Heuristic-based table detection (looks for patterns like "|" or "---"). Can misinterpret user data as table boundaries.
- Safe modification: Add explicit table boundary markers (e.g., `<!-- TABLE START -->` comments) for critical sheets. Document heuristic limitations.
- Test coverage: Tests in `tests/test_ingestion/test_sheets_connector.py:226`, but only cover happy-path formatting

**DuckDB service memory cleanup:**
- Files: `src/pam/agent/duckdb_service.py:102-145`
- Why fragile: Each query creates new in-memory DuckDB connection, loads all data files. Large data files (>1GB) could cause OOM.
- Safe modification: Add connection caching with TTL, limit data file sizes, add query timeouts.
- Test coverage: `tests/test_agent/test_duckdb_service.py:183` only tests small mock files

## Scaling Limits

**Database connection pool underprovisioned:**
- Current capacity: `pool_size=5, max_overflow=10` in `src/pam/common/database.py:17-18`
- Limit: 15 concurrent DB connections. With 100+ concurrent API requests, connections queue and requests timeout.
- Scaling path:
  1. Increase pool_size to 20 and max_overflow to 30 for ~50 concurrent requests
  2. Monitor pool utilization via structured logs
  3. Consider connection pooling proxy (PgBouncer) at scale

**Elasticsearch RRF num_candidates multiplier:**
- Current capacity: `num_candidates = top_k * 10` in `src/pam/retrieval/hybrid_search.py:96`
- Limit: With top_k=100, num_candidates=1000, ES scans 1000 docs for KNN before RRF fusion. Slows down for large indices (>10M docs).
- Scaling path: Make multiplier configurable in settings. Tune empirically (lower multiplier = faster but less accurate).

**Redis cache key explosion:**
- Current capacity: Unbounded cache keys generated per search permutation (query + top_k + source_type + project + date_range)
- Limit: With high query diversity, Redis memory grows unbounded (TTL mitigates but doesn't prevent spikes)
- Scaling path:
  1. Add LRU eviction policy (`ALLKEYS-LRU`) to Redis config
  2. Monitor cache hit rate; if <50%, disable caching
  3. Use query normalization (lemmatization, lowercasing) to improve hit rate

**Ingestion task tracking in memory:**
- Current capacity: `_running_tasks: dict[uuid.UUID, asyncio.Task]` in `src/pam/ingestion/task_manager.py:30` holds all active tasks
- Limit: With 100+ concurrent ingestions, dict grows large (though tasks are garbage collected on completion)
- Scaling path: Move task tracking to database (already have IngestionTask ORM model). Use status column instead of in-memory dict.

## Dependencies at Risk

**Docling parser dependency:**
- Risk: Docling is heavy dependency (imports torch for ML-based parsing). Adds 500MB+ to Docker image. Risk of breaking changes in minor versions.
- Impact: Can't easily switch parsers (would require rewriting parsing pipeline)
- Migration plan: Consider abstracting parser interface further, adding adapter for alternative parsers (pypdf, pptx). Document switching cost.

**Cross-encoder reranking optional but slow:**
- Risk: `cross-encoder/ms-marco-MiniLM-L-6-v2` model download happens on first query (blocking). No fallback if model download fails.
- Impact: First reranked search query hangs while downloading model from HuggingFace
- Migration plan: Pre-download model on startup if enabled. Add timeout to prevent hanging.

**Google API client version pinning:**
- Risk: `google-api-python-client` and `google-auth-oauthlib` versions not pinned in `src/pam/ingestion/connectors/google_docs.py` (dynamic imports). Breaking changes not caught until runtime.
- Impact: Connector suddenly fails after dependency update
- Migration plan: Explicitly pin versions in pyproject.toml with upper bounds (e.g., `google-api-python-client>=2.80,<3.0`)

## Missing Critical Features

**No audit logging for sensitive operations:**
- Problem: Document creation/deletion, user role assignments, and query database tool use aren't logged with user context
- Blocks: Compliance requirements (SOC 2, HIPAA) for data access tracking
- Recommendation: Add audit_log table and middleware to capture user, timestamp, resource, action for all admin endpoints

**No rate limiting on API endpoints:**
- Problem: Unbounded requests to `/chat` and `/search` endpoints can DOS the service
- Blocks: Production deployment; makes service vulnerable to abuse
- Recommendation: Implement sliding-window rate limiter (e.g., 10 requests/minute per IP) using Redis or in-memory counter. Add to middleware.

**No data retention/deletion policies:**
- Problem: Documents, segments, and conversation history stored indefinitely; no way to delete old data for privacy compliance
- Blocks: GDPR "right to be forgotten" requests
- Recommendation: Add `deleted_at` soft-delete columns to Document/Segment/Conversation. Add admin endpoint to hard-delete after retention period.

**No monitoring/alerting for search quality:**
- Problem: No metrics on search relevance, citation accuracy, or tool failure rates. Can't detect degradation.
- Blocks: Ability to catch regressions in production
- Recommendation: Add structured metrics logging for:
  - Search result click-through rate (if user feedback available)
  - Citation accuracy (source appears in top-k)
  - Tool error rates per tool type
  - Agent conversation completion rate

## Test Coverage Gaps

**Streaming response error handling:**
- What's not tested: Error scenarios during streaming (ES down mid-stream, LLM timeout during token stream)
- Files: `src/pam/agent/agent.py:209-342`
- Risk: Clients may receive malformed SSE events or incomplete answers on error
- Priority: High (streaming is user-facing critical path)

**Google API pagination and large result sets:**
- What's not tested: Paginating through >1000 files in Google Drive folder, malformed API responses
- Files: `src/pam/ingestion/connectors/google_sheets.py:85-101`, `src/pam/ingestion/connectors/google_docs.py:45-71`
- Risk: Ingestion silently stops partway through large folder if pagination breaks
- Priority: Medium

**Database transaction rollback edge cases:**
- What's not tested: Rollback during concurrent modifications (two ingestions modifying same document), partial segment saves
- Files: `src/pam/ingestion/pipeline.py:137-140`
- Risk: Inconsistent database state if transaction fails mid-stream
- Priority: Medium

**DuckDB query timeouts and resource limits:**
- What's not tested: Queries that scan entire dataset, memory allocation limits, long-running aggregations
- Files: `src/pam/agent/duckdb_service.py:102-145`
- Risk: Malicious or accidental DuckDB queries can exhaust memory and crash agent process
- Priority: High (security)

**Cache invalidation edge cases:**
- What's not tested: Cache invalidation when segment updated (not just document re-ingested), concurrent cache writes
- Files: `src/pam/common/cache.py:1-152`
- Risk: Stale results served after document updated
- Priority: Medium

---

*Concerns audit: 2026-02-15*
