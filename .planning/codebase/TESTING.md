# Testing Patterns

**Analysis Date:** 2026-02-15

## Test Framework

**Python Backend:**
- Runner: pytest 8.0+
- Config: `pyproject.toml` → `[tool.pytest.ini_options]`
- Async support: pytest-asyncio 0.23+
- Coverage: pytest-cov 5.0+
- Markers: `@pytest.mark.integration` for tests requiring external services (ES, PG)

**Run Commands:**
```bash
pytest tests/                          # Run all tests
pytest tests/ -v                       # Verbose output
pytest tests/ -k "test_name"           # Filter by test name
pytest tests/ -m "not integration"     # Skip integration tests
pytest tests/ --cov=src/pam            # Run with coverage
pytest tests/ --cov=src/pam --cov-report=html  # HTML coverage report
```

**TypeScript Frontend:**
- Runner: Vitest 4.0+
- Config: `web/vite.config.ts` + `vitest` in `package.json`
- Test utilities: @testing-library/react, @testing-library/dom
- Environment: jsdom

**Run Commands:**
```bash
cd web && npm test                     # Run all tests
npm test -- watch                      # Watch mode
npm test -- --coverage                 # Coverage report
```

## Test File Organization

**Python Location:**
- Pattern: `tests/test_{module}/{test_*.py}`
- Co-located with source modules by feature area
- Structure:
  ```
  tests/
  ├── conftest.py                 # Shared fixtures
  ├── test_retrieval/
  │   ├── __init__.py
  │   ├── test_hybrid_search.py
  │   ├── test_haystack_search.py
  │   ├── test_reranker.py
  │   └── test_types.py
  ├── test_agent/
  │   ├── __init__.py
  │   ├── test_agent.py
  │   ├── test_agent_tools.py
  │   ├── test_duckdb_service.py
  │   └── test_tools.py
  ├── test_ingestion/
  │   ├── conftest.py             # Ingestion-specific fixtures
  │   ├── test_docling_parser.py
  │   ├── test_hybrid_chunker.py
  │   ├── test_elasticsearch_store.py
  │   ├── test_postgres_store.py
  │   ├── test_task_manager.py
  │   ├── test_markdown_connector.py
  │   ├── test_sheets_connector.py
  │   └── test_entity_extractor.py
  └── test_api/
      └── (FastAPI route tests)
  ```

**TypeScript Location:**
- Pattern: `src/**/*.test.ts`, `src/**/*.test.tsx`
- Alongside source files
- Structure:
  ```
  web/src/
  ├── hooks/
  │   ├── useChat.ts
  │   └── useChat.test.ts
  ├── api/
  │   ├── client.ts
  │   └── client.test.ts
  └── components/
      ├── ChatInterface.tsx
      └── (no test; integration tested via hook tests)
  ```

**Naming:**
- Python: `test_{feature}.py`
- TypeScript: `{file}.test.ts` or `{file}.test.tsx`

## Test Structure

**Python Suite Organization:**

Test files use class-based organization with `pytest`:

```python
# tests/test_agent/test_agent.py
"""Tests for RetrievalAgent — tool-use loop with mocked Anthropic + search."""

import uuid
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from pam.agent.agent import RetrievalAgent
from pam.retrieval.types import SearchResult


def _make_text_block(text):
    """Helper: construct a text block response."""
    block = Mock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(name, input_dict, tool_id="tool_1"):
    """Helper: construct a tool use block response."""
    block = Mock()
    block.type = "tool_use"
    block.name = name
    block.input = input_dict
    block.id = tool_id
    return block


def _make_response(content, stop_reason="end_turn", input_tokens=100, output_tokens=50):
    """Helper: construct an API response."""
    resp = Mock()
    resp.content = content
    resp.stop_reason = stop_reason
    resp.usage = Mock(input_tokens=input_tokens, output_tokens=output_tokens)
    return resp


class TestRetrievalAgent:
    """Group of RetrievalAgent tests."""

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_simple_answer(self, mock_anthropic_cls):
        """Agent returns a direct answer without tool use."""
        # Arrange: set up mocks
        mock_client = AsyncMock()
        mock_client.messages.create = AsyncMock(
            return_value=_make_response([_make_text_block("The answer is 42.")])
        )
        mock_anthropic_cls.return_value = mock_client

        mock_search = AsyncMock()
        mock_embedder = AsyncMock()

        # Act: call the code
        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )
        result = await agent.answer("What is the answer?")

        # Assert: verify expectations
        assert result.answer == "The answer is 42."
        assert result.tool_calls == 0
        assert result.token_usage["input_tokens"] == 100

    @patch("pam.agent.agent.AsyncAnthropic")
    async def test_tool_use_loop(self, mock_anthropic_cls):
        """Agent calls search_knowledge tool, then provides answer."""
        # Multi-response mock: first tool_use, then final answer
        mock_client = AsyncMock()
        tool_response = _make_response(
            [_make_tool_use_block("search_knowledge", {"query": "revenue"})],
            stop_reason="tool_use",
        )
        final_response = _make_response(
            [_make_text_block("Revenue was $10M. [Source: Report > Q1](file:///r.md)")],
        )
        mock_client.messages.create = AsyncMock(side_effect=[tool_response, final_response])
        mock_anthropic_cls.return_value = mock_client

        # Search mock returns realistic results
        mock_search = AsyncMock()
        mock_search.search = AsyncMock(
            return_value=[
                SearchResult(
                    segment_id=uuid.uuid4(),
                    content="Revenue was $10M",
                    score=0.9,
                    source_url="file:///r.md",
                    document_title="Report",
                    section_path="Q1",
                )
            ]
        )
        mock_embedder = AsyncMock()
        mock_embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])

        agent = RetrievalAgent(
            search_service=mock_search,
            embedder=mock_embedder,
            api_key="test-key",
        )
        result = await agent.answer("What was the revenue?")

        # Assertions
        assert "10M" in result.answer
        assert result.tool_calls == 1
        assert len(result.citations) == 1
        assert result.citations[0].document_title == "Report"
```

**Patterns:**
- Helper functions prefix with `_` (e.g., `_make_text_block()`) for internal utilities
- Test methods: `test_{behavior}` naming (not `test_{unit}`)
- Comments: Arrange → Act → Assert sections
- Use `async def` for async tests; pytest-asyncio auto-handles
- Classes group related tests; module-level helpers for shared utilities

## Mocking

**Framework:** `unittest.mock` (built-in to Python), `vitest` (TypeScript)

**Python Patterns:**

```python
from unittest.mock import AsyncMock, MagicMock, Mock, patch

# 1. AsyncMock for async functions
mock_search = AsyncMock()
mock_search.search = AsyncMock(return_value=[SearchResult(...)])
result = await mock_search.search(query)

# 2. MagicMock for sync objects with auto-spec
session = AsyncMock(spec=AsyncSession)
session.execute = AsyncMock()
session.add = MagicMock()

# 3. patch decorator to mock module imports
@patch("pam.agent.agent.AsyncAnthropic")
async def test_agent(self, mock_anthropic_cls):
    mock_client = AsyncMock()
    mock_anthropic_cls.return_value = mock_client
    # test code...

# 4. side_effect for multi-call sequences
mock_client.messages.create = AsyncMock(
    side_effect=[first_response, second_response, third_response]
)

# 5. Configure return values
mock_es = AsyncMock()
mock_es.search = AsyncMock(return_value={"hits": {"hits": []}})
```

**TypeScript Patterns:**

```typescript
import { describe, it, expect, vi, beforeEach, type Mock } from "vitest";
import { renderHook, act } from "@testing-library/react";

// 1. Mock module imports
vi.mock("../api/client", () => ({
  sendMessage: vi.fn(),
  streamChatMessage: vi.fn(),
}));

import { sendMessage as apiSendMessage, streamChatMessage } from "../api/client";
const mockSendMessage = apiSendMessage as Mock;
const mockStreamChatMessage = streamChatMessage as Mock;

// 2. Setup/teardown
beforeEach(() => {
  vi.clearAllMocks();
});

// 3. Mock async generators
async function* makeStream(events: Array<{ type: string; ... }>) {
  for (const event of events) {
    yield event;
  }
}

mockStreamChatMessage.mockReturnValue(
  makeStream([
    { type: "token", content: "Hello " },
    { type: "done", metadata: { ... } },
  ])
);

// 4. Mock error scenarios
mockStreamChatMessage.mockImplementation(() => {
  return (async function* () {
    throw new Error("Streaming not supported");
  })();
});

// 5. Mock return values
mockSendMessage.mockResolvedValue({
  message: { role: "assistant", content: "fallback response" },
});
```

**What to Mock:**
- External APIs (OpenAI, Anthropic, Elasticsearch)
- Database sessions and stores
- File system operations
- HTTP clients
- Async generators and streams

**What NOT to Mock:**
- Core business logic (agent, search, chunking algorithms)
- Data models and dataclasses
- Configuration objects
- Utilities and helpers
- Logging (can mock but test actual logging calls)

## Fixtures and Factories

**Python Fixtures (pytest):**

Defined in `tests/conftest.py` and `tests/test_ingestion/conftest.py`:

```python
@pytest.fixture
def mock_db_session():
    """Mock async SQLAlchemy session."""
    session = AsyncMock(spec=AsyncSession)
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.execute = AsyncMock()
    session.add = MagicMock()
    return session


@pytest.fixture
def mock_es_client():
    """Mock async Elasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    client.search = AsyncMock(return_value={"hits": {"hits": []}})
    client.bulk = AsyncMock(return_value={"errors": False, "items": []})
    client.delete_by_query = AsyncMock(return_value={"deleted": 0})
    return client


@pytest.fixture
def sample_knowledge_segment():
    """A sample KnowledgeSegment for testing."""
    return KnowledgeSegment(
        id=uuid.uuid4(),
        content="The quarterly revenue was $10M.",
        content_hash="abc123def456",
        embedding=[0.1] * 1536,
        source_type="markdown",
        source_id="/docs/report.md",
        source_url="file:///docs/report.md",
        section_path="Financial Results > Q1",
        segment_type="text",
        position=0,
        document_title="Q1 Report",
        document_id=uuid.uuid4(),
    )


@pytest.fixture
def sample_raw_document():
    """A sample RawDocument for testing."""
    return RawDocument(
        content=b"# Hello World\n\nThis is a test document.",
        content_type="text/markdown",
        source_id="/tmp/test.md",
        title="test",
        source_url="file:///tmp/test.md",
    )
```

**Fixture Scope:**
- Default: function scope (new fixture per test)
- Session scope: used for expensive setup (module/class imports)
- Parametrize: repeat tests with multiple inputs

**Location:**
- `tests/conftest.py`: shared across all test modules
- `tests/test_ingestion/conftest.py`: specific to ingestion tests

## Coverage

**Requirements:** 80% threshold enforced (see `pyproject.toml` → `[tool.coverage.report]`)

**Configuration (pyproject.toml):**
```toml
[tool.coverage.run]
source = ["src/pam"]

[tool.coverage.report]
fail_under = 80
omit = [
    "*/__init__.py",
]
exclude_lines = [
    "if TYPE_CHECKING:",
    "def __repr__",
    "@abstractmethod",
]
```

**View Coverage:**
```bash
pytest tests/ --cov=src/pam --cov-report=term-missing
pytest tests/ --cov=src/pam --cov-report=html
open htmlcov/index.html
```

## Test Types

**Unit Tests:**
- Scope: single function/method in isolation
- Mock all external dependencies
- Fast execution (< 1s per test)
- Location: `tests/test_{module}/`
- Examples: parser tests, chunker tests, utility tests
  - `tests/test_ingestion/test_docling_parser.py`: mocks DocumentConverter
  - `tests/test_retrieval/test_types.py`: type validation

**Integration Tests:**
- Scope: multiple components working together; real or containerized external services
- May use real PostgreSQL, Elasticsearch (via docker-compose)
- Marked with `@pytest.mark.integration`
- Run separately: `pytest tests/ -m integration`
- Examples:
  - `tests/test_ingestion/test_elasticsearch_store.py`: real ES client
  - `tests/test_ingestion/test_postgres_store.py`: real database session
  - `tests/test_ingestion/test_task_manager.py`: full ingestion pipeline

**E2E Tests:**
- Not implemented in current codebase
- Would test full flow: FastAPI endpoints → agent → search
- Typically in separate `tests/e2e/` directory
- Could use browser automation for frontend testing

**Hook/Component Tests (TypeScript):**
- Scope: React hooks and components
- Use `renderHook()` from @testing-library/react for hook tests
- Mock streaming, API calls, async operations
- Examples: `web/src/hooks/useChat.test.ts`

## Common Patterns

**Async Testing (Python):**

```python
@pytest.mark.asyncio
async def test_async_operation():
    """Test async function."""
    result = await async_function()
    assert result == expected


# Or with parametrize:
@pytest.mark.asyncio
@pytest.mark.parametrize("input,expected", [
    ("query1", [result1]),
    ("query2", [result2]),
])
async def test_search_variants(input, expected):
    service = HybridSearchService(client=mock_client)
    result = await service.search(input, embedding=[...])
    assert result == expected
```

**Async Testing (TypeScript/React):**

```typescript
it("handles async stream with multiple events", async () => {
  mockStreamChatMessage.mockReturnValue(
    makeStream([
      { type: "token", content: "Hello " },
      { type: "token", content: "world" },
      { type: "done", metadata: { token_usage: {}, latency_ms: 50, tool_calls: 0 } },
    ])
  );

  const { result } = renderHook(() => useChat());

  // Use act() to flush updates
  await act(async () => {
    await result.current.sendMessage("test");
  });

  expect(result.current.messages[1].content).toBe("Hello world");
});
```

**Error Testing (Python):**

```python
def test_parse_error_propagates(self):
    """Verify error is raised and logged."""
    mock_converter_cls.return_value.convert.side_effect = RuntimeError("Parse failed")

    parser = DoclingParser()
    with pytest.raises(RuntimeError, match="Parse failed"):
        parser.parse(raw_document)


# For expected errors in pipelines (not raised):
def test_ingest_invalid_document(self):
    """Verify error is caught and returned in result."""
    result = await pipeline.ingest_document(invalid_source_id)
    assert result.error is not None
    assert result.skipped is True
```

**Error Testing (TypeScript):**

```typescript
it("sets error when both streaming and fallback fail", async () => {
  mockStreamChatMessage.mockImplementation(() => {
    return (async function* () {
      throw new Error("Stream failed");
    })();
  });
  mockSendMessage.mockRejectedValue(new Error("Fallback also failed"));

  const { result } = renderHook(() => useChat());

  await act(async () => {
    await result.current.sendMessage("doomed");
  });

  expect(result.current.error).toBe("Fallback also failed");
});
```

**State/Streaming Testing (TypeScript):**

```typescript
it("accumulates citations from streaming events", async () => {
  const citation = {
    title: "Doc A",
    document_id: "doc-1",
    source_url: "http://example.com",
  };
  mockStreamChatMessage.mockReturnValue(
    makeStream([
      { type: "token", content: "Answer" },
      { type: "citation", data: citation },
      { type: "done", metadata: { token_usage: {}, latency_ms: 50, tool_calls: 0 } },
    ])
  );

  const { result } = renderHook(() => useChat());

  await act(async () => {
    await result.current.sendMessage("cite test");
  });

  // Verify citations accumulated
  expect(result.current.messages[1].citations).toEqual([citation]);
});
```

## Test Quality Guidelines

**Readability:**
- Use descriptive test names: `test_tool_use_loop_with_multiple_calls` not `test_tool`
- Keep tests short and focused (one assertion per test when possible)
- Use helper functions for complex mock setup
- Add docstrings explaining the test's purpose

**Isolation:**
- Each test should be independent and runnable in any order
- Clean up mocks/fixtures between tests (pytest handles scope)
- Don't rely on test execution order

**Maintainability:**
- Use fixtures for repeated setup
- Keep mock definitions near tests (or in conftest if shared)
- Parametrize tests for multiple similar inputs
- Avoid testing implementation details; test behavior

**Coverage:**
- Aim for 80% minimum (enforced by pytest-cov)
- Cover error paths, not just happy paths
- Test edge cases (empty lists, None values, boundary conditions)
- Skip testing abstract methods and type checks (`TYPE_CHECKING` blocks)

