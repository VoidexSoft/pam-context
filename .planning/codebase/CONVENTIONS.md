# Coding Conventions

**Analysis Date:** 2026-02-15

## Naming Patterns

**Files:**
- Python: `snake_case.py` (e.g., `hybrid_search.py`, `docling_parser.py`)
- TypeScript/React: `camelCase.ts`, `PascalCase.tsx` for components (e.g., `useChat.ts`, `MessageBubble.tsx`)
- Test files: `test_*.py`, `*.test.ts` (co-located with source)

**Functions/Methods:**
- Python: `snake_case` (e.g., `embed_texts()`, `ingest_document()`, `get_correlation_id()`)
- TypeScript: `camelCase` functions (e.g., `sendMessage()`, `useChat()`)
- React components: `PascalCase` (e.g., `MessageBubble`, `CitationTooltip`, `ChatInterface`)

**Variables:**
- Python: `snake_case` (e.g., `query_embedding`, `segment_type`, `correlation_id_var`)
- TypeScript: `camelCase` (e.g., `conversationId`, `isStreaming`, `statusText`)
- Constants: `UPPER_SNAKE_CASE` in Python (e.g., `MAX_TOOL_ITERATIONS`, `SYSTEM_PROMPT`)
- React hooks: `useXxx` pattern (e.g., `useChat`, `useDocuments`, `useMarkdownComponents`)

**Types/Interfaces:**
- Python dataclasses: `PascalCase` (e.g., `IngestionResult`, `Citation`, `AgentResponse`)
- Python Pydantic models: `PascalCase` (e.g., `Settings`, `BaseSettings`)
- TypeScript interfaces: `PascalCase` (e.g., `ChatMessage`, `SearchResult`, `Document`)
- SQLAlchemy ORM models: `PascalCase` (e.g., `Project`, `Document`, `Segment`, `User`)

## Code Style

**Formatting:**
- Python: Ruff with 120-character line length
- TypeScript: TypeScript compiler with strict mode enabled
- React: TSX/JSX syntax with TypeScript strict types

**Linting:**
- Python: Ruff (`ruff check` and `ruff format`)
  - Selected rules: E (errors), F (pyflakes), I (import sorting), N (naming), W (warnings), UP (pyupgrade)
  - Line length: 120 characters
- Pre-commit hooks via `.pre-commit-config.yaml`: trailing whitespace, file ending, YAML validation, debug statement detection
- No explicit ESLint/Prettier config for TypeScript (uses TSC strict mode)

**File Organization:**
- Python: Modules organized by feature (connector, parser, embedder, store, retrieval)
- TypeScript: Component-based organization with hooks, API client, utils, pages, styles
- Imports grouped by: future imports → stdlib → external packages → local modules

## Import Organization

**Order (Python):**
1. `from __future__ import annotations` (when needed)
2. Standard library imports (`import json`, `from dataclasses import dataclass`)
3. Type checking imports (`from typing import TYPE_CHECKING, Any`)
4. External packages (`import structlog`, `from sqlalchemy import ...`)
5. Local package imports (`from pam.common.config import settings`)

**Example from `src/pam/agent/agent.py`:**
```python
from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import structlog
from anthropic import AsyncAnthropic

from pam.agent.tools import ALL_TOOLS
from pam.common.config import settings
from pam.common.logging import CostTracker
```

**Path Aliases:**
- TypeScript: `@/*` maps to `src/*` (in `web/tsconfig.json`)
  - Used for relative imports in components: `import { ChatMessage } from "@/api/client"`

## Error Handling

**Patterns (Python):**
- Use `try/except` blocks with structured logging via `structlog`
- Propagate errors with context using `logger.exception()` or `logger.warning()`
- For pipeline operations: catch exceptions, log with context, return error in result object
- Example from `src/pam/ingestion/pipeline.py`:
  ```python
  try:
      raw_doc = await self.connector.fetch_document(source_id)
      logger.info("pipeline_fetch", source_id=source_id, title=raw_doc.title)
      # ... processing
  except Exception as e:
      logger.exception("error_context", source_id=source_id)
      return IngestionResult(source_id=source_id, title=title, error=str(e))
  ```

**Patterns (TypeScript/React):**
- Use try/catch in async functions
- Set error state on failure and clear on success
- Log errors with context (network, timeout, etc.)
- Example from `web/src/hooks/useChat.ts`:
  ```typescript
  try {
    // stream or API call
  } catch (err) {
    setError(err instanceof Error ? err.message : "Unknown error");
  }
  ```

**HTTP Error Handling (FastAPI):**
- Use `HTTPException` with status codes
- Return structured error responses with message and detail fields

## Logging

**Framework:** `structlog` (Python), `console` (TypeScript/React)

**Python Patterns:**
- Initialize: `logger = structlog.get_logger()`
- Log levels: `logger.info()`, `logger.warning()`, `logger.exception()`
- Context: pass key-value pairs as kwargs (e.g., `logger.info("event_name", query=query, top_k=10)`)
- Correlation IDs: automatically attached via `contextvars` (see `src/pam/common/logging.py`)
- Example: `logger.info("hybrid_search_cache_hit", query_length=len(query))`

**TypeScript/React Patterns:**
- Use `console.log()`, `console.error()` with descriptive messages
- Include context in error messages
- Streaming events use typed event objects (type: "token", "error", "status", "citation", "done")

**When to Log:**
- Cache hits/misses (info level)
- Tool execution start/end (status level in streaming)
- Errors and exceptions (exception/warning level)
- Performance metrics (latency, token usage)
- Configuration warnings (JWT secret validation)

## Comments

**When to Comment:**
- Docstrings required for all public functions and classes
- Explain WHY, not WHAT (code should be self-explanatory for WHAT)
- Document complex algorithms (e.g., RRF fusion in hybrid search)
- Explain non-obvious design decisions (e.g., why temp file cleanup is needed)

**Docstring Format (Python):**
- Use triple-quoted strings immediately after function/class signature
- Include: description, parameters, return type, exceptions
- Example from `src/pam/common/utils.py`:
  ```python
  def escape_like(value: str) -> str:
      """Escape SQL ILIKE/LIKE wildcard characters.

      Prevents user-controlled input from being interpreted as wildcard patterns
      when used in ILIKE queries.
      """
      return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
  ```

**JSDoc/TSDoc (TypeScript):**
- Use for public APIs and complex functions
- Example: interface documentation in `web/src/api/client.ts` has inline comments for field purposes
- Component props typically documented as TypeScript interfaces

**Module-Level Comments:**
- First line of Python files is a docstring describing the module's purpose
- Example: `"""Ingestion pipeline orchestrator: connector → parser → chunker → embedder → stores."""`

## Function Design

**Size:**
- Keep functions focused on single responsibility
- Python functions typically 20-50 lines; longer functions refactored into helpers
- TypeScript hooks and components similar sizing

**Parameters:**
- Avoid long parameter lists; use dataclass/type objects when multiple related params
- Type all parameters explicitly (Python type hints, TypeScript types)
- Example from `src/pam/agent/agent.py`:
  ```python
  def __init__(
      self,
      search_service: HybridSearchService,
      embedder: BaseEmbedder,
      api_key: str | None = None,
      model: str | None = None,
      cost_tracker: CostTracker | None = None,
      db_session: AsyncSession | None = None,
      duckdb_service: DuckDBService | None = None,
  ) -> None:
  ```

**Return Values:**
- Dataclasses for multiple return values (e.g., `IngestionResult`, `AgentResponse`)
- Type hint return values explicitly
- Use `None` for operations with side effects only
- Example: `async def ingest_document(self, source_id: str) -> IngestionResult:`

## Module Design

**Exports:**
- Python: no wildcard imports; explicit imports from modules
- TypeScript: named exports preferred; re-export grouped types from API modules
- Example API module exports from `web/src/api/client.ts`:
  ```typescript
  export interface ChatMessage { ... }
  export interface Citation { ... }
  export async function sendMessage(...) { ... }
  export async function streamChatMessage(...) { ... }
  ```

**Barrel Files:**
- Python: `__init__.py` files minimal; rarely re-export (prefer explicit imports)
- TypeScript: Index files export public types (e.g., API types from `web/src/api/`)

**Base Classes/Abstract Patterns:**
- Python: use `ABC` and `abstractmethod` for plugin interfaces
- Examples: `BaseConnector`, `BaseEmbedder`, `BaseReranker`, `BaseStore` in `src/pam/`
- Each base class defines contract and optional default implementations

## Type Annotations

**Python:**
- Use `from __future__ import annotations` for forward references
- Use type union syntax: `X | None` (Python 3.10+)
- Use `Mapped[T]` for SQLAlchemy ORM fields
- Use `TYPE_CHECKING` blocks for circular import prevention
- Example from `src/pam/common/models.py`:
  ```python
  id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
  metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
  documents: Mapped[list["Document"]] = relationship(back_populates="project")
  ```

**TypeScript:**
- Strict mode enabled: `"strict": true` in `tsconfig.json`
- All function parameters and returns typed
- Interface-based props for React components
- Avoid `any`; use `unknown` with type guards or proper typing

## Async/Await Patterns

**Python:**
- Async functions prefixed with `async def`
- Use `await` for async operations (database, HTTP, embeddings)
- Handle streaming with `async for` and `AsyncGenerator`
- Example from `src/pam/agent/agent.py`:
  ```python
  async def stream_answer(self, question: str) -> AsyncGenerator[dict, None]:
      """Yield streaming events (status, token, citation, done)."""
  ```

**TypeScript/React:**
- Hooks use `useCallback` for memoized async operations
- Streaming with `for await...of` async generators
- AbortController for cancellation support
- Example from `web/src/hooks/useChat.ts`:
  ```typescript
  for await (const event of streamChatMessage(...)) {
      switch (event.type) {
          case "token":
              // accumulate and update state
      }
  }
  ```

## Configuration & Secrets

**Pattern (Python):**
- Use Pydantic `Settings` class from `pydantic-settings` (see `src/pam/common/config.py`)
- All config via environment variables with defaults
- Validators for security-critical settings (e.g., JWT secret strength)
- No hardcoded secrets; use `.env` file (git-ignored)

**Example Settings:**
- Database: `database_url`, `elasticsearch_url`
- API Keys: `openai_api_key`, `anthropic_api_key` (empty by default, required at runtime)
- Auth: `jwt_secret`, `jwt_algorithm`, `auth_required` (strict validation when enabled)
- Feature flags: `use_haystack_retrieval`, `rerank_enabled`

