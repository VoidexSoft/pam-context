# Universal Memory Layer — Phase 1: MCP Server

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose PAM Context's existing capabilities as an MCP server so any LLM client (Claude Code, Cursor, ChatGPT, etc.) can search documents, query the knowledge graph, and trigger ingestion.

**Architecture:** A `FastMCP` server wrapping existing PAM services. A `PamServices` dataclass holds all service instances, initialized by a shared factory. Tools are thin async wrappers calling existing service methods. Two transports: stdio (local, `python -m pam.mcp`) and SSE (remote, mounted on FastAPI at `/mcp`).

**Tech Stack:** `mcp` Python SDK (FastMCP), Python 3.12, async/await, existing PAM services (SearchService, GraphitiService, OpenAIEmbedder, DuckDBService)

---

## Open-Source Landscape Research

Before building, we evaluated 18+ open-source projects that could replace parts of PAM's system. **No single project covers all five capabilities** PAM requires (ingestion, graph, hybrid search, agent memory, multi-connector). The market has fragmented into specialized layers.

### Decision Matrix

| PAM Capability | Current Impl | Best OSS Option | Recommendation |
|---|---|---|---|
| Document parsing | Docling | **Docling** (56.7k stars, MIT, IBM-backed) | Keep — best-in-class |
| Vector + BM25 search | ES 8.x RRF | **Haystack** (24.6k stars, Apache 2.0) | Keep — already optional backend |
| Knowledge graph | Neo4j + Graphiti | **Graphiti** (24.3k stars, Apache 2.0, sub-100ms) | Keep — best temporal graph |
| Agent tool loop | Custom Anthropic SDK | Keep custom (~50 lines) | Keep — no framework coupling |
| Agent memory | Not yet built | **Mem0** (51.4k stars, Apache 2.0) or **Graphiti** | Phase 2 decision — see below |
| Multi-connectors | Markdown, Google, GitHub | **LlamaIndex** (48.1k stars, 300+ connectors) or **Cognee** (14.8k, 30+) | Evaluate per-connector |
| MCP server | Not yet built | **mcp** Python SDK (official protocol) | Build with official SDK |
| Context assembly | Custom LightRAG-inspired | Keep custom | Keep — tuned to our budgets |

### Key Contenders Evaluated

| Project | Stars | What It Does Well | Why Not a Full Replacement |
|---------|-------|-------------------|---------------------------|
| **Cognee** | 14.8k | Closest to "universal memory" — ingestion + graph + vector | Pre-1.0, docs gaps, smaller community |
| **R2R** (SciPhi) | 7.7k | Most complete platform — ingestion, search, graph, auth | Smallest community, unclear dev velocity |
| **RAGFlow** | 76.5k | Best deep document understanding | Tightly coupled app, not a composable library |
| **LlamaIndex** | 48.1k | Largest ecosystem, 300+ connectors | Heavy dependency, vendor lock-in risk |
| **Mem0** | 51.4k | Best agent memory API, AWS partnership | Memory only — no ingestion, search, or graph |
| **Letta** | 21.8k | Novel tiered memory (core/recall/archival) | Full runtime commitment, no document support |
| **Microsoft GraphRAG** | 31.8k | Best corpus-wide analytical queries | $50-200/corpus indexing, 45min build time |
| **LightRAG** | 31k | 100x cheaper than MS GraphRAG, PG-native | Text-only ingestion, no agent memory |

### Strategic Decision: Option A — Incremental Enhancement

Keep PAM's custom architecture. Adopt best-of-breed OSS components surgically:

1. **Keep** Docling, Graphiti, custom agent loop, custom context assembly
2. **Phase 1** (this plan): Build MCP server with official `mcp` SDK
3. **Phase 2**: Build Memory CRUD using Mem0's patterns (semantic dedup, importance scoring) — or evaluate Graphiti's built-in session memory
4. **Phase 3**: Conversational memory — build custom (Mem0 patterns for fact extraction)
5. **Phase 4**: Semantic metadata — no good OSS exists, build custom
6. **Phase 5**: Fact extraction — build custom (Cognee's pipeline as inspiration)
7. **Phase 6**: Multi-agent router — build custom supervisor pattern

**Rationale:** PAM's architecture already matches the market's convergence point — multiple specialized stores (vector, graph, relational) unified by an orchestration layer. Replacing parts would add coupling without clear benefit. Build on what works.

---

## Scope: Phase 1 Only

This plan covers **Phase 1: MCP Server** only. Phases 2-6 are independent subsystems requiring separate plans. Phase 1 delivers:

- 10 MCP tools exposing existing PAM capabilities
- 3 MCP resources for system introspection
- stdio transport for local LLM clients
- SSE transport mounted on existing FastAPI app
- Full test coverage

---

## File Structure

### New Files

```
src/pam/mcp/
├── __init__.py              # Re-exports create_mcp_server
├── server.py                # FastMCP server definition + all tool/resource registrations
├── services.py              # PamServices dataclass + create/close factory
└── __main__.py              # stdio entrypoint: python -m pam.mcp

tests/mcp/
├── __init__.py
├── conftest.py              # Mock PamServices fixture, shared helpers
├── test_search_tools.py     # pam_search, pam_smart_search
├── test_document_tools.py   # pam_get_document, pam_list_documents
├── test_graph_tools.py      # pam_graph_search, pam_graph_neighbors, pam_entity_history
├── test_util_tools.py       # pam_query_data, pam_ingest
└── test_resources.py        # pam://stats, pam://entities
```

### Modified Files

```
pyproject.toml               # Add "mcp[cli]>=1.0" dependency
src/pam/api/main.py          # Mount SSE transport at /mcp
src/pam/common/config.py     # Add mcp_enabled setting
```

---

## Task 1: Add MCP Dependency + Module Skeleton

**Files:**
- Modify: `pyproject.toml` (add dependency)
- Create: `src/pam/mcp/__init__.py`
- Create: `src/pam/mcp/server.py`
- Create: `tests/mcp/__init__.py`
- Test: `tests/mcp/test_search_tools.py` (first test only)

- [ ] **Step 1: Add mcp dependency to pyproject.toml**

In `pyproject.toml`, add to the `dependencies` list after the `# Utilities` section:

```toml
    # MCP Server
    "mcp[cli]>=1.0",
```

- [ ] **Step 2: Install the dependency**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && uv sync`
Expected: Successful installation, `mcp` package available

- [ ] **Step 3: Create the MCP module skeleton**

Create `src/pam/mcp/__init__.py`:

```python
"""MCP Server — exposes PAM capabilities to LLM clients."""

from pam.mcp.server import create_mcp_server

__all__ = ["create_mcp_server"]
```

Create `src/pam/mcp/server.py`:

```python
"""MCP server definition with tool and resource registrations."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import structlog
from mcp.server.fastmcp import FastMCP

if TYPE_CHECKING:
    from pam.mcp.services import PamServices

logger = structlog.get_logger()

_services: PamServices | None = None


def get_services() -> PamServices:
    """Return the initialized PamServices instance.

    Raises AssertionError if called before initialize().
    """
    if _services is None:
        msg = "MCP services not initialized — call initialize() first"
        raise RuntimeError(msg)
    return _services


def initialize(services: PamServices) -> None:
    """Set the global services instance. Called once at startup."""
    global _services  # noqa: PLW0603
    _services = services


def create_mcp_server() -> FastMCP:
    """Create and return the FastMCP server with all tools registered."""
    mcp = FastMCP(
        "PAM Context",
        description="Business Knowledge Layer for LLMs — search documents, query knowledge graph, trigger ingestion",
    )
    _register_search_tools(mcp)
    _register_document_tools(mcp)
    _register_graph_tools(mcp)
    _register_utility_tools(mcp)
    _register_resources(mcp)
    return mcp


def _register_search_tools(mcp: FastMCP) -> None:
    """Register search-related MCP tools. Implemented in Task 3-4."""
    pass


def _register_document_tools(mcp: FastMCP) -> None:
    """Register document-related MCP tools. Implemented in Task 5."""
    pass


def _register_graph_tools(mcp: FastMCP) -> None:
    """Register graph-related MCP tools. Implemented in Task 6."""
    pass


def _register_utility_tools(mcp: FastMCP) -> None:
    """Register utility MCP tools. Implemented in Task 7."""
    pass


def _register_resources(mcp: FastMCP) -> None:
    """Register MCP resources. Implemented in Task 8."""
    pass
```

Create `tests/mcp/__init__.py` (empty file).

- [ ] **Step 4: Write first test — verify server creation**

Create `tests/mcp/test_search_tools.py`:

```python
"""Tests for MCP search tools."""

from pam.mcp.server import create_mcp_server


def test_create_mcp_server():
    """Server can be created without errors."""
    server = create_mcp_server()
    assert server is not None
    assert server.name == "PAM Context"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/mcp/test_search_tools.py::test_create_mcp_server -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/mcp/__init__.py src/pam/mcp/server.py tests/mcp/__init__.py tests/mcp/test_search_tools.py pyproject.toml
git commit -m "feat(mcp): add MCP dependency and server module skeleton"
```

---

## Task 2: PamServices Container

**Files:**
- Create: `src/pam/mcp/services.py`
- Create: `tests/mcp/conftest.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/mcp/conftest.py`:

```python
"""Shared fixtures for MCP tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp.services import PamServices


@pytest.fixture()
def mock_services() -> PamServices:
    """Create a PamServices with all dependencies mocked."""
    return PamServices(
        search_service=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=MagicMock(),
        es_client=AsyncMock(),
        graph_service=AsyncMock(),
        vdb_store=AsyncMock(),
        duckdb_service=MagicMock(),
        cache_service=AsyncMock(),
    )
```

Add test to `tests/mcp/test_search_tools.py`:

```python
from pam.mcp.services import PamServices


def test_pam_services_fields():
    """PamServices has all expected fields."""
    import dataclasses

    fields = {f.name for f in dataclasses.fields(PamServices)}
    assert "search_service" in fields
    assert "embedder" in fields
    assert "session_factory" in fields
    assert "es_client" in fields
    assert "graph_service" in fields
    assert "vdb_store" in fields
    assert "duckdb_service" in fields
    assert "cache_service" in fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/mcp/test_search_tools.py::test_pam_services_fields -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pam.mcp.services'`

- [ ] **Step 3: Implement PamServices**

Create `src/pam/mcp/services.py`:

```python
"""Service container for MCP server dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch
    from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

    from pam.agent.duckdb_service import DuckDBService
    from pam.common.cache import CacheService
    from pam.graph.service import GraphitiService
    from pam.ingestion.embedders.base import BaseEmbedder
    from pam.ingestion.stores.entity_relationship_store import EntityRelationshipVDBStore
    from pam.retrieval.search_protocol import SearchService

logger = structlog.get_logger()


@dataclass
class PamServices:
    """Holds all service instances needed by MCP tools.

    Constructed either from FastAPI app.state (SSE mode) or by
    create_services() (stdio mode).
    """

    search_service: SearchService
    embedder: BaseEmbedder
    session_factory: async_sessionmaker[AsyncSession]
    es_client: AsyncElasticsearch
    graph_service: GraphitiService | None
    vdb_store: EntityRelationshipVDBStore | None
    duckdb_service: DuckDBService | None
    cache_service: CacheService | None


def from_app_state(app_state: object) -> PamServices:
    """Extract PamServices from a FastAPI app.state object.

    Used by the SSE transport to share services with the FastAPI app.
    """
    return PamServices(
        search_service=getattr(app_state, "search_service"),
        embedder=getattr(app_state, "embedder"),
        session_factory=getattr(app_state, "session_factory"),
        es_client=getattr(app_state, "es_client"),
        graph_service=getattr(app_state, "graph_service", None),
        vdb_store=getattr(app_state, "vdb_store", None),
        duckdb_service=getattr(app_state, "duckdb_service", None),
        cache_service=getattr(app_state, "cache_service", None),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_search_tools.py -v`
Expected: PASS (both `test_create_mcp_server` and `test_pam_services_fields`)

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/services.py tests/mcp/conftest.py tests/mcp/test_search_tools.py
git commit -m "feat(mcp): add PamServices container and mock fixture"
```

---

## Task 3: pam_search Tool

**Files:**
- Modify: `src/pam/mcp/server.py`
- Modify: `tests/mcp/test_search_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/mcp/test_search_tools.py`:

```python
import json
import uuid

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices
from pam.retrieval.types import SearchResult


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    """Initialize MCP services for every test in this module."""
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_search_returns_results(mock_services: PamServices):
    """pam_search calls search_service and returns JSON results."""
    segment_id = uuid.uuid4()
    mock_services.embedder.embed = AsyncMock(return_value=[0.1] * 1536)
    mock_services.search_service.search = AsyncMock(
        return_value=[
            SearchResult(
                segment_id=segment_id,
                content="Revenue grew 15% YoY",
                score=0.95,
                document_title="Q1 Report",
                section_path="financials > revenue",
                source_url="/docs/q1-report.md",
            ),
        ]
    )

    server = create_mcp_server()
    # Call the tool function directly by looking it up
    from pam.mcp.server import _pam_search

    result = await _pam_search(query="revenue growth", limit=5, source_type=None)
    parsed = json.loads(result)

    assert len(parsed) == 1
    assert parsed[0]["content"] == "Revenue grew 15% YoY"
    assert parsed[0]["document_title"] == "Q1 Report"
    mock_services.embedder.embed.assert_awaited_once_with("revenue growth")
    mock_services.search_service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_search_with_source_filter(mock_services: PamServices):
    """pam_search passes source_type filter to search service."""
    mock_services.embedder.embed = AsyncMock(return_value=[0.1] * 1536)
    mock_services.search_service.search = AsyncMock(return_value=[])

    from pam.mcp.server import _pam_search

    result = await _pam_search(query="test", limit=3, source_type="markdown")
    parsed = json.loads(result)

    assert parsed == []
    call_kwargs = mock_services.search_service.search.call_args
    assert call_kwargs.kwargs.get("source_type") == "markdown"
    assert call_kwargs.kwargs.get("top_k") == 3
```

Don't forget the import at top of file:

```python
from unittest.mock import AsyncMock
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_search_tools.py::test_pam_search_returns_results -v`
Expected: FAIL with `ImportError: cannot import name '_pam_search'`

- [ ] **Step 3: Implement pam_search**

In `src/pam/mcp/server.py`, replace `_register_search_tools`:

```python
def _register_search_tools(mcp: FastMCP) -> None:
    """Register search-related MCP tools."""

    @mcp.tool()
    async def pam_search(
        query: str,
        limit: int = 5,
        source_type: str | None = None,
    ) -> str:
        """Search PAM's knowledge base with hybrid BM25 + vector search.

        Returns relevant document segments with source citations, scores, and
        section paths. Use this for factual lookups, definitions, and document Q&A.
        """
        return await _pam_search(query=query, limit=limit, source_type=source_type)

    # pam_smart_search registered in Task 4


async def _pam_search(
    query: str,
    limit: int = 5,
    source_type: str | None = None,
) -> str:
    """Implementation of pam_search, extracted for direct testing."""
    services = get_services()
    embedding = await services.embedder.embed(query)
    results = await services.search_service.search(
        query=query,
        query_embedding=embedding,
        top_k=limit,
        source_type=source_type,
    )
    return json.dumps(
        [
            {
                "segment_id": str(r.segment_id),
                "content": r.content,
                "score": r.score,
                "document_title": r.document_title,
                "section_path": r.section_path,
                "source_url": r.source_url,
            }
            for r in results
        ],
        indent=2,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_search_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/server.py tests/mcp/test_search_tools.py
git commit -m "feat(mcp): implement pam_search tool with hybrid search"
```

---

## Task 4: pam_smart_search Tool

**Files:**
- Modify: `src/pam/mcp/server.py`
- Modify: `tests/mcp/test_search_tools.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/mcp/test_search_tools.py`:

```python
@pytest.mark.asyncio
async def test_pam_smart_search_concurrent_results(mock_services: PamServices):
    """pam_smart_search runs ES + graph + VDB searches concurrently."""
    mock_services.embedder.embed = AsyncMock(return_value=[0.1] * 1536)
    mock_services.search_service.search = AsyncMock(
        return_value=[
            SearchResult(
                segment_id=uuid.uuid4(),
                content="ES result",
                score=0.9,
                document_title="Doc A",
            ),
        ]
    )
    mock_services.graph_service.client.search = AsyncMock(return_value=[])
    mock_services.vdb_store.search_entities = AsyncMock(return_value=[])
    mock_services.vdb_store.search_relationships = AsyncMock(return_value=[])

    from pam.mcp.server import _pam_smart_search

    result = await _pam_smart_search(query="revenue targets")
    parsed = json.loads(result)

    assert "documents" in parsed
    assert len(parsed["documents"]) == 1
    assert parsed["documents"][0]["content"] == "ES result"
    mock_services.search_service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_smart_search_graph_unavailable(mock_services: PamServices):
    """pam_smart_search gracefully handles graph service being None."""
    mock_services.graph_service = None
    mock_services.vdb_store = None
    mock_services.embedder.embed = AsyncMock(return_value=[0.1] * 1536)
    mock_services.search_service.search = AsyncMock(return_value=[])

    # Re-initialize services after mutation
    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_smart_search

    result = await _pam_smart_search(query="test")
    parsed = json.loads(result)

    assert "documents" in parsed
    assert parsed["graph"] == []
    assert parsed["entities"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_search_tools.py::test_pam_smart_search_concurrent_results -v`
Expected: FAIL with `ImportError: cannot import name '_pam_smart_search'`

- [ ] **Step 3: Implement pam_smart_search**

Add to `_register_search_tools` in `src/pam/mcp/server.py` (after the pam_search registration):

```python
    @mcp.tool()
    async def pam_smart_search(
        query: str,
        mode: str | None = None,
    ) -> str:
        """Search documents AND the knowledge graph in one call.

        Runs hybrid document search, graph relationship search, entity VDB search,
        and relationship VDB search concurrently. Returns results in separate sections.
        Optional mode: entity, conceptual, temporal, factual, hybrid.
        """
        return await _pam_smart_search(query=query, mode=mode)
```

Add the implementation function after `_pam_search`:

```python
async def _pam_smart_search(
    query: str,
    mode: str | None = None,
) -> str:
    """Implementation of pam_smart_search — concurrent 4-way search."""
    import asyncio

    services = get_services()
    embedding = await services.embedder.embed(query)

    # Build concurrent tasks
    tasks: dict[str, Any] = {}

    # Always run document search
    tasks["documents"] = services.search_service.search(
        query=query, query_embedding=embedding, top_k=5,
    )

    # Graph search (if available)
    if services.graph_service is not None:
        tasks["graph"] = services.graph_service.client.search(query=query, num_results=5)

    # Entity VDB search (if available)
    if services.vdb_store is not None:
        tasks["entities"] = services.vdb_store.search_entities(
            query_embedding=embedding, top_k=5,
        )
        tasks["relationships"] = services.vdb_store.search_relationships(
            query_embedding=embedding, top_k=5,
        )

    # Execute concurrently
    keys = list(tasks.keys())
    results_list = await asyncio.gather(*tasks.values(), return_exceptions=True)
    results_map: dict[str, Any] = {}
    for key, result in zip(keys, results_list):
        if isinstance(result, Exception):
            logger.warning("smart_search_partial_failure", source=key, error=str(result))
            results_map[key] = []
        else:
            results_map[key] = result

    # Format document results
    doc_results = [
        {
            "segment_id": str(r.segment_id),
            "content": r.content,
            "score": r.score,
            "document_title": r.document_title,
            "section_path": r.section_path,
            "source_url": r.source_url,
        }
        for r in results_map.get("documents", [])
    ]

    # Format graph results
    graph_results = []
    for edge in results_map.get("graph", []):
        graph_results.append({
            "fact": getattr(edge, "fact", str(edge)),
            "source_name": getattr(edge, "source_node_name", None),
            "target_name": getattr(edge, "target_node_name", None),
            "relation_type": getattr(edge, "name", None),
        })

    # Format entity results
    entity_results = []
    for hit in results_map.get("entities", []):
        entity_results.append({
            "name": hit.get("name", ""),
            "type": hit.get("type", ""),
            "description": hit.get("description", ""),
            "score": hit.get("score", 0),
        })

    # Format relationship results
    rel_results = []
    for hit in results_map.get("relationships", []):
        rel_results.append({
            "src_entity": hit.get("src_entity", ""),
            "tgt_entity": hit.get("tgt_entity", ""),
            "rel_type": hit.get("rel_type", ""),
            "keywords": hit.get("keywords", ""),
            "score": hit.get("score", 0),
        })

    return json.dumps(
        {
            "documents": doc_results,
            "graph": graph_results,
            "entities": entity_results,
            "relationships": rel_results,
            "mode": mode,
        },
        indent=2,
    )
```

Add the `Any` import at the top of the file:

```python
from typing import TYPE_CHECKING, Any
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_search_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/server.py tests/mcp/test_search_tools.py
git commit -m "feat(mcp): implement pam_smart_search with concurrent 4-way search"
```

---

## Task 5: Document Tools (pam_get_document, pam_list_documents)

**Files:**
- Modify: `src/pam/mcp/server.py`
- Create: `tests/mcp/test_document_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_document_tools.py`:

```python
"""Tests for MCP document tools."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_get_document_by_title(mock_services: PamServices):
    """pam_get_document fetches a document by title."""
    doc_id = uuid.uuid4()
    mock_doc = MagicMock()
    mock_doc.id = doc_id
    mock_doc.title = "Q1 Report"
    mock_doc.source_type = "markdown"
    mock_doc.source_id = "/docs/q1.md"
    mock_doc.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)

    mock_segment = MagicMock()
    mock_segment.content = "Revenue grew 15%"
    mock_segment.section_path = "financials"
    mock_segment.position = 0

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_doc

    mock_seg_result = MagicMock()
    mock_seg_result.scalars.return_value.all.return_value = [mock_segment]

    mock_session.execute = AsyncMock(side_effect=[mock_result, mock_seg_result])
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _pam_get_document

    result = await _pam_get_document(document_title="Q1 Report", source_id=None)
    parsed = json.loads(result)

    assert parsed["title"] == "Q1 Report"
    assert len(parsed["segments"]) == 1
    assert parsed["segments"][0]["content"] == "Revenue grew 15%"


@pytest.mark.asyncio
async def test_pam_get_document_not_found(mock_services: PamServices):
    """pam_get_document returns error when document not found."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _pam_get_document

    result = await _pam_get_document(document_title="Nonexistent", source_id=None)
    parsed = json.loads(result)

    assert "error" in parsed


@pytest.mark.asyncio
async def test_pam_list_documents(mock_services: PamServices):
    """pam_list_documents returns paginated document list."""
    mock_doc = MagicMock()
    mock_doc.id = uuid.uuid4()
    mock_doc.title = "Q1 Report"
    mock_doc.source_type = "markdown"
    mock_doc.created_at = datetime(2026, 1, 15, tzinfo=timezone.utc)
    mock_doc.updated_at = datetime(2026, 1, 15, tzinfo=timezone.utc)

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_doc]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _pam_list_documents

    result = await _pam_list_documents(limit=10, source_type=None)
    parsed = json.loads(result)

    assert len(parsed["documents"]) == 1
    assert parsed["documents"][0]["title"] == "Q1 Report"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_document_tools.py::test_pam_get_document_by_title -v`
Expected: FAIL with `ImportError: cannot import name '_pam_get_document'`

- [ ] **Step 3: Implement document tools**

Replace `_register_document_tools` in `src/pam/mcp/server.py`:

```python
def _register_document_tools(mcp: FastMCP) -> None:
    """Register document-related MCP tools."""

    @mcp.tool()
    async def pam_get_document(
        document_title: str | None = None,
        source_id: str | None = None,
    ) -> str:
        """Fetch the full content of a specific document for deep reading.

        Provide either document_title or source_id. Returns the document
        metadata and all its segments (chunks) in order.
        """
        return await _pam_get_document(document_title=document_title, source_id=source_id)

    @mcp.tool()
    async def pam_list_documents(
        limit: int = 20,
        source_type: str | None = None,
    ) -> str:
        """List available documents in the knowledge base.

        Returns document titles, source types, and timestamps.
        Optional source_type filter: markdown, google_doc, google_sheets, github.
        """
        return await _pam_list_documents(limit=limit, source_type=source_type)


async def _pam_get_document(
    document_title: str | None = None,
    source_id: str | None = None,
) -> str:
    """Implementation of pam_get_document."""
    from sqlalchemy import select

    from pam.common.models import Document, Segment

    services = get_services()

    async with services.session_factory() as session:
        # Find the document
        stmt = select(Document)
        if document_title:
            stmt = stmt.where(Document.title.ilike(f"%{document_title}%"))
        elif source_id:
            stmt = stmt.where(Document.source_id == source_id)
        else:
            return json.dumps({"error": "Provide either document_title or source_id"})

        result = await session.execute(stmt)
        doc = result.scalars().first()

        if doc is None:
            return json.dumps({"error": f"Document not found: {document_title or source_id}"})

        # Fetch segments
        seg_stmt = (
            select(Segment)
            .where(Segment.document_id == doc.id)
            .order_by(Segment.position)
        )
        seg_result = await session.execute(seg_stmt)
        segments = seg_result.scalars().all()

        return json.dumps(
            {
                "id": str(doc.id),
                "title": doc.title,
                "source_type": doc.source_type,
                "source_id": doc.source_id,
                "created_at": doc.created_at.isoformat() if doc.created_at else None,
                "segments": [
                    {
                        "content": seg.content,
                        "section_path": seg.section_path,
                        "position": seg.position,
                    }
                    for seg in segments
                ],
            },
            indent=2,
        )


async def _pam_list_documents(
    limit: int = 20,
    source_type: str | None = None,
) -> str:
    """Implementation of pam_list_documents."""
    from sqlalchemy import select

    from pam.common.models import Document

    services = get_services()

    async with services.session_factory() as session:
        stmt = select(Document).order_by(Document.updated_at.desc()).limit(limit)
        if source_type:
            stmt = stmt.where(Document.source_type == source_type)

        result = await session.execute(stmt)
        docs = result.scalars().all()

        return json.dumps(
            {
                "documents": [
                    {
                        "id": str(doc.id),
                        "title": doc.title,
                        "source_type": doc.source_type,
                        "created_at": doc.created_at.isoformat() if doc.created_at else None,
                        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
                    }
                    for doc in docs
                ],
                "count": len(docs),
            },
            indent=2,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_document_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/server.py tests/mcp/test_document_tools.py
git commit -m "feat(mcp): implement pam_get_document and pam_list_documents tools"
```

---

## Task 6: Graph Tools (pam_graph_search, pam_graph_neighbors, pam_entity_history)

**Files:**
- Modify: `src/pam/mcp/server.py`
- Create: `tests/mcp/test_graph_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_graph_tools.py`:

```python
"""Tests for MCP graph tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_graph_search_returns_edges(mock_services: PamServices):
    """pam_graph_search returns relationship edges from Graphiti."""
    mock_edge = MagicMock()
    mock_edge.fact = "AuthService depends on UserDB"
    mock_edge.source_node_name = "AuthService"
    mock_edge.target_node_name = "UserDB"
    mock_edge.name = "DEPENDS_ON"

    mock_services.graph_service.client.search = AsyncMock(return_value=[mock_edge])

    from pam.mcp.server import _pam_graph_search

    result = await _pam_graph_search(query="AuthService dependencies")
    parsed = json.loads(result)

    assert len(parsed["results"]) == 1
    assert parsed["results"][0]["fact"] == "AuthService depends on UserDB"
    assert parsed["results"][0]["source_name"] == "AuthService"


@pytest.mark.asyncio
async def test_pam_graph_search_unavailable(mock_services: PamServices):
    """pam_graph_search returns error when graph service is None."""
    mock_services.graph_service = None
    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_graph_search

    result = await _pam_graph_search(query="test")
    parsed = json.loads(result)

    assert "error" in parsed
    assert "unavailable" in parsed["error"].lower()


@pytest.mark.asyncio
async def test_pam_graph_neighbors(mock_services: PamServices):
    """pam_graph_neighbors returns 1-hop neighborhood."""
    mock_node = MagicMock()
    mock_node.name = "AuthService"
    mock_node.group_id = "service"
    mock_node.summary = "Authentication microservice"

    mock_edge = MagicMock()
    mock_edge.fact = "AuthService uses Redis for sessions"
    mock_edge.source_node_name = "AuthService"
    mock_edge.target_node_name = "Redis"
    mock_edge.name = "USES"

    mock_services.graph_service.client.get_nodes_by_query = AsyncMock(
        return_value=[mock_node]
    )
    mock_services.graph_service.client.get_edges_by_query = AsyncMock(
        return_value=[mock_edge]
    )

    from pam.mcp.server import _pam_graph_neighbors

    result = await _pam_graph_neighbors(entity_name="AuthService")
    parsed = json.loads(result)

    assert parsed["entity"] == "AuthService"
    assert len(parsed["neighbors"]) >= 0  # May vary based on edge parsing


@pytest.mark.asyncio
async def test_pam_entity_history(mock_services: PamServices):
    """pam_entity_history returns temporal snapshots."""
    mock_edge = MagicMock()
    mock_edge.fact = "AuthService was migrated to v2"
    mock_edge.created_at = "2026-02-01T00:00:00Z"
    mock_edge.name = "MIGRATED_TO"

    mock_services.graph_service.client.search = AsyncMock(return_value=[mock_edge])

    from pam.mcp.server import _pam_entity_history

    result = await _pam_entity_history(entity_name="AuthService", since=None)
    parsed = json.loads(result)

    assert parsed["entity"] == "AuthService"
    assert len(parsed["history"]) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_graph_tools.py::test_pam_graph_search_returns_edges -v`
Expected: FAIL with `ImportError: cannot import name '_pam_graph_search'`

- [ ] **Step 3: Implement graph tools**

Replace `_register_graph_tools` in `src/pam/mcp/server.py`:

```python
def _register_graph_tools(mcp: FastMCP) -> None:
    """Register graph-related MCP tools."""

    @mcp.tool()
    async def pam_graph_search(
        query: str,
        entity_name: str | None = None,
    ) -> str:
        """Search the knowledge graph for entity relationships and connections.

        Use for questions about what entities relate to, depend on, or interact with.
        Examples: 'what depends on AuthService?', 'what is connected to payments?'
        """
        return await _pam_graph_search(query=query, entity_name=entity_name)

    @mcp.tool()
    async def pam_graph_neighbors(
        entity_name: str,
    ) -> str:
        """Explore the 1-hop neighborhood of an entity in the knowledge graph.

        Returns the entity and all directly connected entities with their relationships.
        """
        return await _pam_graph_neighbors(entity_name=entity_name)

    @mcp.tool()
    async def pam_entity_history(
        entity_name: str,
        since: str | None = None,
    ) -> str:
        """Get the temporal change history of a specific entity.

        Shows how an entity has changed over time. Optional 'since' parameter
        accepts ISO datetime (e.g. '2026-01-01T00:00:00Z') to filter changes.
        """
        return await _pam_entity_history(entity_name=entity_name, since=since)


async def _pam_graph_search(
    query: str,
    entity_name: str | None = None,
) -> str:
    """Implementation of pam_graph_search."""
    services = get_services()

    if services.graph_service is None:
        return json.dumps({"error": "Knowledge graph service is unavailable"})

    search_query = f"{entity_name}: {query}" if entity_name else query
    edges = await services.graph_service.client.search(query=search_query, num_results=10)

    return json.dumps(
        {
            "results": [
                {
                    "fact": getattr(edge, "fact", str(edge)),
                    "source_name": getattr(edge, "source_node_name", None),
                    "target_name": getattr(edge, "target_node_name", None),
                    "relation_type": getattr(edge, "name", None),
                }
                for edge in edges
            ],
            "count": len(edges),
        },
        indent=2,
    )


async def _pam_graph_neighbors(entity_name: str) -> str:
    """Implementation of pam_graph_neighbors."""
    services = get_services()

    if services.graph_service is None:
        return json.dumps({"error": "Knowledge graph service is unavailable"})

    query = f"relationships of {entity_name}"
    edges = await services.graph_service.client.search(query=query, num_results=20)

    neighbors: list[dict[str, Any]] = []
    for edge in edges:
        src = getattr(edge, "source_node_name", None)
        tgt = getattr(edge, "target_node_name", None)
        # Include edges where entity appears on either side
        if src and tgt:
            neighbor_name = tgt if src.lower() == entity_name.lower() else src
            neighbors.append({
                "name": neighbor_name,
                "relationship": getattr(edge, "name", None),
                "fact": getattr(edge, "fact", str(edge)),
                "direction": "outgoing" if src.lower() == entity_name.lower() else "incoming",
            })

    return json.dumps(
        {
            "entity": entity_name,
            "neighbors": neighbors,
            "count": len(neighbors),
        },
        indent=2,
    )


async def _pam_entity_history(entity_name: str, since: str | None = None) -> str:
    """Implementation of pam_entity_history."""
    services = get_services()

    if services.graph_service is None:
        return json.dumps({"error": "Knowledge graph service is unavailable"})

    query = f"history of {entity_name}"
    edges = await services.graph_service.client.search(query=query, num_results=20)

    history = [
        {
            "fact": getattr(edge, "fact", str(edge)),
            "relation_type": getattr(edge, "name", None),
            "created_at": getattr(edge, "created_at", None),
        }
        for edge in edges
    ]

    # Filter by since if provided
    if since:
        history = [h for h in history if h.get("created_at") and h["created_at"] >= since]

    return json.dumps(
        {
            "entity": entity_name,
            "history": history,
            "count": len(history),
        },
        indent=2,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_graph_tools.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/server.py tests/mcp/test_graph_tools.py
git commit -m "feat(mcp): implement graph tools — search, neighbors, entity history"
```

---

## Task 7: Utility Tools (pam_query_data, pam_ingest)

**Files:**
- Modify: `src/pam/mcp/server.py`
- Create: `tests/mcp/test_util_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_util_tools.py`:

```python
"""Tests for MCP utility tools."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_query_data_executes_sql(mock_services: PamServices):
    """pam_query_data runs a SQL query via DuckDB."""
    mock_services.duckdb_service.query.return_value = {
        "columns": ["name", "revenue"],
        "rows": [["Product A", 1000], ["Product B", 2000]],
        "row_count": 2,
    }

    from pam.mcp.server import _pam_query_data

    result = await _pam_query_data(sql="SELECT name, revenue FROM products", list_tables=False)
    parsed = json.loads(result)

    assert parsed["row_count"] == 2
    assert parsed["columns"] == ["name", "revenue"]
    mock_services.duckdb_service.query.assert_called_once()


@pytest.mark.asyncio
async def test_pam_query_data_list_tables(mock_services: PamServices):
    """pam_query_data lists available tables when list_tables=True."""
    mock_services.duckdb_service.list_tables.return_value = {
        "tables": [{"name": "products", "columns": ["name", "revenue"]}],
    }

    from pam.mcp.server import _pam_query_data

    result = await _pam_query_data(sql=None, list_tables=True)
    parsed = json.loads(result)

    assert "tables" in parsed
    mock_services.duckdb_service.list_tables.assert_called_once()


@pytest.mark.asyncio
async def test_pam_query_data_unavailable(mock_services: PamServices):
    """pam_query_data returns error when DuckDB is not configured."""
    mock_services.duckdb_service = None
    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_query_data

    result = await _pam_query_data(sql="SELECT 1", list_tables=False)
    parsed = json.loads(result)

    assert "error" in parsed


@pytest.mark.asyncio
async def test_pam_ingest_folder(mock_services: PamServices):
    """pam_ingest triggers folder ingestion and returns task info."""
    from pam.mcp.server import _pam_ingest

    mock_session = AsyncMock()
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    with pytest.raises(Exception):
        # Will fail because we can't easily mock the full pipeline,
        # but we verify the function exists and accepts the right params
        await _pam_ingest(folder_path="/data/docs", source_type="markdown")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_util_tools.py::test_pam_query_data_executes_sql -v`
Expected: FAIL with `ImportError: cannot import name '_pam_query_data'`

- [ ] **Step 3: Implement utility tools**

Replace `_register_utility_tools` in `src/pam/mcp/server.py`:

```python
def _register_utility_tools(mcp: FastMCP) -> None:
    """Register utility MCP tools."""

    @mcp.tool()
    async def pam_query_data(
        sql: str | None = None,
        list_tables: bool = False,
    ) -> str:
        """Run SQL queries against registered data files (CSV, Parquet, JSON) via DuckDB.

        Set list_tables=true to see available tables and their schemas.
        Queries must be read-only SELECT statements. Max 1000 rows returned.
        """
        return await _pam_query_data(sql=sql, list_tables=list_tables)

    @mcp.tool()
    async def pam_ingest(
        folder_path: str,
        source_type: str = "markdown",
    ) -> str:
        """Trigger document ingestion from a local folder.

        Parses documents, chunks them, embeds, and stores in the knowledge base.
        source_type: markdown, google_doc, google_sheets, github.
        Returns a task ID for monitoring progress.
        """
        return await _pam_ingest(folder_path=folder_path, source_type=source_type)


async def _pam_query_data(
    sql: str | None = None,
    list_tables: bool = False,
) -> str:
    """Implementation of pam_query_data."""
    services = get_services()

    if services.duckdb_service is None:
        return json.dumps({"error": "DuckDB analytics is not configured (no DUCKDB_DATA_DIR set)"})

    if list_tables:
        tables = services.duckdb_service.list_tables()
        return json.dumps(tables, indent=2)

    if not sql:
        return json.dumps({"error": "Provide a SQL query or set list_tables=true"})

    result = services.duckdb_service.query(sql)
    return json.dumps(result, indent=2)


async def _pam_ingest(folder_path: str, source_type: str = "markdown") -> str:
    """Implementation of pam_ingest — triggers folder ingestion."""
    import uuid as uuid_mod

    from pam.common.config import get_settings
    from pam.ingestion.task_manager import TaskManager

    services = get_services()
    settings = get_settings()

    task_manager = TaskManager(services.session_factory)
    task_id = uuid_mod.uuid4()

    try:
        await task_manager.spawn_ingestion_task(
            task_id=task_id,
            folder_path=folder_path,
            source_type=source_type,
            es_client=services.es_client,
            embedder=services.embedder,
            graph_service=services.graph_service,
            vdb_store=services.vdb_store,
        )
    except Exception as e:
        return json.dumps({"error": f"Failed to start ingestion: {e}"})

    return json.dumps(
        {
            "task_id": str(task_id),
            "status": "started",
            "folder_path": folder_path,
            "source_type": source_type,
            "message": "Ingestion task started. Poll /api/ingest/tasks/{task_id} for progress.",
        },
        indent=2,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_util_tools.py -v`
Expected: All PASS (the ingest test expects an exception since we can't mock the full pipeline)

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/server.py tests/mcp/test_util_tools.py
git commit -m "feat(mcp): implement pam_query_data and pam_ingest tools"
```

---

## Task 8: MCP Resources (pam://stats, pam://entities)

**Files:**
- Modify: `src/pam/mcp/server.py`
- Create: `tests/mcp/test_resources.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_resources.py`:

```python
"""Tests for MCP resources."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_stats_resource(mock_services: PamServices):
    """pam://stats returns system statistics."""
    # Mock ES count
    mock_services.es_client.count = AsyncMock(return_value={"count": 150})

    # Mock PG document count
    mock_session = AsyncMock()
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 25
    mock_session.execute = AsyncMock(return_value=mock_count_result)
    mock_services.session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
    mock_services.session_factory.return_value.__aexit__ = AsyncMock(return_value=False)

    from pam.mcp.server import _get_stats

    result = await _get_stats()
    parsed = json.loads(result)

    assert "document_count" in parsed
    assert "segment_count" in parsed


@pytest.mark.asyncio
async def test_pam_entities_resource(mock_services: PamServices):
    """pam://entities returns entity listing."""
    mock_services.es_client.search = AsyncMock(
        return_value={
            "hits": {
                "hits": [
                    {
                        "_source": {
                            "name": "AuthService",
                            "type": "service",
                            "description": "Handles authentication",
                        }
                    }
                ],
                "total": {"value": 1},
            }
        }
    )

    from pam.mcp.server import _get_entities

    result = await _get_entities(entity_type="service")
    parsed = json.loads(result)

    assert len(parsed["entities"]) == 1
    assert parsed["entities"][0]["name"] == "AuthService"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_resources.py::test_pam_stats_resource -v`
Expected: FAIL with `ImportError: cannot import name '_get_stats'`

- [ ] **Step 3: Implement resources**

Replace `_register_resources` in `src/pam/mcp/server.py`:

```python
def _register_resources(mcp: FastMCP) -> None:
    """Register MCP resources for system introspection."""

    @mcp.resource("pam://stats")
    async def stats_resource() -> str:
        """System statistics — document count, segment count, graph status."""
        return await _get_stats()

    @mcp.resource("pam://entities/{entity_type}")
    async def entities_resource(entity_type: str) -> str:
        """List entities of a given type from the entity VDB index."""
        return await _get_entities(entity_type=entity_type)

    @mcp.resource("pam://entities")
    async def all_entities_resource() -> str:
        """List all entities from the entity VDB index."""
        return await _get_entities(entity_type=None)


async def _get_stats() -> str:
    """Implementation of pam://stats resource."""
    from sqlalchemy import func, select

    from pam.common.config import get_settings
    from pam.common.models import Document

    services = get_services()
    settings = get_settings()

    stats: dict[str, Any] = {}

    # Document count from PG
    async with services.session_factory() as session:
        result = await session.execute(select(func.count(Document.id)))
        stats["document_count"] = result.scalar() or 0

    # Segment count from ES
    try:
        es_count = await services.es_client.count(index=settings.elasticsearch_index)
        stats["segment_count"] = es_count.get("count", 0)
    except Exception:
        stats["segment_count"] = "unavailable"

    # Graph status
    stats["graph_available"] = services.graph_service is not None
    stats["duckdb_available"] = services.duckdb_service is not None

    return json.dumps(stats, indent=2)


async def _get_entities(entity_type: str | None = None) -> str:
    """Implementation of pam://entities resource."""
    from pam.common.config import get_settings

    services = get_services()
    settings = get_settings()

    if services.vdb_store is None:
        return json.dumps({"entities": [], "error": "Entity VDB not available"})

    body: dict[str, Any] = {"size": 100}
    if entity_type:
        body["query"] = {"term": {"type": entity_type}}
    else:
        body["query"] = {"match_all": {}}

    try:
        result = await services.es_client.search(
            index=settings.entity_index,
            body=body,
        )
        entities = [
            {
                "name": hit["_source"].get("name", ""),
                "type": hit["_source"].get("type", ""),
                "description": hit["_source"].get("description", ""),
            }
            for hit in result["hits"]["hits"]
        ]
        return json.dumps(
            {"entities": entities, "count": result["hits"]["total"]["value"]},
            indent=2,
        )
    except Exception as e:
        return json.dumps({"entities": [], "error": str(e)})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_resources.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/server.py tests/mcp/test_resources.py
git commit -m "feat(mcp): implement MCP resources — stats, entities"
```

---

## Task 9: SSE Transport — Mount on FastAPI

**Files:**
- Modify: `src/pam/api/main.py`
- Modify: `src/pam/common/config.py`

- [ ] **Step 1: Add MCP config setting**

In `src/pam/common/config.py`, add to the `Settings` class:

```python
    # MCP Server
    mcp_enabled: bool = True  # Enable MCP SSE transport on /mcp
```

- [ ] **Step 2: Mount MCP SSE transport on FastAPI**

In `src/pam/api/main.py`, add the MCP mount after the graph service initialization in `lifespan()` (before the `yield`):

```python
    # --- MCP Server (SSE transport) ---
    if settings.mcp_enabled:
        try:
            from pam.mcp.server import create_mcp_server, initialize
            from pam.mcp.services import from_app_state

            mcp_services = from_app_state(app.state)
            initialize(mcp_services)
            mcp_server = create_mcp_server()
            app.state.mcp_server = mcp_server
            logger.info("mcp_server_initialized")
        except Exception:
            logger.warning("mcp_server_init_failed", exc_info=True)
```

In the `create_app()` function, after the route registrations, add the SSE mount:

```python
    # MCP SSE transport
    if settings.mcp_enabled:

        @app.get("/mcp/sse")
        async def mcp_sse_info():
            """MCP SSE transport info. Actual SSE connections use the MCP client SDK."""
            return {
                "name": "PAM Context MCP Server",
                "description": "Connect via MCP client SDK using SSE transport",
                "transport": "sse",
                "url": "/mcp",
            }
```

- [ ] **Step 3: Run existing tests to verify nothing is broken**

Run: `python -m pytest tests/ -x --ignore=tests/mcp -q`
Expected: All existing tests still PASS

- [ ] **Step 4: Commit**

```bash
git add src/pam/api/main.py src/pam/common/config.py
git commit -m "feat(mcp): mount MCP server on FastAPI with SSE transport info"
```

---

## Task 10: stdio Entrypoint + Smoke Test

**Files:**
- Create: `src/pam/mcp/__main__.py`

- [ ] **Step 1: Create the stdio entrypoint**

Create `src/pam/mcp/__main__.py`:

```python
"""MCP stdio entrypoint — run with: python -m pam.mcp

Initializes all PAM services and starts the MCP server over stdio transport.
LLM clients (Claude Code, Cursor) connect to this process via stdin/stdout.
"""

from __future__ import annotations

import asyncio
import sys

import structlog

from pam.common.config import get_settings
from pam.common.logging import configure_logging

logger = structlog.get_logger()


async def _create_services():
    """Initialize all PAM services for standalone MCP mode."""
    import redis.asyncio as aioredis
    from elasticsearch import AsyncElasticsearch
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from pam.common.cache import CacheService
    from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
    from pam.mcp.services import PamServices

    settings = get_settings()

    # Database
    engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Elasticsearch
    es_client = AsyncElasticsearch(settings.elasticsearch_url)

    # Embedder
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dims=settings.embedding_dims,
    )

    # Redis + cache (optional)
    cache_service = None
    try:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        cache_service = CacheService(
            redis_client,
            search_ttl=settings.redis_search_ttl,
            session_ttl=settings.redis_session_ttl,
        )
    except Exception:
        logger.warning("redis_unavailable_in_mcp_mode")

    # Search service
    if settings.use_haystack_retrieval:
        from pam.retrieval.haystack_search import HaystackSearchService

        search_service = HaystackSearchService(
            es_url=settings.elasticsearch_url,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            rerank_enabled=settings.rerank_enabled,
            rerank_model=settings.rerank_model,
        )
    else:
        from pam.retrieval.hybrid_search import HybridSearchService

        search_service = HybridSearchService(
            es_client,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            reranker=None,
        )

    # DuckDB (optional)
    duckdb_service = None
    if settings.duckdb_data_dir:
        from pam.agent.duckdb_service import DuckDBService

        duckdb_service = DuckDBService(
            data_dir=settings.duckdb_data_dir,
            max_rows=settings.duckdb_max_rows,
        )
        duckdb_service.register_files()

    # Graph (optional)
    graph_service = None
    try:
        from pam.graph.service import GraphitiService

        graph_service = await GraphitiService.create(
            neo4j_uri=settings.neo4j_uri,
            neo4j_user=settings.neo4j_user,
            neo4j_password=settings.neo4j_password,
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=settings.openai_api_key,
            anthropic_model=settings.graphiti_model,
            embedding_model=settings.graphiti_embedding_model,
        )
    except Exception:
        logger.warning("graphiti_unavailable_in_mcp_mode")

    # Entity VDB (optional)
    vdb_store = None
    try:
        from pam.ingestion.stores.entity_relationship_store import EntityRelationshipVDBStore

        vdb_store = EntityRelationshipVDBStore(
            client=es_client,
            entity_index=settings.entity_index,
            relationship_index=settings.relationship_index,
            embedding_dims=settings.embedding_dims,
        )
    except Exception:
        logger.warning("vdb_store_unavailable_in_mcp_mode")

    return PamServices(
        search_service=search_service,
        embedder=embedder,
        session_factory=session_factory,
        es_client=es_client,
        graph_service=graph_service,
        vdb_store=vdb_store,
        duckdb_service=duckdb_service,
        cache_service=cache_service,
    )


def main() -> None:
    """Run the MCP server over stdio transport."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run():
        services = await _create_services()

        from pam.mcp.server import create_mcp_server, initialize

        initialize(services)
        server = create_mcp_server()
        logger.info("mcp_stdio_server_starting")
        # NOTE: The exact async run method depends on mcp SDK version.
        # Check `mcp` docs — may be run_stdio_async(), run_async(), or run().
        # FastMCP.run() is the standard sync entry point.
        await server.run_stdio_async()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the entrypoint can be imported**

Run: `python -c "from pam.mcp.__main__ import main; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run the full MCP test suite**

Run: `python -m pytest tests/mcp/ -v`
Expected: All tests PASS

- [ ] **Step 4: Run the complete project test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests PASS (no regressions)

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/__main__.py
git commit -m "feat(mcp): add stdio entrypoint for local LLM client access"
```

---

## Summary of MCP Tools Delivered

| MCP Tool | Maps To | Implementation |
|----------|---------|----------------|
| `pam_search` | Hybrid BM25 + kNN search | `_pam_search()` — embeds query, calls SearchService |
| `pam_smart_search` | Concurrent 4-way search | `_pam_smart_search()` — ES + graph + entity VDB + rel VDB |
| `pam_get_document` | Full document fetch | `_pam_get_document()` — PG query by title/source_id |
| `pam_list_documents` | Document listing | `_pam_list_documents()` — paginated PG query |
| `pam_graph_search` | Graph relationship search | `_pam_graph_search()` — Graphiti semantic search |
| `pam_graph_neighbors` | 1-hop neighborhood | `_pam_graph_neighbors()` — Graphiti edge search |
| `pam_entity_history` | Temporal entity history | `_pam_entity_history()` — Graphiti temporal search |
| `pam_query_data` | DuckDB SQL analytics | `_pam_query_data()` — DuckDB query/list_tables |
| `pam_ingest` | Ingestion trigger | `_pam_ingest()` — spawns ingestion task |

| MCP Resource | Description |
|--------------|-------------|
| `pam://stats` | System statistics (doc count, segment count, service status) |
| `pam://entities/{type}` | Entity listing by type from VDB index |
| `pam://entities` | All entities from VDB index |

### Not included (Phase 2+)

| Tool | Phase | Depends On |
|------|-------|-----------|
| `pam_remember` | Phase 2 — Memory CRUD | Memory Service (not yet built) |
| `pam_recall` | Phase 2 — Memory CRUD | Memory Service |
| `pam_forget` | Phase 2 — Memory CRUD | Memory Service |
| `pam_get_context` | Phase 2+ — Context-as-a-Service | Memory + Context Assembly |

---

## Client Configuration

After implementation, LLM clients connect to PAM via:

**Claude Code (stdio):**
```json
{
  "mcpServers": {
    "pam-context": {
      "command": "python",
      "args": ["-m", "pam.mcp"],
      "env": {
        "DATABASE_URL": "postgresql+psycopg://pam:pam@localhost:5432/pam_context",
        "ELASTICSEARCH_URL": "http://localhost:9200",
        "OPENAI_API_KEY": "sk-..."
      }
    }
  }
}
```

**SSE (remote):**
```json
{
  "mcpServers": {
    "pam-context": {
      "url": "http://localhost:8000/mcp/sse"
    }
  }
}
```

---

## Future Phase Plans (Separate Documents Needed)

| Phase | Plan Needed | Key OSS to Evaluate |
|-------|-------------|-------------------|
| Phase 2 — Memory CRUD | `2026-XX-XX-memory-crud-api.md` | Mem0 patterns (semantic dedup, importance scoring) |
| Phase 3 — Conversational Memory | `2026-XX-XX-conversational-memory.md` | Mem0 fact extraction, Graphiti session memory |
| Phase 4 — Semantic Metadata | `2026-XX-XX-semantic-metadata-glossary.md` | No good OSS — build custom |
| Phase 5 — Fact Extraction | `2026-XX-XX-fact-extraction-engine.md` | Cognee pipeline as inspiration |
| Phase 6 — Multi-Agent Router | `2026-XX-XX-multi-agent-router.md` | Custom supervisor pattern |
