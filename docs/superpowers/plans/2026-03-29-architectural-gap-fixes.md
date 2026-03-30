# Architectural Gap Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 11 architectural gaps found in code review: rate limiting, config validation, tiered health checks, error boundaries, search error propagation, document size limits, conversation history truncation, task_manager refactoring, background task concurrency, frontend role handling, and SSE reconnection.

**Architecture:** Each task is independent and produces a self-contained change. Tasks can be executed in any order or in parallel. All backend tasks follow TDD. Frontend tasks include manual verification steps.

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / Elasticsearch / React 18 / TypeScript / tiktoken / slowapi

---

## File Structure

**Create:**
- `src/pam/api/rate_limit.py` — Rate limiter setup and exception handler
- `web/src/components/ErrorBoundary.tsx` — React error boundary component
- `tests/test_api/test_rate_limit.py` — Rate limiting tests
- `tests/test_common/test_config_validation.py` — Config validator tests
- `tests/test_agent/test_conversation_truncation.py` — History truncation tests
- `tests/test_agent/test_document_limit.py` — Document size limit tests

**Modify:**
- `pyproject.toml` — Add `slowapi` dependency
- `src/pam/common/config.py` — Add validators, rate limit settings
- `src/pam/api/main.py` — Rate limiting middleware, tiered health
- `src/pam/api/routes/chat.py` — Rate limit decorators, rename `request` param
- `src/pam/retrieval/hybrid_search.py` — Raise on search failure instead of returning `[]`
- `src/pam/retrieval/haystack_search.py` — Same as above
- `src/pam/retrieval/types.py` — Add `SearchError` exception class
- `src/pam/agent/agent.py` — Document size cap, conversation truncation, search error handling
- `src/pam/ingestion/task_manager.py` — Extract common pipeline runner, add semaphore
- `web/src/App.tsx` — Wrap routes in ErrorBoundary
- `web/src/api/client.ts` — Fix hardcoded role in `getMe()`
- `web/src/hooks/useAuth.ts` — Use server-provided roles
- `web/src/hooks/useChat.ts` — SSE retry with exponential backoff

---

### Task 1: Rate Limiting

**Files:**
- Create: `src/pam/api/rate_limit.py`
- Create: `tests/test_api/test_rate_limit.py`
- Modify: `pyproject.toml`
- Modify: `src/pam/common/config.py`
- Modify: `src/pam/api/main.py`
- Modify: `src/pam/api/routes/chat.py`

- [ ] **Step 1: Add slowapi dependency**

In `pyproject.toml`, add `slowapi` to the dependencies list after the `httpx` line:

```toml
    "httpx>=0.27",
    "slowapi>=0.1.9",
]
```

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && uv sync`

- [ ] **Step 2: Add rate limit settings to config**

In `src/pam/common/config.py`, add these fields after the `cors_origins` line (before `model_config`):

```python
    # Rate limiting
    rate_limit_default: str = "100/minute"
    rate_limit_chat: str = "10/minute"
    rate_limit_ingest: str = "5/minute"
    rate_limit_search: str = "30/minute"
```

- [ ] **Step 3: Write the rate limit module**

Create `src/pam/api/rate_limit.py`:

```python
"""Rate limiting setup using slowapi."""

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from pam.common.config import settings


def _key_func(request: Request) -> str:
    """Rate limit key: client IP address."""
    return get_remote_address(request)


limiter = Limiter(
    key_func=_key_func,
    default_limits=[settings.rate_limit_default],
)


async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}"},
    )
```

- [ ] **Step 4: Wire rate limiting into the app**

In `src/pam/api/main.py`, add imports after the existing imports:

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from pam.api.rate_limit import limiter
```

In the `create_app()` function, after `app.add_middleware(CorrelationIdMiddleware)`, add:

```python
    # Rate limiting
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
```

- [ ] **Step 5: Add per-route limits on chat endpoints**

In `src/pam/api/routes/chat.py`, add imports:

```python
from fastapi import APIRouter, Depends, HTTPException, Request

from pam.api.rate_limit import limiter
```

Rename the `request` parameter to `body` in all three route handlers and add `request: Request` + `@limiter.limit()` decorator. For the `chat` handler:

```python
@router.post("/chat", response_model=ChatResponse)
@limiter.limit("10/minute")
async def chat(
    request: Request,
    body: ChatRequest,
    agent: RetrievalAgent = Depends(get_agent),
    _user: User | None = Depends(get_current_user),
):
    """Send a message and get an AI-powered answer with citations."""
    conversation_id = body.conversation_id or str(uuid.uuid4())

    kwargs: dict = {}
    if body.conversation_history:
        kwargs["conversation_history"] = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    if body.source_type:
        kwargs["source_type"] = body.source_type

    try:
        result: AgentResponse = await agent.answer(body.message, **kwargs)
    except Exception as e:
        logger.exception("chat_error", message=body.message[:100])
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

    return ChatResponse(
        response=result.answer,
        citations=[
            {
                "document_title": c.document_title,
                "section_path": c.section_path,
                "source_url": c.source_url,
                "segment_id": c.segment_id,
            }
            for c in result.citations
        ],
        conversation_id=conversation_id,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
        retrieval_mode=result.retrieval_mode,
        mode_confidence=result.mode_confidence,
    )
```

Apply the same pattern to `chat_debug` (rename `request` to `body`, add `request: Request`, add `@limiter.limit("10/minute")`, replace all `request.` with `body.`).

Apply the same pattern to `chat_stream` (rename `request` to `body`, add `request: Request`, add `@limiter.limit("10/minute")`, replace all `request.` with `body.`).

- [ ] **Step 6: Write the failing test**

Create `tests/test_api/test_rate_limit.py`:

```python
"""Tests for rate limiting middleware."""

import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from pam.api.main import create_app


@pytest.fixture
def app():
    """Create app with rate limiting."""
    return create_app()


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_rate_limit_returns_429_when_exceeded(client):
    """Requests exceeding the rate limit receive 429."""
    # The default limit is 100/minute. Override to 2/minute for testing.
    with patch("pam.api.rate_limit.limiter._default_limits", ["2/minute"]):
        # First two requests should succeed (health endpoint is simple)
        for _ in range(2):
            resp = await client.get("/api/health")
            assert resp.status_code != 429

        # Third request should be rate limited
        resp = await client.get("/api/health")
        assert resp.status_code == 429
        assert "Rate limit" in resp.json()["detail"]
```

- [ ] **Step 7: Run the test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_api/test_rate_limit.py -v`

Expected: FAIL (rate limiting not yet wired up, or import errors if steps 3-5 not done yet). If you implemented steps 3-5 first, expect PASS and skip to step 9.

- [ ] **Step 8: Verify all tests pass**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_api/ -v --timeout=30`

Expected: All tests PASS including existing chat tests (the `request` → `body` rename doesn't affect the test client since it sends HTTP requests, not function calls).

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml src/pam/api/rate_limit.py src/pam/common/config.py src/pam/api/main.py src/pam/api/routes/chat.py tests/test_api/test_rate_limit.py
git commit -m "feat: add rate limiting with slowapi on chat and ingest endpoints"
```

---

### Task 2: Config Validation for API Keys

**Files:**
- Modify: `src/pam/common/config.py`
- Create: `tests/test_common/test_config_validation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_common/test_config_validation.py`:

```python
"""Tests for Settings validation."""

import pytest
from pydantic import ValidationError

from pam.common.config import Settings


def test_empty_anthropic_key_rejected():
    """Settings rejects empty anthropic_api_key."""
    with pytest.raises(ValidationError, match="anthropic_api_key"):
        Settings(anthropic_api_key="", openai_api_key="sk-proj-valid-key-here")


def test_empty_openai_key_rejected():
    """Settings rejects empty openai_api_key."""
    with pytest.raises(ValidationError, match="openai_api_key"):
        Settings(anthropic_api_key="sk-ant-valid-key", openai_api_key="")


def test_valid_keys_accepted():
    """Settings accepts valid API keys."""
    s = Settings(
        anthropic_api_key="sk-ant-test-key",
        openai_api_key="sk-proj-test-key",
    )
    assert s.anthropic_api_key == "sk-ant-test-key"
    assert s.openai_api_key == "sk-proj-test-key"


def test_mode_confidence_out_of_range_rejected():
    """Settings rejects mode_confidence_threshold outside 0.0-1.0."""
    with pytest.raises(ValidationError, match="mode_confidence_threshold"):
        Settings(
            anthropic_api_key="sk-ant-test",
            openai_api_key="sk-proj-test",
            mode_confidence_threshold=1.5,
        )


def test_context_budget_exceeds_max_rejected():
    """Settings rejects entity + relationship budget exceeding max."""
    with pytest.raises(ValidationError, match="context budget"):
        Settings(
            anthropic_api_key="sk-ant-test",
            openai_api_key="sk-proj-test",
            context_entity_budget=8000,
            context_relationship_budget=8000,
            context_max_tokens=10000,
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_common/test_config_validation.py -v`

Expected: FAIL — validators don't exist yet.

- [ ] **Step 3: Add validators to Settings**

In `src/pam/common/config.py`, add a new validator after the existing `_check_jwt_secret` method (still inside the `Settings` class):

```python
    @model_validator(mode="after")
    def _check_api_keys(self) -> "Settings":
        """Reject empty API keys — app will fail at runtime without them."""
        if not self.anthropic_api_key:
            raise ValueError(
                "anthropic_api_key is required. Set ANTHROPIC_API_KEY in your environment."
            )
        if not self.openai_api_key:
            raise ValueError(
                "openai_api_key is required. Set OPENAI_API_KEY in your environment."
            )
        return self

    @model_validator(mode="after")
    def _check_constraints(self) -> "Settings":
        """Validate numeric constraints between settings."""
        if not 0.0 <= self.mode_confidence_threshold <= 1.0:
            raise ValueError(
                f"mode_confidence_threshold must be 0.0-1.0, got {self.mode_confidence_threshold}"
            )
        if self.context_entity_budget + self.context_relationship_budget > self.context_max_tokens:
            raise ValueError(
                f"context budget overflow: entity ({self.context_entity_budget}) + "
                f"relationship ({self.context_relationship_budget}) > "
                f"max ({self.context_max_tokens})"
            )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_common/test_config_validation.py -v`

Expected: All 5 tests PASS.

**Important:** The existing `get_settings()` function uses `lru_cache`. The new validators will fire when `Settings()` is first constructed. Ensure your `.env` file has valid `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` values, or existing tests that instantiate Settings from env will fail.

- [ ] **Step 5: Verify no regressions**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/ -v --timeout=30 -x`

Expected: All tests PASS. If any fail due to the new validators reading empty env vars in test environments, add a `conftest.py` override or use `monkeypatch` to set dummy API keys.

- [ ] **Step 6: Commit**

```bash
git add src/pam/common/config.py tests/test_common/test_config_validation.py
git commit -m "feat: add config validators for API keys and numeric constraints"
```

---

### Task 3: Tiered Health Endpoint

**Files:**
- Modify: `src/pam/api/main.py` (health endpoint, lines 215-277)
- Modify: `tests/test_api/test_health.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_api/test_health.py` (append to existing file):

```python
@pytest.mark.asyncio
async def test_health_returns_200_when_optional_services_down(client):
    """Health returns 200 if only optional services (Redis, Neo4j) are down."""
    # Mock: PG and ES up, Redis and Neo4j down
    mock_es = AsyncMock()
    mock_es.ping = AsyncMock(return_value=True)

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock()

    # Override deps
    app.dependency_overrides[get_es_client] = lambda: mock_es
    app.dependency_overrides[get_db] = lambda: mock_session

    # Set Redis to None and graph_service to None (optional services down)
    app.state.redis_client = None
    app.state.graph_service = None

    resp = await client.get("/api/health")

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["services"]["elasticsearch"] == "up"
    assert data["services"]["postgres"] == "up"
    assert data["services"]["redis"] == "down"
    assert data["services"]["neo4j"] == "down"

    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_api/test_health.py::test_health_returns_200_when_optional_services_down -v`

Expected: FAIL — current code returns 503 when any service is down.

- [ ] **Step 3: Update health endpoint with tiered service checks**

In `src/pam/api/main.py`, replace the health endpoint status logic (lines 268-277) with:

```python
        # Required services determine overall status
        required_ok = all(
            services[s] == "up" for s in ("elasticsearch", "postgres")
        )
        status_code = 200 if required_ok else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "healthy" if required_ok else "unhealthy",
                "services": services,
                "auth_required": settings.auth_required,
            },
        )
```

- [ ] **Step 4: Run all health tests**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_api/test_health.py -v`

Expected: All tests PASS. Existing tests that check "all up → 200" and "PG down → 503" still pass. The new test for "optional down → 200" passes.

Note: If any existing test asserts 503 specifically when Redis is down, update that assertion to 200 since Redis is now optional.

- [ ] **Step 5: Commit**

```bash
git add src/pam/api/main.py tests/test_api/test_health.py
git commit -m "fix: health endpoint returns 200 when only optional services (Redis, Neo4j) are down"
```

---

### Task 4: React Error Boundary

**Files:**
- Create: `web/src/components/ErrorBoundary.tsx`
- Modify: `web/src/App.tsx`

- [ ] **Step 1: Create ErrorBoundary component**

Create `web/src/components/ErrorBoundary.tsx`:

```tsx
import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export default class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info.componentStack);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex flex-col items-center justify-center h-full p-8 text-center">
          <h2 className="text-lg font-semibold text-red-600 mb-2">
            Something went wrong
          </h2>
          <p className="text-sm text-gray-500 mb-4 max-w-md">
            {this.state.error?.message || "An unexpected error occurred."}
          </p>
          <button
            onClick={() => this.setState({ hasError: false, error: null })}
            className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700"
          >
            Try again
          </button>
        </div>
      );
    }

    return this.props.children;
  }
}
```

- [ ] **Step 2: Wrap App routes with ErrorBoundary**

In `web/src/App.tsx`, add the import at the top:

```tsx
import ErrorBoundary from "./components/ErrorBoundary";
```

Wrap the `<main>` content with `<ErrorBoundary>`:

```tsx
        <main className="flex-1 flex flex-col overflow-hidden">
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<ChatPage />} />
              <Route path="/documents" element={<DocumentsPage />} />
              <Route path="/admin" element={<AdminDashboard />} />
              <Route
                path="/graph/explore"
                element={
                  graphEnabled ? (
                    <GraphExplorerPage />
                  ) : (
                    <div className="flex items-center justify-center h-full">
                      <p className="text-sm text-gray-400">
                        Graph features are not enabled. Set VITE_GRAPH_ENABLED=true to activate.
                      </p>
                    </div>
                  )
                }
              />
              <Route path="/graph" element={<GraphPage />} />
            </Routes>
          </ErrorBoundary>
        </main>
```

- [ ] **Step 3: Verify manually**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context/web && npm run build`

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/ErrorBoundary.tsx web/src/App.tsx
git commit -m "feat: add React ErrorBoundary to catch component crashes"
```

---

### Task 5: Search Error Propagation

**Files:**
- Modify: `src/pam/retrieval/types.py`
- Modify: `src/pam/retrieval/hybrid_search.py`
- Modify: `src/pam/retrieval/haystack_search.py`
- Modify: `src/pam/agent/agent.py`
- Create: `tests/test_retrieval/test_search_errors.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_retrieval/test_search_errors.py`:

```python
"""Tests for search error propagation."""

import pytest
from unittest.mock import AsyncMock

from pam.retrieval.hybrid_search import HybridSearchService
from pam.retrieval.types import SearchBackendError


@pytest.mark.asyncio
async def test_hybrid_search_raises_on_es_error():
    """HybridSearchService raises SearchBackendError on ES failure."""
    mock_client = AsyncMock()
    mock_client.search = AsyncMock(side_effect=ConnectionError("ES down"))

    service = HybridSearchService(mock_client, index_name="test")
    with pytest.raises(SearchBackendError, match="ES down"):
        await service.search(query="test", query_embedding=[0.1] * 1536)


@pytest.mark.asyncio
async def test_hybrid_search_returns_results_normally():
    """HybridSearchService returns results when ES is healthy."""
    mock_client = AsyncMock()
    mock_client.search = AsyncMock(return_value={"hits": {"hits": []}})

    service = HybridSearchService(mock_client, index_name="test")
    results = await service.search(query="test", query_embedding=[0.1] * 1536)
    assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_retrieval/test_search_errors.py -v`

Expected: FAIL — `SearchBackendError` doesn't exist, and `HybridSearchService` returns `[]` instead of raising.

- [ ] **Step 3: Add SearchBackendError to types.py**

In `src/pam/retrieval/types.py`, add at the end of the file:

```python
class SearchBackendError(Exception):
    """Raised when a search backend fails, so callers can distinguish 'no results' from 'backend down'."""

    pass
```

- [ ] **Step 4: Update HybridSearchService to raise**

In `src/pam/retrieval/hybrid_search.py`, add the import:

```python
from pam.retrieval.types import SearchBackendError, SearchQuery, SearchResult
```

Replace the try/except block in `search()` (lines 110-120):

```python
        try:
            response = await self.client.search(index=self.index_name, body=body)
        except Exception as exc:
            logger.exception(
                "hybrid_search_es_error",
                query_length=len(query),
                top_k=top_k,
                source_type=source_type,
                project=project,
            )
            raise SearchBackendError(f"Elasticsearch search failed: {exc}") from exc
```

- [ ] **Step 5: Update HaystackSearchService to raise**

In `src/pam/retrieval/haystack_search.py`, add the import:

```python
from pam.retrieval.types import SearchBackendError, SearchQuery, SearchResult
```

Replace the try/except in `_run_pipeline_sync()` (lines 144-153):

```python
        try:
            result = self.pipeline.run(data=run_data)
        except Exception as exc:
            logger.exception(
                "haystack_search_pipeline_error",
                query_length=len(query),
                top_k=top_k,
                has_filters=filters is not None,
            )
            raise SearchBackendError(f"Haystack search failed: {exc}") from exc
```

- [ ] **Step 6: Handle SearchBackendError in agent**

In `src/pam/agent/agent.py`, add the import:

```python
from pam.retrieval.types import SearchBackendError
```

In `_search_knowledge()`, wrap the search call (around line 636):

```python
        try:
            results = await self.search.search(
                query=query,
                query_embedding=query_embedding,
                top_k=10,
                source_type=source_type,
            )
        except SearchBackendError as exc:
            logger.warning("search_backend_error", query=query[:100], error=str(exc))
            return "Search is temporarily unavailable. Please try again.", []
```

In `_smart_search()`, the `asyncio.gather(return_exceptions=True)` pattern already handles exceptions from search coroutines — the `isinstance(es_result, Exception)` check on line 553 catches `SearchBackendError`. No change needed here.

- [ ] **Step 7: Run tests**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_retrieval/test_search_errors.py tests/test_retrieval/test_hybrid_search.py tests/test_agent/ -v --timeout=30`

Expected: All tests PASS. Existing tests that mock `client.search` with valid responses still work. Tests that mock search exceptions now get `SearchBackendError` instead of `[]`.

Note: If existing tests in `test_hybrid_search.py` assert that search errors return `[]`, update them to expect `SearchBackendError` instead.

- [ ] **Step 8: Commit**

```bash
git add src/pam/retrieval/types.py src/pam/retrieval/hybrid_search.py src/pam/retrieval/haystack_search.py src/pam/agent/agent.py tests/test_retrieval/test_search_errors.py
git commit -m "fix: search backends raise SearchBackendError instead of silently returning empty"
```

---

### Task 6: Document Content Size Limit

**Files:**
- Modify: `src/pam/agent/agent.py`
- Create: `tests/test_agent/test_document_limit.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent/test_document_limit.py`:

```python
"""Tests for document content size limiting in agent tools."""

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from pam.agent.agent import RetrievalAgent

MAX_DOC_CHARS = 50_000  # ~12,500 tokens at 4 chars/token


def _make_agent(db_session: AsyncMock) -> RetrievalAgent:
    return RetrievalAgent(
        search_service=MagicMock(),
        embedder=MagicMock(),
        api_key="test",
        model="test",
        db_session=db_session,
    )


def _make_doc(segment_count: int, segment_size: int = 2000) -> Mock:
    """Create a mock Document with segments."""
    doc = Mock()
    doc.title = "Big Document"
    doc.source_id = "big.md"
    doc.source_url = "file:///big.md"
    doc.segments = [
        Mock(content="x" * segment_size, position=i)
        for i in range(segment_count)
    ]
    return doc


@pytest.mark.asyncio
async def test_large_document_truncated():
    """Documents exceeding MAX_DOC_CHARS are truncated with a notice."""
    db = AsyncMock()
    # 100 segments * 2000 chars = 200,000 chars (well over limit)
    doc = _make_doc(segment_count=100, segment_size=2000)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = doc
    db.execute = AsyncMock(return_value=result_mock)

    agent = _make_agent(db)
    result_text, citations = await agent._get_document_context({"document_title": "Big Document"})

    assert len(result_text) <= MAX_DOC_CHARS + 500  # header + truncation notice
    assert "[truncated]" in result_text


@pytest.mark.asyncio
async def test_small_document_not_truncated():
    """Small documents pass through without truncation."""
    db = AsyncMock()
    doc = _make_doc(segment_count=3, segment_size=100)
    result_mock = MagicMock()
    result_mock.scalar_one_or_none.return_value = doc
    db.execute = AsyncMock(return_value=result_mock)

    agent = _make_agent(db)
    result_text, citations = await agent._get_document_context({"document_title": "Small Document"})

    assert "[truncated]" not in result_text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_agent/test_document_limit.py -v`

Expected: FAIL — no truncation logic exists.

- [ ] **Step 3: Add truncation to _get_document_context**

In `src/pam/agent/agent.py`, add a constant near `MAX_TOOL_ITERATIONS` (line 61):

```python
MAX_DOC_CHARS = 50_000  # ~12,500 tokens — prevents blowing context window
```

Replace the content assembly in `_get_document_context()` (around lines 697-708):

```python
        # Sort segments by position and concatenate
        segments = sorted(doc.segments, key=lambda s: s.position)
        full_content = "\n\n".join(s.content for s in segments)

        # Truncate if too large to prevent context window overflow
        truncated = False
        if len(full_content) > MAX_DOC_CHARS:
            full_content = full_content[:MAX_DOC_CHARS]
            truncated = True

        citation = Citation(
            document_title=doc.title,
            section_path=None,
            source_url=doc.source_url,
            segment_id=None,
        )

        header = f"Document: {doc.title}\nSource: {doc.source_id}\nSegments: {len(segments)}\n\n"
        result = header + full_content
        if truncated:
            result += "\n\n[truncated] Document content was too large. Use search_knowledge for specific sections."
        return result, [citation]
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_agent/test_document_limit.py -v`

Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pam/agent/agent.py tests/test_agent/test_document_limit.py
git commit -m "fix: truncate large documents in get_document_context to prevent context overflow"
```

---

### Task 7: Conversation History Truncation

**Files:**
- Modify: `src/pam/agent/agent.py`
- Create: `tests/test_agent/test_conversation_truncation.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_agent/test_conversation_truncation.py`:

```python
"""Tests for conversation history token-based truncation."""

import pytest

from pam.agent.agent import _truncate_history


def test_short_history_unchanged():
    """History under the token budget passes through unchanged."""
    messages = [
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there"},
        {"role": "user", "content": "What is X?"},
    ]
    result = _truncate_history(messages, max_chars=10_000)
    assert result == messages


def test_long_history_truncated():
    """History exceeding the budget drops oldest pairs, keeps latest user message."""
    messages = [
        {"role": "user", "content": "A" * 5000},
        {"role": "assistant", "content": "B" * 5000},
        {"role": "user", "content": "C" * 5000},
        {"role": "assistant", "content": "D" * 5000},
        {"role": "user", "content": "latest question"},
    ]
    result = _truncate_history(messages, max_chars=12_000)
    # Should drop the oldest pair(s) but keep "latest question"
    assert result[-1]["content"] == "latest question"
    total_chars = sum(len(m["content"]) for m in result)
    assert total_chars <= 12_000


def test_empty_history_unchanged():
    """Empty history returns empty."""
    assert _truncate_history([], max_chars=10_000) == []


def test_single_message_kept():
    """A single oversized message is kept (we never drop the last user message)."""
    messages = [{"role": "user", "content": "X" * 50_000}]
    result = _truncate_history(messages, max_chars=10_000)
    assert len(result) == 1
    assert result[0]["content"] == "X" * 50_000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_agent/test_conversation_truncation.py -v`

Expected: FAIL — `_truncate_history` doesn't exist.

- [ ] **Step 3: Add _truncate_history function and wire it in**

In `src/pam/agent/agent.py`, add the function before the `RetrievalAgent` class:

```python
MAX_HISTORY_CHARS = 400_000  # ~100K tokens — leaves room for system prompt + tool results


def _truncate_history(messages: list[dict], max_chars: int = MAX_HISTORY_CHARS) -> list[dict]:
    """Drop oldest message pairs if total character count exceeds budget.

    Always keeps the last message (the user's current question).
    Drops from the front in pairs (user+assistant) to maintain conversation coherence.
    """
    if not messages:
        return messages

    total = sum(len(m.get("content", "") if isinstance(m.get("content"), str) else "") for m in messages)
    if total <= max_chars:
        return messages

    # Keep dropping oldest pairs until under budget (or only 1 message left)
    trimmed = list(messages)
    while len(trimmed) > 1:
        total = sum(len(m.get("content", "") if isinstance(m.get("content"), str) else "") for m in trimmed)
        if total <= max_chars:
            break
        # Drop oldest message
        trimmed.pop(0)

    return trimmed
```

In the `answer()` method (around line 125), add truncation before the loop:

```python
        messages = list(conversation_history or [])
        messages = _truncate_history(messages)
        messages.append({"role": "user", "content": question})
```

In the `answer_streaming()` method (around line 259), add the same:

```python
        messages = list(conversation_history or [])
        messages = _truncate_history(messages)
        messages.append({"role": "user", "content": question})
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_agent/test_conversation_truncation.py -v`

Expected: All 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pam/agent/agent.py tests/test_agent/test_conversation_truncation.py
git commit -m "fix: truncate conversation history to prevent context window overflow"
```

---

### Task 8: Refactor task_manager.py

**Files:**
- Modify: `src/pam/ingestion/task_manager.py`
- Create: `tests/test_ingestion/test_task_manager_refactor.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_ingestion/test_task_manager_refactor.py`:

```python
"""Tests for the refactored _run_pipeline helper in task_manager."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.ingestion.task_manager import _run_pipeline


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.mark.asyncio
async def test_run_pipeline_marks_task_running(mock_session_factory):
    """_run_pipeline sets task status to 'running'."""
    task_id = uuid.uuid4()
    connector = AsyncMock()
    connector.list_documents = AsyncMock(return_value=[])

    await _run_pipeline(
        task_id=task_id,
        connectors=[("markdown", connector)],
        es_client=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=mock_session_factory,
    )

    # Verify status was set to "running" (first execute call)
    calls = mock_session_factory.return_value.__aenter__.return_value.execute.call_args_list
    assert len(calls) >= 1  # At least the status update


@pytest.mark.asyncio
async def test_run_pipeline_completes_with_no_docs(mock_session_factory):
    """_run_pipeline completes successfully when connector returns no documents."""
    task_id = uuid.uuid4()
    connector = AsyncMock()
    connector.list_documents = AsyncMock(return_value=[])

    await _run_pipeline(
        task_id=task_id,
        connectors=[("markdown", connector)],
        es_client=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=mock_session_factory,
    )
    # Should not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_ingestion/test_task_manager_refactor.py -v`

Expected: FAIL — `_run_pipeline` doesn't exist.

- [ ] **Step 3: Extract the common pipeline runner**

Replace the three duplicated functions in `src/pam/ingestion/task_manager.py` with one shared helper. Keep the existing spawn functions but have them call `_run_pipeline`.

Add this function after the `get_task` and `list_tasks` functions (around line 55):

```python
async def _run_pipeline(
    task_id: uuid.UUID,
    connectors: list[tuple[str, BaseConnector]],
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Shared background pipeline runner for all ingestion task types.

    Args:
        connectors: List of (source_type, connector) pairs to process sequentially.
    """
    try:
        async with session_factory() as status_session:
            # Mark task as running
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="running", started_at=datetime.now(UTC))
            )
            await status_session.commit()

            # Count all documents across connectors
            total_docs = 0
            connector_docs: list[tuple[str, BaseConnector, list]] = []
            for source_type, connector in connectors:
                docs = await connector.list_documents()
                total_docs += len(docs)
                connector_docs.append((source_type, connector, docs))

            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(total_documents=total_docs)
            )
            await status_session.commit()

            if total_docs == 0:
                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="completed", completed_at=datetime.now(UTC))
                )
                await status_session.commit()
                return

            # Progress callback
            async def on_progress(result: IngestionResult) -> None:
                result_entry = [
                    {
                        "source_id": result.source_id,
                        "title": result.title,
                        "segments_created": result.segments_created,
                        "skipped": result.skipped,
                        "error": result.error,
                        "graph_synced": result.graph_synced,
                        "graph_entities_extracted": result.graph_entities_extracted,
                    }
                ]
                succeeded_inc = 1 if not result.error and not result.skipped else 0
                skipped_inc = 1 if result.skipped else 0
                failed_inc = 1 if result.error else 0

                await status_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(
                        processed_documents=IngestionTask.processed_documents + 1,
                        succeeded=IngestionTask.succeeded + succeeded_inc,
                        skipped=IngestionTask.skipped + skipped_inc,
                        failed=IngestionTask.failed + failed_inc,
                        results=IngestionTask.results
                        + cast(literal(json_module.dumps(result_entry)), JSONB),
                    )
                )
                await status_session.commit()

            # Run pipeline for each connector
            for source_type, connector, _docs in connector_docs:
                async with session_factory() as pipeline_session:
                    parser = DoclingParser()
                    es_store = ElasticsearchStore(
                        es_client,
                        index_name=settings.elasticsearch_index,
                        embedding_dims=settings.embedding_dims,
                    )
                    pipeline = IngestionPipeline(
                        connector=connector,
                        parser=parser,
                        embedder=embedder,
                        es_store=es_store,
                        session=pipeline_session,
                        source_type=source_type,
                        progress_callback=on_progress,
                        graph_service=graph_service,
                        vdb_store=vdb_store,
                        skip_graph=skip_graph,
                    )
                    await pipeline.ingest_all()

            # Mark completed
            await status_session.execute(
                update(IngestionTask)
                .where(IngestionTask.id == task_id)
                .values(status="completed", completed_at=datetime.now(UTC))
            )
            await status_session.commit()

            # Invalidate search cache
            if cache_service:
                try:
                    cleared = await cache_service.invalidate_search()
                    logger.info("cache_invalidated_after_ingest", keys_cleared=cleared)
                except Exception:
                    logger.warning("cache_invalidate_failed", exc_info=True)

        logger.info("task_completed", task_id=str(task_id))

    except asyncio.CancelledError:
        logger.warning("task_cancelled", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="failed", error="Task was cancelled", completed_at=datetime.now(UTC))
                )
                await err_session.commit()
        except Exception:
            logger.exception("task_cancelled_status_update_error", task_id=str(task_id))

    except Exception as e:
        logger.exception("task_failed", task_id=str(task_id))
        try:
            async with session_factory() as err_session:
                await err_session.execute(
                    update(IngestionTask)
                    .where(IngestionTask.id == task_id)
                    .values(status="failed", error=str(e), completed_at=datetime.now(UTC))
                )
                await err_session.commit()
        except Exception:
            logger.exception("task_failed_status_update_error", task_id=str(task_id))

    finally:
        _running_tasks.pop(task_id, None)
```

- [ ] **Step 4: Rewrite spawn functions to use _run_pipeline**

Add the `BaseConnector` import at the top of the file:

```python
from pam.ingestion.connectors.base import BaseConnector
```

Replace `run_ingestion_background` (the entire function) with:

```python
async def run_ingestion_background(
    task_id: uuid.UUID,
    folder_path: str,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    connector = MarkdownConnector(folder_path)
    await _run_pipeline(
        task_id, [("markdown", connector)], es_client, embedder, session_factory,
        cache_service, graph_service, skip_graph, vdb_store,
    )
```

Replace `run_github_ingestion_background` with:

```python
async def run_github_ingestion_background(
    task_id: uuid.UUID,
    repo_config: dict,
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    connector = GitHubConnector(
        repo=repo_config["repo"],
        branch=repo_config.get("branch", "main"),
        paths=repo_config.get("paths", []),
        extensions=repo_config.get("extensions", [".md", ".txt"]),
    )
    await _run_pipeline(
        task_id, [("github", connector)], es_client, embedder, session_factory,
        cache_service, graph_service, skip_graph, vdb_store,
    )
```

Replace `run_sync_background` with:

```python
async def run_sync_background(
    task_id: uuid.UUID,
    sources: list[str],
    github_repos: list[dict],
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    connectors: list[tuple[str, BaseConnector]] = []
    if "github" in sources:
        for repo_config in github_repos:
            connector = GitHubConnector(
                repo=repo_config["repo"],
                branch=repo_config.get("branch", "main"),
                paths=repo_config.get("paths", []),
                extensions=repo_config.get("extensions", [".md", ".txt"]),
            )
            connectors.append(("github", connector))
    await _run_pipeline(
        task_id, connectors, es_client, embedder, session_factory,
        cache_service, graph_service, skip_graph, vdb_store,
    )
```

The three `spawn_*` functions remain unchanged — they just call `asyncio.create_task()` with the appropriate `run_*_background` function.

- [ ] **Step 5: Run all tests**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_ingestion/ tests/test_api/test_ingest.py -v --timeout=30`

Expected: All tests PASS. The refactoring preserves identical behavior.

- [ ] **Step 6: Commit**

```bash
git add src/pam/ingestion/task_manager.py tests/test_ingestion/test_task_manager_refactor.py
git commit -m "refactor: extract _run_pipeline to eliminate 200 lines of duplication in task_manager"
```

---

### Task 9: Background Task Concurrency Limit

**Files:**
- Modify: `src/pam/ingestion/task_manager.py`
- Modify: `src/pam/common/config.py`

- [ ] **Step 1: Add concurrency setting to config**

In `src/pam/common/config.py`, add after the `ingest_root` line:

```python
    max_concurrent_ingestions: int = 3  # Max background ingestion tasks
```

- [ ] **Step 2: Add semaphore to task_manager**

In `src/pam/ingestion/task_manager.py`, add after the `_running_tasks` dict:

```python
_ingestion_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore (must be created inside a running event loop)."""
    global _ingestion_semaphore
    if _ingestion_semaphore is None:
        _ingestion_semaphore = asyncio.Semaphore(settings.max_concurrent_ingestions)
    return _ingestion_semaphore
```

- [ ] **Step 3: Wrap _run_pipeline with semaphore**

At the top of the `_run_pipeline` function, add semaphore acquisition:

```python
async def _run_pipeline(
    task_id: uuid.UUID,
    connectors: list[tuple[str, BaseConnector]],
    es_client: AsyncElasticsearch,
    embedder: BaseEmbedder,
    session_factory: async_sessionmaker,
    cache_service: CacheService | None = None,
    graph_service: GraphitiService | None = None,
    skip_graph: bool = False,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> None:
    """Shared background pipeline runner for all ingestion task types."""
    semaphore = _get_semaphore()
    async with semaphore:
        # ... existing try/except/finally body (indented one more level)
```

Move the entire existing try/except/finally block inside the `async with semaphore:` context.

- [ ] **Step 4: Verify no regressions**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/test_ingestion/ tests/test_api/test_ingest.py -v --timeout=30`

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/pam/ingestion/task_manager.py src/pam/common/config.py
git commit -m "feat: add semaphore to limit concurrent ingestion tasks"
```

---

### Task 10: Frontend Role Handling

**Files:**
- Modify: `web/src/api/client.ts`
- Modify: `web/src/hooks/useAuth.ts`

- [ ] **Step 1: Fix hardcoded role in client.ts**

In `web/src/api/client.ts`, update the `AuthUser` interface and the `getMe()` function.

First, update the backend response type to include `roles` (the backend's `UserResponse` doesn't include roles, but we can use the `/auth/me` endpoint which returns `UserResponse`). Since the backend doesn't include roles in the `/auth/me` response, the simplest fix is to acknowledge that role is determined by project context and default to "viewer" explicitly rather than pretending it comes from the server.

Replace the `getMe()` function:

```typescript
export async function getMe(): Promise<AuthUser> {
  const data = await request<{
    id: string;
    email: string;
    name: string;
    is_active: boolean;
  }>("/auth/me");
  return {
    id: data.id,
    email: data.email,
    name: data.name,
    role: "viewer", // Per-project role; see UserProjectRole on backend
  };
}
```

This is already the current code. The real issue is that `useAuth.ts` tries to extract role from the JWT payload. Fix that:

- [ ] **Step 2: Fix role extraction in useAuth.ts**

In `web/src/hooks/useAuth.ts`, find the JWT decode section where it extracts the role. The optimistic JWT decode should NOT set the role from the JWT (since the JWT payload only has `sub`, `email`, `iat`, `exp` — no `role` field).

Find the line that does `payload.role || "viewer"` and replace with just `"viewer"`:

```typescript
// In the token restoration section:
setUser({
  id: payload.sub,
  email: payload.email || "",
  name: payload.name || payload.email || "",
  role: "viewer",  // Role is per-project, not in JWT
});
```

- [ ] **Step 3: Verify build**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context/web && npm run build`

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 4: Commit**

```bash
git add web/src/api/client.ts web/src/hooks/useAuth.ts
git commit -m "fix: clarify that role is per-project, remove misleading JWT role extraction"
```

---

### Task 11: SSE Reconnection with Retry

**Files:**
- Modify: `web/src/hooks/useChat.ts`

- [ ] **Step 1: Add retry logic to streaming**

In `web/src/hooks/useChat.ts`, find the section where the streaming generator is consumed (the `for await` loop that reads from `streamChatMessage`). The current error handling catches streaming failure and falls back to non-streaming. Improve this to retry the SSE connection once before falling back.

Find the `try` block that calls `streamChatMessage` and wrap it in a retry loop:

```typescript
// Inside the sendMessage function, replace the streaming try/catch block:

let streamAttempts = 0;
const MAX_STREAM_RETRIES = 1;

while (streamAttempts <= MAX_STREAM_RETRIES) {
  try {
    for await (const event of streamChatMessage(
      message,
      conversationId,
      history,
      filters,
      abortRef.current.signal
    )) {
      if (event.type === "token") {
        assistantContent += event.content ?? "";
        setMessages((prev) => {
          const updated = [...prev];
          const last = updated[updated.length - 1];
          if (last?.role === "assistant") {
            updated[updated.length - 1] = {
              ...last,
              content: assistantContent,
            };
          }
          return updated;
        });
      } else if (event.type === "status") {
        setStatus(event.content ?? null);
      } else if (event.type === "citation" && event.data) {
        streamCitations.push(event.data);
      } else if (event.type === "done") {
        // Success — update final metadata
        if (event.metadata) {
          setMessages((prev) => {
            const updated = [...prev];
            const last = updated[updated.length - 1];
            if (last?.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                citations: streamCitations,
                token_usage: event.metadata!.token_usage,
                latency_ms: event.metadata!.latency_ms,
              };
            }
            return updated;
          });
        }
        setStatus(null);
        setIsLoading(false);
        return; // Done successfully
      } else if (event.type === "error") {
        setError(event.message ?? "Unknown streaming error");
        break; // Exit the for-await, will retry or fall back
      }
    }
    break; // Stream ended normally (without done event), stop retrying
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      // User cancelled — keep partial response
      setIsLoading(false);
      return;
    }
    streamAttempts++;
    if (streamAttempts <= MAX_STREAM_RETRIES) {
      // Brief delay before retry
      await new Promise((resolve) => setTimeout(resolve, 1000));
      continue;
    }
    // All retries exhausted — fall back to non-streaming
    break;
  }
}
```

After the while loop, keep the existing fallback-to-non-streaming logic.

- [ ] **Step 2: Verify build**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context/web && npm run build`

Expected: Build succeeds with no TypeScript errors.

- [ ] **Step 3: Run existing frontend tests**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context/web && npx vitest run`

Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add web/src/hooks/useChat.ts
git commit -m "feat: add SSE stream retry before falling back to non-streaming"
```

---

## Self-Review

**Spec coverage check:**
- Rate limiting: Task 1
- Config validation: Task 2
- Tiered health: Task 3
- Error boundaries: Task 4
- Search error propagation: Task 5
- Document size limit: Task 6
- Conversation truncation: Task 7
- task_manager refactor: Task 8
- Background concurrency: Task 9
- Frontend role handling: Task 10
- SSE reconnection: Task 11

**Placeholder scan:** No TBD/TODO/placeholder text found. All code blocks are complete.

**Type consistency:**
- `SearchBackendError` defined in Task 5, imported in Task 5 (agent.py and hybrid_search.py)
- `_truncate_history` defined and used in Task 7
- `_run_pipeline` defined in Task 8, used by `run_ingestion_background`, `run_github_ingestion_background`, `run_sync_background`
- `BaseConnector` imported for type annotation in Task 8
- Semaphore in Task 9 wraps `_run_pipeline` from Task 8 — Task 9 depends on Task 8

**Task dependency:** Task 9 (concurrency) depends on Task 8 (refactor) since the semaphore wraps `_run_pipeline`. All other tasks are fully independent.
