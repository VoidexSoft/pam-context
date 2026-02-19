# Phase 3: API + Agent Hardening - Research

**Researched:** 2026-02-16
**Domain:** FastAPI API hardening, SSE streaming, ASGI middleware, cursor pagination, agent tool schemas
**Confidence:** HIGH

## Summary

Phase 3 is a correctness-and-reliability pass over the existing API and agent layers. No new features or endpoints are added. The work breaks down into three clusters: (1) API infrastructure -- replacing BaseHTTPMiddleware with pure ASGI middleware to fix SSE streaming buffering, adding cursor-based pagination to all list endpoints, and adding response_model to endpoints missing OpenAPI schemas; (2) SSE streaming error handling -- wrapping LLM API failures in structured SSE error events with both JSON and human-readable content; (3) Agent hardening -- fixing tool schema required fields, the `_chunk_text` leading-space artifact, log emission timing in hybrid_search, search service interface formalization, CostTracker unknown model warnings, and cache key hash length.

The codebase is well-structured with clear separation of concerns. All modifications are surgical -- each requirement maps to a specific file and function. The existing test infrastructure (pytest-asyncio, httpx AsyncClient with dependency overrides) is mature enough to cover all changes without new test tooling.

**Primary recommendation:** Work through changes file-by-file, starting with the ASGI middleware replacement (biggest structural change), then pagination (new shared module), then response_model additions and agent fixes (independent, parallelizable).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- SSE streaming & error handling: When LLM API fails mid-stream, send BOTH a structured `event: error` with JSON payload {type, message} AND human-readable text -- UI can choose how to display
- No retry on transient errors -- fail fast, send error event immediately, let user retry from UI
- ASGI middleware: Replace BaseHTTPMiddleware with pure ASGI middleware to fix SSE streaming buffering
- Cursor-based pagination (Nakama-style), NOT offset/limit
- Opaque base64-encoded cursor encoding last item's ID + sort field
- Empty string cursor = no more pages
- Response envelope: `{"items": [...], "total": N, "cursor": "base64..."}`
- Default page size: 50 items
- Apply pagination to all list endpoints, not just GET /documents
- get_me when auth disabled: return 501 Not Implemented
- CostTracker warning must include the model name: `"Unknown model 'claude-4-opus': using default cost estimate"`

### Claude's Discretion
- Stream lifecycle after error event (done then close, or just close)
- ASGI middleware scope (same as current or add request timing)
- Error response envelope format
- 404 message detail level
- get_stats partial failure handling
- Protocol vs ABC for search service interface
- Cache key hash length
- Chunk text whitespace fix approach

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | >=0.115 | API framework | Already in use, provides ASGI-native streaming |
| Starlette | (bundled) | ASGI middleware base, MutableHeaders, scope types | Used for pure ASGI middleware patterns |
| Pydantic | >=2.0 | Response models, pagination schemas | Already in use for all schemas |
| SQLAlchemy | >=2.0 (async) | DB queries, pagination queries | Already in use |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| base64 (stdlib) | -- | Cursor encoding/decoding | Opaque cursor pagination |
| json (stdlib) | -- | Cursor payload serialization | Cursor contents |
| structlog | >=24.0 | Logging (already in use) | CostTracker warnings, middleware logs |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled cursor pagination | fastapi-pagination library | Library adds dependency for what is ~50 lines of code; user wants Nakama-style specifically |
| Protocol (typing) | ABC (abc module) | Protocol is structural typing (duck typing); ABC is nominal. Project already uses ABC for BaseReranker. Decision is at Claude's discretion |

**Installation:** No new dependencies needed. All required libraries are already installed.

## Architecture Patterns

### Recommended Project Structure
The changes touch existing files only. No new modules beyond a shared pagination utility:
```
src/pam/
├── api/
│   ├── middleware.py       # REWRITE: pure ASGI middleware (CorrelationId + RequestLogging)
│   ├── pagination.py       # NEW: cursor encode/decode, PaginatedResponse schema, paginate() helper
│   ├── routes/
│   │   ├── documents.py    # MODIFY: add response_model, pagination, JOIN query
│   │   ├── admin.py        # MODIFY: add response_model, pagination, revoke_role 404
│   │   ├── chat.py         # MODIFY: SSE error handling enhancement
│   │   ├── auth.py         # MODIFY: get_me returns 501 when auth disabled
│   │   ├── ingest.py       # MODIFY: add pagination to list_tasks
│   │   └── search.py       # OK as-is (already has response_model)
│   ├── deps.py             # MODIFY: search_service type annotation (Protocol/ABC)
│   └── main.py             # MODIFY: middleware registration change
├── agent/
│   ├── agent.py            # MODIFY: _chunk_text fix, SSE error format, streaming error handling
│   └── tools.py            # MODIFY: add required fields to GET_DOCUMENT_CONTEXT_TOOL
├── common/
│   ├── logging.py          # MODIFY: CostTracker unknown model warning
│   └── cache.py            # MODIFY: cache key hash length
└── retrieval/
    ├── hybrid_search.py    # MODIFY: move log after reranking
    ├── haystack_search.py  # (interface conformance if Protocol/ABC added)
    └── search_protocol.py  # NEW (if Protocol chosen) or update types.py
```

### Pattern 1: Pure ASGI Middleware
**What:** Replace BaseHTTPMiddleware classes with pure ASGI middleware classes
**When to use:** All HTTP middleware in the application
**Current code (BaseHTTPMiddleware):**
```python
# src/pam/api/middleware.py (CURRENT)
class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        cid = request.headers.get("X-Correlation-ID")
        cid = set_correlation_id(cid)
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = cid
        return response
```
**Target code (pure ASGI):**
```python
# Source: https://www.starlette.io/middleware/
from starlette.datastructures import MutableHeaders

class CorrelationIdMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        cid = None
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"x-correlation-id":
                cid = header_value.decode()
                break
        cid = set_correlation_id(cid)

        async def send_with_cid(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.append("X-Correlation-ID", cid)
            await send(message)

        await self.app(scope, receive, send_with_cid)
```
**Key difference:** Pure ASGI does NOT buffer the response body. BaseHTTPMiddleware's `call_next` reads the entire response body into memory before returning, which causes SSE streaming to buffer until the stream completes. Pure ASGI passes `send` through directly, so SSE events flow immediately.

**Registration change in main.py:**
```python
# BaseHTTPMiddleware style (CURRENT):
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Pure ASGI style (TARGET):
# Starlette's app.add_middleware works with any ASGI middleware class
# that takes `app` as first __init__ argument
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(CorrelationIdMiddleware)
# Same API call -- Starlette handles both styles
```

### Pattern 2: Cursor-Based Pagination (Nakama-style)
**What:** Opaque base64 cursor encoding the last item's sort position
**When to use:** All list endpoints (GET /documents, GET /admin/users, GET /ingest/tasks)

**Cursor encode/decode:**
```python
import base64
import json

def encode_cursor(last_id: str, sort_value: str) -> str:
    """Encode pagination position as opaque base64 cursor."""
    payload = json.dumps({"id": last_id, "sv": sort_value}, sort_keys=True)
    return base64.urlsafe_b64encode(payload.encode()).decode()

def decode_cursor(cursor: str) -> dict:
    """Decode opaque cursor back to position data."""
    raw = base64.urlsafe_b64decode(cursor.encode())
    return json.loads(raw)
```

**Response envelope schema:**
```python
from pydantic import BaseModel
from typing import Generic, TypeVar

T = TypeVar("T")

class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    cursor: str  # empty string = no more pages
```

**SQLAlchemy query pattern (keyset pagination):**
```python
# For documents sorted by updated_at DESC:
stmt = select(Document).order_by(Document.updated_at.desc(), Document.id.desc())
if cursor:
    pos = decode_cursor(cursor)
    # Keyset condition: (updated_at, id) < (cursor_sv, cursor_id)
    stmt = stmt.where(
        (Document.updated_at < pos["sv"]) |
        ((Document.updated_at == pos["sv"]) & (Document.id < pos["id"]))
    )
stmt = stmt.limit(page_size + 1)  # fetch one extra to detect next page

rows = (await db.execute(stmt)).all()
has_next = len(rows) > page_size
items = rows[:page_size]
next_cursor = encode_cursor(str(items[-1].id), items[-1].updated_at.isoformat()) if has_next else ""
```

**List endpoints that need pagination:**
1. `GET /documents` -- sort by `updated_at DESC` -- currently returns ALL documents
2. `GET /admin/users` -- sort by `created_at DESC` -- currently has limit but no cursor
3. `GET /ingest/tasks` -- sort by `created_at DESC` -- currently has limit but no cursor

### Pattern 3: SSE Error Events
**What:** Structured error events in SSE stream when LLM API fails mid-stream
**When to use:** In `answer_streaming()` exception handler

**Current behavior:**
```python
except Exception as e:
    logger.exception("streaming_error", error=str(e))
    yield {"type": "error", "message": "An internal error occurred. Please try again."}
```

**Target behavior (per user decision):**
```python
except Exception as e:
    logger.exception("streaming_error", error=str(e))
    # Structured error event with JSON payload
    yield {
        "type": "error",
        "data": {"type": type(e).__name__, "message": str(e)},
        "message": f"An error occurred: {str(e)}"  # human-readable fallback
    }
    # Stream lifecycle: send done event then close (recommendation)
    yield {"type": "done", "metadata": {...}}
```

**Frontend already handles this** -- `useChat.ts` lines 114-128 check for `event.type === "error"` and reads `event.message`.

### Pattern 4: RequestLogging as Pure ASGI (with request timing)
**What:** Pure ASGI middleware that logs request method, path, status code, and latency
**Recommendation for Claude's Discretion:** Add request timing (it's natural and nearly free)

```python
class RequestLoggingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        start = time.perf_counter()
        status_code = 0

        async def send_with_timing(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_with_timing)

        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "http_request",
            method=scope.get("method", ""),
            path=scope.get("path", ""),
            status_code=status_code,
            latency_ms=round(latency_ms, 1),
        )
```

### Anti-Patterns to Avoid
- **Using BaseHTTPMiddleware with streaming responses:** BaseHTTPMiddleware buffers the entire response body through `call_next()`. This causes SSE events to be held until the stream completes, defeating the purpose of streaming.
- **Offset-based pagination for mutable datasets:** Items shift between pages when data is inserted/deleted. Cursor-based pagination is stable under writes.
- **Returning raw dicts from endpoints without response_model:** FastAPI cannot generate OpenAPI schemas, and no output validation occurs. Always specify response_model or return type annotation.
- **Silent fallback in CostTracker:** Currently falls back to sonnet pricing silently. Unknown models should trigger a warning log with the model name.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ASGI header manipulation | Raw bytes header lists | `starlette.datastructures.MutableHeaders` | Handles encoding, duplicates, case-insensitive lookup |
| Base64 URL encoding | Custom encoding | `base64.urlsafe_b64encode/decode` | Handles padding, URL-safe characters |
| Response schema validation | Manual dict construction | Pydantic `response_model` | FastAPI auto-validates and generates OpenAPI |

**Key insight:** The Starlette/FastAPI ecosystem already provides the building blocks. The work is wiring them correctly, not building new infrastructure.

## Common Pitfalls

### Pitfall 1: ASGI Middleware Scope Type Check
**What goes wrong:** Middleware processes WebSocket or lifespan scope types as HTTP
**Why it happens:** ASGI `__call__` receives all scope types, not just HTTP
**How to avoid:** Always check `if scope["type"] != "http": return await self.app(scope, receive, send)` as the first line
**Warning signs:** Errors on app startup (lifespan scope) or WebSocket connections

### Pitfall 2: Cursor Pagination Off-By-One
**What goes wrong:** Fetching `page_size` rows makes it impossible to know if there's a next page
**Why it happens:** You need `page_size + 1` rows to detect whether more data exists
**How to avoid:** Always fetch `limit + 1`, use the extra row only to set `has_next`, then slice to `limit`
**Warning signs:** Last page always shows a "next" cursor that returns empty results

### Pitfall 3: Cursor Sort Field Uniqueness
**What goes wrong:** Two items with identical `updated_at` timestamps cause the cursor to skip or repeat items
**Why it happens:** The keyset condition `updated_at < cursor_value` skips items with the same timestamp
**How to avoid:** Always include a unique tiebreaker (the primary key UUID) in the sort and cursor
**Warning signs:** Missing items when documents are updated in the same second

### Pitfall 4: SSE Event Format Mismatch
**What goes wrong:** Frontend cannot parse new error event structure
**Why it happens:** Backend changes event shape without matching frontend expectations
**How to avoid:** Keep backward-compatible: `event.message` for human-readable text (already used), add `event.data` for structured info
**Warning signs:** Frontend shows "Unknown streaming error" instead of actual error message

### Pitfall 5: Pure ASGI Middleware Ordering
**What goes wrong:** Correlation ID is not set when RequestLogging runs
**Why it happens:** `app.add_middleware()` in Starlette wraps in reverse order -- last added is outermost
**How to avoid:** Add CorrelationIdMiddleware AFTER RequestLoggingMiddleware (so it wraps outermost)
**Warning signs:** Request logs missing correlation_id field. Current ordering is already correct.

### Pitfall 6: _chunk_text Leading Space in Streaming
**What goes wrong:** Non-first chunks start with `" word word word"` (leading space)
**Why it happens:** `_chunk_text` adds `" " + chunk` for `i > 0` to separate words when concatenating
**How to avoid:** Append the space to the END of the previous chunk instead, or use a different splitting strategy
**Warning signs:** Individual SSE token events start with a space character, which may affect incremental rendering

## Code Examples

### Example 1: Endpoints Missing response_model (current state)

| Endpoint | File | Current | Needed response_model |
|----------|------|---------|----------------------|
| `GET /documents` | documents.py:19 | No response_model, returns list[dict] | `PaginatedResponse[DocumentResponse]` |
| `GET /segments/{id}` | documents.py:29 | No response_model, returns dict | New `SegmentResponse` Pydantic model |
| `GET /stats` | documents.py:59 | No response_model, returns dict | New `StatsResponse` Pydantic model |
| `POST /admin/roles` | admin.py:66 | No response_model, returns dict | New `RoleAssignedResponse` model |
| `PATCH /admin/users/{id}/deactivate` | admin.py:125 | No response_model, returns dict | New `MessageResponse` model |
| `DELETE /admin/roles/{uid}/{pid}` | admin.py:108 | 204 No Content | No response_model needed (correct) |
| `POST /chat/stream` | chat.py:77 | SSE stream | No response_model needed (SSE) |

### Example 2: GET_DOCUMENT_CONTEXT_TOOL Missing Required Fields
```python
# CURRENT (tools.py) -- no required fields
GET_DOCUMENT_CONTEXT_TOOL = {
    "name": "get_document_context",
    "input_schema": {
        "type": "object",
        "properties": {
            "document_title": {"type": "string", ...},
            "source_id": {"type": "string", ...},
        },
        # No "required" key! Claude may call with empty input.
    },
}

# FIX: Add required (at least one of the two)
# Since the tool requires at least one, the cleanest approach is to
# NOT add required (both are optional) but add a clear description that
# at least one must be provided. The handler already validates this.
# Alternatively, could use oneOf but Anthropic tool schema doesn't support it.
# The handler at agent.py:424 already checks: if not title and not source_id: return error
# So the fix is actually fine as-is for this tool.
#
# But GET_CHANGE_HISTORY_TOOL and SEARCH_ENTITIES_TOOL also lack required where they should have it:
# - SEARCH_ENTITIES_TOOL already has "required": ["search_term"] -- correct
# - QUERY_DATABASE_TOOL has "required": ["sql"] -- but sql is optional when list_tables=true
#   This is a schema bug: the handler checks for either sql or list_tables
```

### Example 3: CostTracker Unknown Model Warning
```python
# CURRENT (logging.py:100-108)
@staticmethod
def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = {
        "claude-sonnet-4-5-20250514": {"input": 3.0, "output": 15.0},
        "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    }
    # Default to sonnet pricing -- SILENTLY falls back
    rates = pricing.get(model, pricing["claude-sonnet-4-5-20250514"])
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000

# FIX: Add warning log when model is unknown
@staticmethod
def _estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    pricing = {
        "claude-sonnet-4-5-20250514": {"input": 3.0, "output": 15.0},
        "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    }
    rates = pricing.get(model)
    if rates is None:
        log = structlog.get_logger()
        log.warning("unknown_model_cost", message=f"Unknown model '{model}': using default cost estimate")
        rates = pricing["claude-sonnet-4-5-20250514"]
    return (input_tokens * rates["input"] + output_tokens * rates["output"]) / 1_000_000
```

### Example 4: Cache Key Hash Length Fix
```python
# CURRENT (cache.py:44) -- truncated to 16 hex chars (64 bits)
digest = hashlib.sha256(raw.encode()).hexdigest()[:16]

# FIX: Use full SHA-256 (64 hex chars / 256 bits)
digest = hashlib.sha256(raw.encode()).hexdigest()
return f"search:{digest}"
```

### Example 5: Hybrid Search Log After Reranking
```python
# CURRENT (hybrid_search.py:151-155) -- log BEFORE reranking
logger.info("hybrid_search", query_length=len(query), results=len(results), top_k=top_k)

# Rerank results if reranker is configured
if self.reranker and results:
    results = await self.reranker.rerank(query, results, top_k=top_k)

# FIX: Move log AFTER reranking
if self.reranker and results:
    results = await self.reranker.rerank(query, results, top_k=top_k)

logger.info("hybrid_search", query_length=len(query), results=len(results), top_k=top_k)
```

### Example 6: get_segment JOIN Query
```python
# CURRENT (documents.py:36-43) -- 2 sequential queries
result = await db.execute(select(Segment).where(Segment.id == segment_id))
segment = result.scalar_one_or_none()
# ... then ...
doc_result = await db.execute(select(Document).where(Document.id == segment.document_id))
doc = doc_result.scalar_one_or_none()

# FIX: Single JOIN query
from sqlalchemy.orm import selectinload
result = await db.execute(
    select(Segment)
    .options(selectinload(Segment.document))
    .where(Segment.id == segment_id)
)
segment = result.scalar_one_or_none()
# Then access segment.document directly
```

### Example 7: get_me 501 When Auth Disabled
```python
# CURRENT (auth.py:109-110) -- returns 404
if not settings.auth_required:
    raise HTTPException(status_code=404, detail="Auth not enabled")

# FIX: Return 501 Not Implemented
if not settings.auth_required:
    raise HTTPException(status_code=501, detail="Authentication is not enabled")
```

### Example 8: revoke_role 404 When Role Doesn't Exist
```python
# CURRENT (admin.py:108-122) -- always returns 204 even if no role existed
@router.delete("/admin/roles/{user_id}/{project_id}", status_code=204)
async def revoke_role(user_id, project_id, db, _admin):
    await db.execute(delete(UserProjectRole).where(...))
    await db.commit()

# FIX: Check if row was actually deleted
result = await db.execute(delete(UserProjectRole).where(...))
await db.commit()
if result.rowcount == 0:
    raise HTTPException(status_code=404, detail="Role assignment not found")
```

## Discretion Recommendations

### Stream Lifecycle After Error
**Recommendation:** Send the error event, then immediately close (do NOT send a done event after error).
**Rationale:** The frontend `useChat.ts` handles `error` events by setting error state and updating the message. It does NOT depend on a subsequent `done` event to clean up -- the `finally` block handles cleanup. Sending `done` after `error` would be confusing and might reset the error state.

### ASGI Middleware Scope
**Recommendation:** Combine CorrelationId and RequestLogging into the same scope as current, BUT add request timing to the pure ASGI RequestLoggingMiddleware.
**Rationale:** Request timing is already implemented in the current BaseHTTPMiddleware version (line 28-30). Removing it in the pure ASGI version would be a regression. Adding it costs nothing.

### Error Response Envelope Format
**Recommendation:** Keep FastAPI's default error format `{"detail": "message"}` for HTTPExceptions.
**Rationale:** The frontend `client.ts` line 179 reads `res.text()` on error and wraps it in a thrown Error. It does not parse JSON error bodies. Changing the envelope format would require frontend changes, which is out of scope for this phase. The `{"detail": ...}` format is what FastAPI generates by default.

### 404 Detail Level for revoke_role
**Recommendation:** `"Role assignment not found"` -- concise, describes what's missing.
**Rationale:** No need to echo back user_id/project_id (they're already in the URL path). Keep it consistent with other 404s in the codebase ("User not found", "Segment not found").

### get_stats Partial Failure Handling
**Recommendation:** Current behavior is already correct -- entity query failure is caught, logged with warning + exc_info, and returns empty dict. No change needed.
**Rationale:** The existing `try/except` block at documents.py:74-81 already logs `entity_count_query_failed` with `exc_info=True`. The API-07 requirement says "logs warning on entity query failure instead of silently swallowing" -- this is already implemented. Verify with a test and move on.

### Protocol vs ABC for Search Service Interface
**Recommendation:** Use `typing.Protocol` (structural subtyping).
**Rationale:** The project already uses ABC for `BaseReranker` (retrieval/rerankers/base.py), but the search services (`HybridSearchService` and `HaystackSearchService`) are NOT subclassing anything today. They just happen to share the same `search()` and `search_from_query()` method signatures. A Protocol captures this "same shape" pattern without requiring the classes to inherit from a base. This also avoids modifying the two existing service classes to add a base class import. The deps.py type hint `get_search_service() -> HybridSearchService` is wrong when Haystack is active -- a Protocol fixes this cleanly.

### Cache Key Hash Length
**Recommendation:** Use full SHA-256 (64 hex chars).
**Rationale:** The current 16-hex-char truncation (64 bits) creates a birthday paradox collision risk at ~2^32 (~4 billion) unique queries, which is practically safe but unnecessarily weak. Full SHA-256 costs negligible additional Redis key storage (48 extra chars per key, no performance impact). The Redis key becomes `search:<64 hex chars>` instead of `search:<16 hex chars>`.

### Chunk Text Whitespace Fix
**Recommendation:** Move the space to the end of the previous chunk instead of the start of the next.
**Rationale:** The current approach: `["Hello world", " is great", " today"]`. The fix: `["Hello world ", "is great ", "today"]`. This way each token event starts with visible text (no leading space artifact). The concatenation result is identical. The last chunk correctly has no trailing space since it's the final one.

Fixed implementation:
```python
@staticmethod
def _chunk_text(text: str, size: int = 4) -> list[str]:
    words = text.split(" ")
    chunks = []
    for i in range(0, len(words), size):
        chunk = " ".join(words[i : i + size])
        if i + size < len(words):
            chunk += " "  # trailing space as word separator
        chunks.append(chunk)
    return chunks
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| BaseHTTPMiddleware | Pure ASGI middleware | Starlette has recommended pure ASGI for years; FastAPI docs now explicitly mention it | Fixes SSE buffering, ~20-30% perf improvement |
| Offset/limit pagination | Cursor-based (keyset) pagination | Industry trend since ~2020 | Stable under concurrent writes, better performance on large datasets |
| Silent fallback for unknown config | Explicit warnings with structured logging | Standard practice | Faster debugging, better observability |

**Deprecated/outdated:**
- `BaseHTTPMiddleware`: Still works but causes response body buffering. Starlette docs recommend pure ASGI for streaming use cases.

## Resolved Questions

1. **QUERY_DATABASE_TOOL schema conflict** — RESOLVED
   - **Finding:** Anthropic's tool-use API enforces `required` strictly. Claude will not call the tool with `list_tables=true` while omitting `sql` — it will either pass an empty `sql=""` or refuse.
   - **Evidence:** The test `test_list_tables` calls `_query_database({"list_tables": True})` directly (bypasses Claude's schema validation). `GET_DOCUMENT_CONTEXT_TOOL` already uses the correct pattern: no `required` field, handler validates manually.
   - **Decision:** Remove `"sql"` from `required` (set `"required": []`). The handler already validates that at least one of `sql` or `list_tables` is provided. Aligns with `GET_DOCUMENT_CONTEXT_TOOL` pattern.

2. **Total count query for cursor pagination** — RESOLVED
   - **Finding:** Include exact count on all three endpoints — tables are small and queries are cheap.
   - **Evidence:** `ingestion_tasks` (10-100 rows, has `idx_ingestion_tasks_created_at`, <0.5ms), `users` (10-1K rows, <1ms), `documents` (100-10K rows, 1-3ms). All negligible.
   - **Decision:** Always include `total` in the paginated response. No toggle needed. Run `SELECT COUNT(*)` on every request.

3. **Frontend pagination integration** — RESOLVED
   - **Finding:** Frontend changes are out of scope for Phase 3 per ROADMAP (Phase 4 = Frontend + Dead Code Cleanup). However, changing list endpoints from returning arrays to `{items, total, cursor}` will break `client.ts` and consuming hooks.
   - **Evidence:** `listDocuments()` returns `Document[]`, `useDocuments.ts` maps over array directly, `useIngestionTask.ts` expects `IngestionTask[]`.
   - **Decision:** Add minimal frontend adapter in Phase 3 — update `client.ts` functions to unwrap `response.items` so hooks keep working (~5 lines per endpoint). Avoids shipping knowingly broken frontend between phases.

## Sources

### Primary (HIGH confidence)
- Codebase analysis: All files in `src/pam/api/`, `src/pam/agent/`, `src/pam/common/`, `src/pam/retrieval/` read directly
- [Starlette Middleware Documentation](https://www.starlette.io/middleware/) -- pure ASGI middleware patterns, MutableHeaders usage
- [FastAPI Advanced Middleware](https://fastapi.tiangolo.com/advanced/middleware/) -- middleware registration, ASGI middleware support

### Secondary (MEDIUM confidence)
- [Analysing FastAPI Middleware Performance](https://medium.com/@ssazonov/analysing-fastapi-middleware-performance-8abe47a7ab93) -- 20-30% performance improvement with pure ASGI
- [FastAPI + SQLAlchemy cursor-based pagination](https://www.slingacademy.com/article/fastapi-sqlalchemy-using-cursor-based-pagination/) -- implementation patterns
- [Nakama cursor pagination](https://github.com/heroiclabs/nakama/blob/master/server/core_channel.go) -- base64 cursor encoding reference

### Tertiary (LOW confidence)
- None -- all findings verified against codebase or official docs

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries needed, all patterns verified against codebase
- Architecture: HIGH -- all target files read, modifications are surgical and well-understood
- Pitfalls: HIGH -- pitfalls are specific to the codebase patterns observed (not generic advice)

**Research date:** 2026-02-16
**Valid until:** 2026-03-16 (stable -- no fast-moving dependencies)
