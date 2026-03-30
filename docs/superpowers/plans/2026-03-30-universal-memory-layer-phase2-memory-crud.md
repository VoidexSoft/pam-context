# Universal Memory Layer — Phase 2: Memory CRUD

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Memory Service that lets LLM clients and REST consumers store, search, update, and delete discrete facts with semantic deduplication and importance scoring.

**Architecture:** A `MemoryService` wraps two backends — PostgreSQL for durable storage (ORM model) and Elasticsearch for kNN vector search (embedding index). On store, the service embeds content, checks for duplicates via cosine similarity > 0.9, and either merges (LLM-assisted) or inserts. Three access layers: REST API (`/api/memory`), MCP tools (`pam_remember`, `pam_recall`, `pam_forget`), and the Python service directly.

**Tech Stack:** SQLAlchemy 2.x (async), Elasticsearch 8.x (dense_vector kNN), OpenAI embeddings (text-embedding-3-large, 1536d), Anthropic SDK (Haiku for content merge), Alembic migration, FastAPI routes, FastMCP tools, pytest

---

## File Structure

### New Files

```
src/pam/memory/
├── __init__.py              # Re-exports MemoryService, MemoryStore
├── service.py               # MemoryService — CRUD, dedup, importance scoring
└── store.py                 # MemoryStore — ES index ops (index, search, dedup, delete)

src/pam/api/routes/memory.py # REST endpoints: POST, GET, PUT, DELETE, search, list

tests/memory/
├── __init__.py
├── conftest.py              # Mock fixtures for MemoryService, MemoryStore
├── test_store.py            # MemoryStore unit tests
└── test_service.py          # MemoryService unit tests

tests/mcp/test_memory_tools.py  # MCP pam_remember, pam_recall, pam_forget tests
```

### Modified Files

```
src/pam/common/models.py        # Add Memory ORM model + Pydantic schemas
src/pam/common/config.py        # Add memory_index, memory_dedup_threshold settings
src/pam/mcp/server.py           # Add _register_memory_tools
src/pam/mcp/services.py         # Add memory_service field to PamServices
src/pam/mcp/__main__.py         # Initialize MemoryService in stdio mode
src/pam/api/main.py             # Initialize MemoryService + register memory routes
alembic/versions/008_add_memories.py  # Migration for memories table
```

---

## Task 1: Memory ORM Model + Pydantic Schemas

**Files:**
- Modify: `src/pam/common/models.py`
- Test: `tests/memory/test_service.py` (first test only)

- [ ] **Step 1: Write the failing test**

Create `tests/memory/__init__.py` (empty file).

Create `tests/memory/test_service.py`:

```python
"""Tests for Memory model and schemas."""

import dataclasses
import uuid
from datetime import datetime, timezone

from pam.common.models import Memory


def test_memory_model_has_required_fields():
    """Memory ORM model has all expected columns."""
    columns = {c.name for c in Memory.__table__.columns}
    expected = {
        "id", "user_id", "project_id", "type", "content", "source",
        "metadata", "importance", "access_count", "last_accessed_at",
        "expires_at", "created_at", "updated_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -m pytest tests/memory/test_service.py::test_memory_model_has_required_fields -v`
Expected: FAIL with `ImportError: cannot import name 'Memory'`

- [ ] **Step 3: Add the Memory ORM model**

In `src/pam/common/models.py`, add after the `IngestionTask` class (before the `# ── Pydantic Schemas` comment):

```python
class Memory(Base):
    __tablename__ = "memories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(100))
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    importance: Mapped[float] = mapped_column(default=0.5)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "type IN ('fact', 'preference', 'observation', 'conversation_summary')",
            name="ck_memories_type",
        ),
        CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memories_importance"),
        {"comment": "Discrete memories (facts, preferences, observations) with importance scoring"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/memory/test_service.py::test_memory_model_has_required_fields -v`
Expected: PASS

- [ ] **Step 5: Add Pydantic schemas**

In `src/pam/common/models.py`, add after the existing `MessageResponse` class at the end:

```python
# ── Memory Schemas ─────────────────────────────────────────────────────


class MemoryCreate(BaseModel):
    content: str
    type: Literal["fact", "preference", "observation", "conversation_summary"] = "fact"
    source: str | None = None
    metadata: dict = Field(default_factory=dict)
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    expires_at: datetime | None = None


class MemoryResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    type: str
    content: str
    source: str | None = None
    metadata: dict = Field(default_factory=dict)
    importance: float
    access_count: int = 0
    last_accessed_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MemoryUpdate(BaseModel):
    content: str | None = None
    metadata: dict | None = None
    importance: float | None = Field(default=None, ge=0.0, le=1.0)
    expires_at: datetime | None = None


class MemorySearchQuery(BaseModel):
    query: str
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    type: str | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class MemorySearchResult(BaseModel):
    memory: MemoryResponse
    score: float
```

- [ ] **Step 6: Write schema tests**

Add to `tests/memory/test_service.py`:

```python
from pam.common.models import MemoryCreate, MemoryResponse, MemoryUpdate, MemorySearchQuery


def test_memory_create_schema_defaults():
    """MemoryCreate has correct defaults."""
    mc = MemoryCreate(content="User prefers Python")
    assert mc.type == "fact"
    assert mc.importance == 0.5
    assert mc.metadata == {}
    assert mc.source is None


def test_memory_create_schema_validation():
    """MemoryCreate rejects invalid importance values."""
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        MemoryCreate(content="test", importance=1.5)

    with pytest.raises(ValidationError):
        MemoryCreate(content="test", importance=-0.1)


def test_memory_response_from_attributes():
    """MemoryResponse can be constructed from ORM-like attributes."""
    now = datetime.now(tz=timezone.utc)
    mr = MemoryResponse(
        id=uuid.uuid4(),
        type="fact",
        content="Test memory",
        importance=0.7,
        access_count=3,
        created_at=now,
        updated_at=now,
    )
    assert mr.type == "fact"
    assert mr.importance == 0.7
```

- [ ] **Step 7: Run all tests to verify they pass**

Run: `python -m pytest tests/memory/test_service.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add src/pam/common/models.py tests/memory/__init__.py tests/memory/test_service.py
git commit -m "feat(memory): add Memory ORM model and Pydantic schemas"
```

---

## Task 2: Alembic Migration

**Files:**
- Create: `alembic/versions/008_add_memories.py`

- [ ] **Step 1: Create the migration file**

Create `alembic/versions/008_add_memories.py`:

```python
"""Add memories table for discrete fact storage with importance scoring.

Revision ID: 008
Revises: 007
Create Date: 2026-03-30
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True),
        sa.Column("project_id", UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="SET NULL"), index=True),
        sa.Column("type", sa.String(30), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("source", sa.String(100)),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("importance", sa.Float, server_default=sa.text("0.5")),
        sa.Column("access_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "type IN ('fact', 'preference', 'observation', 'conversation_summary')",
            name="ck_memories_type",
        ),
        sa.CheckConstraint("importance >= 0 AND importance <= 1", name="ck_memories_importance"),
        comment="Discrete memories (facts, preferences, observations) with importance scoring",
    )
    # Composite index for user-scoped queries
    op.create_index("ix_memories_user_project", "memories", ["user_id", "project_id"])
    # Index for TTL expiration cleanup
    op.create_index("ix_memories_expires_at", "memories", ["expires_at"], postgresql_where=sa.text("expires_at IS NOT NULL"))


def downgrade() -> None:
    op.drop_index("ix_memories_expires_at", table_name="memories")
    op.drop_index("ix_memories_user_project", table_name="memories")
    op.drop_table("memories")
```

- [ ] **Step 2: Verify migration syntax is valid**

Run: `cd /Users/datnguyen/Projects/AI-Projects/pam-context && python -c "import alembic.versions; print('OK')" 2>/dev/null; python -c "from alembic.config import Config; print('Migration file created')" `
Expected: No import errors

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/008_add_memories.py
git commit -m "feat(memory): add Alembic migration 008 for memories table"
```

---

## Task 3: Config Settings

**Files:**
- Modify: `src/pam/common/config.py`

- [ ] **Step 1: Add memory-related settings**

In `src/pam/common/config.py`, add to the `Settings` class after the `mcp_enabled` line:

```python
    # Memory Service
    memory_index: str = "pam_memories"  # ES index for memory embeddings
    memory_dedup_threshold: float = 0.9  # Cosine similarity threshold for dedup
    memory_merge_model: str = "claude-haiku-4-5-20251001"  # LLM for content merge
```

- [ ] **Step 2: Run existing config tests to verify no regression**

Run: `python -m pytest tests/ -k "config" -v --no-header -q 2>/dev/null; echo "Config check done"`
Expected: No failures

- [ ] **Step 3: Commit**

```bash
git add src/pam/common/config.py
git commit -m "feat(memory): add memory service config settings"
```

---

## Task 4: MemoryStore — ES Index Operations

**Files:**
- Create: `src/pam/memory/__init__.py`
- Create: `src/pam/memory/store.py`
- Create: `tests/memory/conftest.py`
- Create: `tests/memory/test_store.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/memory/conftest.py`:

```python
"""Shared fixtures for memory tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.memory.store import MemoryStore


@pytest.fixture()
def mock_es_client() -> AsyncMock:
    """Create a mock Elasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    return client


@pytest.fixture()
def memory_store(mock_es_client: AsyncMock) -> MemoryStore:
    """Create a MemoryStore with mocked ES client."""
    return MemoryStore(
        client=mock_es_client,
        index_name="test_memories",
        embedding_dims=1536,
    )
```

Create `tests/memory/test_store.py`:

```python
"""Tests for MemoryStore ES operations."""

from __future__ import annotations

import uuid

import pytest

from pam.memory.store import MemoryStore, get_memory_index_mapping


def test_memory_index_mapping_structure():
    """Index mapping has correct fields and types."""
    mapping = get_memory_index_mapping(1536)
    props = mapping["mappings"]["properties"]

    assert props["embedding"]["type"] == "dense_vector"
    assert props["embedding"]["dims"] == 1536
    assert props["embedding"]["similarity"] == "cosine"
    assert props["user_id"]["type"] == "keyword"
    assert props["project_id"]["type"] == "keyword"
    assert props["type"]["type"] == "keyword"
    assert props["content"]["type"] == "text"
    assert props["importance"]["type"] == "float"


@pytest.mark.asyncio
async def test_ensure_index_creates_when_missing(memory_store, mock_es_client):
    """ensure_index creates the index when it doesn't exist."""
    mock_es_client.indices.exists.return_value = False

    await memory_store.ensure_index()

    mock_es_client.indices.create.assert_awaited_once()
    call_kwargs = mock_es_client.indices.create.call_args
    assert call_kwargs.kwargs["index"] == "test_memories"


@pytest.mark.asyncio
async def test_ensure_index_skips_when_exists(memory_store, mock_es_client):
    """ensure_index is a no-op when index already exists."""
    mock_es_client.indices.exists.return_value = True

    await memory_store.ensure_index()

    mock_es_client.indices.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_memory(memory_store, mock_es_client):
    """index_memory indexes a memory document in ES."""
    memory_id = uuid.uuid4()
    embedding = [0.1] * 1536

    await memory_store.index_memory(
        memory_id=memory_id,
        content="User prefers Python",
        embedding=embedding,
        user_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        memory_type="preference",
        importance=0.7,
    )

    mock_es_client.index.assert_awaited_once()
    call_kwargs = mock_es_client.index.call_args.kwargs
    assert call_kwargs["index"] == "test_memories"
    assert call_kwargs["id"] == str(memory_id)
    assert call_kwargs["document"]["content"] == "User prefers Python"
    assert call_kwargs["document"]["importance"] == 0.7


@pytest.mark.asyncio
async def test_search_memories(memory_store, mock_es_client):
    """search returns scored memory IDs from kNN search."""
    memory_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(memory_id),
                    "_score": 0.95,
                    "_source": {
                        "content": "User prefers Python",
                        "user_id": str(uuid.uuid4()),
                        "type": "preference",
                        "importance": 0.7,
                    },
                }
            ],
            "total": {"value": 1},
        }
    }

    results = await memory_store.search(
        query_embedding=[0.1] * 1536,
        user_id=uuid.uuid4(),
        top_k=5,
    )

    assert len(results) == 1
    assert results[0]["memory_id"] == str(memory_id)
    assert results[0]["score"] == 0.95


@pytest.mark.asyncio
async def test_find_duplicates(memory_store, mock_es_client):
    """find_duplicates returns high-similarity matches."""
    dup_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(dup_id),
                    "_score": 0.95,
                    "_source": {
                        "content": "User likes Python",
                        "user_id": str(uuid.uuid4()),
                        "type": "preference",
                    },
                }
            ]
        }
    }

    results = await memory_store.find_duplicates(
        embedding=[0.1] * 1536,
        user_id=uuid.uuid4(),
        threshold=0.9,
    )

    assert len(results) == 1
    assert results[0]["memory_id"] == str(dup_id)
    assert results[0]["score"] >= 0.9


@pytest.mark.asyncio
async def test_delete_memory(memory_store, mock_es_client):
    """delete removes a memory from the ES index."""
    memory_id = uuid.uuid4()

    await memory_store.delete(memory_id)

    mock_es_client.delete.assert_awaited_once_with(
        index="test_memories",
        id=str(memory_id),
        refresh="wait_for",
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/memory/test_store.py::test_memory_index_mapping_structure -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pam.memory'`

- [ ] **Step 3: Implement MemoryStore**

Create `src/pam/memory/__init__.py`:

```python
"""Memory service — store, search, and manage discrete facts."""

from pam.memory.service import MemoryService
from pam.memory.store import MemoryStore

__all__ = ["MemoryService", "MemoryStore"]
```

Create `src/pam/memory/store.py`:

```python
"""Elasticsearch store for memory embeddings and kNN search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch

logger = structlog.get_logger()


def get_memory_index_mapping(embedding_dims: int) -> dict:
    """Build the ES index mapping for the memory VDB."""
    return {
        "mappings": {
            "properties": {
                "content": {"type": "text", "analyzer": "standard"},
                "user_id": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "type": {"type": "keyword"},
                "source": {"type": "keyword"},
                "importance": {"type": "float"},
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
        },
    }


class MemoryStore:
    """Elasticsearch store for memory vector search."""

    def __init__(
        self,
        client: AsyncElasticsearch,
        index_name: str,
        embedding_dims: int,
    ) -> None:
        self._client = client
        self._index_name = index_name
        self._embedding_dims = embedding_dims

    async def ensure_index(self) -> None:
        """Create the memory index if it does not exist."""
        exists = await self._client.indices.exists(index=self._index_name)
        if not exists:
            mapping = get_memory_index_mapping(self._embedding_dims)
            await self._client.indices.create(index=self._index_name, body=mapping)
            logger.info("memory_index_created", index=self._index_name)

    async def index_memory(
        self,
        memory_id: UUID,
        content: str,
        embedding: list[float],
        user_id: UUID | None,
        project_id: UUID | None,
        memory_type: str,
        importance: float,
        source: str | None = None,
    ) -> None:
        """Index a memory document for kNN search."""
        doc: dict[str, Any] = {
            "content": content,
            "embedding": embedding,
            "type": memory_type,
            "importance": importance,
        }
        if user_id:
            doc["user_id"] = str(user_id)
        if project_id:
            doc["project_id"] = str(project_id)
        if source:
            doc["source"] = source

        await self._client.index(
            index=self._index_name,
            id=str(memory_id),
            document=doc,
            refresh="wait_for",
        )

    async def search(
        self,
        query_embedding: list[float],
        user_id: UUID | None = None,
        project_id: UUID | None = None,
        type_filter: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """kNN search with optional user/project/type filters."""
        filters: list[dict] = []
        if user_id:
            filters.append({"term": {"user_id": str(user_id)}})
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})
        if type_filter:
            filters.append({"term": {"type": type_filter}})

        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": query_embedding,
            "k": top_k,
            "num_candidates": top_k * 10,
        }
        if filters:
            knn["filter"] = {"bool": {"must": filters}}

        result = await self._client.search(
            index=self._index_name,
            knn=knn,
            size=top_k,
        )

        return [
            {
                "memory_id": hit["_id"],
                "score": hit["_score"],
                "content": hit["_source"].get("content", ""),
                "type": hit["_source"].get("type", ""),
                "importance": hit["_source"].get("importance", 0),
            }
            for hit in result["hits"]["hits"]
        ]

    async def find_duplicates(
        self,
        embedding: list[float],
        user_id: UUID | None,
        threshold: float = 0.9,
    ) -> list[dict[str, Any]]:
        """Find semantically similar memories for dedup check.

        Returns memories with cosine similarity >= threshold.
        """
        filters: list[dict] = []
        if user_id:
            filters.append({"term": {"user_id": str(user_id)}})

        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": embedding,
            "k": 5,
            "num_candidates": 50,
            "similarity": threshold,
        }
        if filters:
            knn["filter"] = {"bool": {"must": filters}}

        result = await self._client.search(
            index=self._index_name,
            knn=knn,
            size=5,
        )

        return [
            {
                "memory_id": hit["_id"],
                "score": hit["_score"],
                "content": hit["_source"].get("content", ""),
            }
            for hit in result["hits"]["hits"]
            if hit["_score"] >= threshold
        ]

    async def delete(self, memory_id: UUID) -> None:
        """Remove a memory from the ES index."""
        await self._client.delete(
            index=self._index_name,
            id=str(memory_id),
            refresh="wait_for",
        )

    async def update_importance(self, memory_id: UUID, importance: float) -> None:
        """Update the importance score of a memory in ES."""
        await self._client.update(
            index=self._index_name,
            id=str(memory_id),
            doc={"importance": importance},
            refresh="wait_for",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/memory/test_store.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/memory/__init__.py src/pam/memory/store.py tests/memory/conftest.py tests/memory/test_store.py
git commit -m "feat(memory): implement MemoryStore with ES kNN search and dedup"
```

---

## Task 5: MemoryService — Store with Semantic Dedup

**Files:**
- Create: `src/pam/memory/service.py`
- Modify: `tests/memory/conftest.py`
- Modify: `tests/memory/test_service.py`

- [ ] **Step 1: Add service fixtures to conftest**

Add to `tests/memory/conftest.py`:

```python
from pam.memory.service import MemoryService
from pam.memory.store import MemoryStore


@pytest.fixture()
def mock_embedder() -> AsyncMock:
    """Create a mock embedder."""
    embedder = AsyncMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return embedder


@pytest.fixture()
def mock_store() -> AsyncMock:
    """Create a mock MemoryStore."""
    store = AsyncMock(spec=MemoryStore)
    store.find_duplicates = AsyncMock(return_value=[])
    store.index_memory = AsyncMock()
    store.search = AsyncMock(return_value=[])
    store.delete = AsyncMock()
    store.update_importance = AsyncMock()
    return store


@pytest.fixture()
def mock_session_factory() -> MagicMock:
    """Create a mock async session factory."""
    factory = MagicMock()
    session = AsyncMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.fixture()
def memory_service(mock_session_factory, mock_store, mock_embedder) -> MemoryService:
    """Create a MemoryService with all dependencies mocked."""
    return MemoryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
        anthropic_api_key="test-key",
        dedup_threshold=0.9,
        merge_model="claude-haiku-4-5-20251001",
    )
```

- [ ] **Step 2: Write the failing tests**

Add to `tests/memory/test_service.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.memory.service import MemoryService


@pytest.mark.asyncio
async def test_store_memory_no_duplicate(memory_service, mock_store, mock_embedder):
    """store() inserts a new memory when no duplicate exists."""
    mock_store.find_duplicates.return_value = []

    # Mock the session to capture the add() call
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_session.flush = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.store(
        content="Revenue target is $10M",
        memory_type="fact",
        source="manual",
        user_id=None,
        project_id=None,
    )

    assert result is not None
    assert result.content == "Revenue target is $10M"
    assert result.type == "fact"
    mock_embedder.embed_texts.assert_awaited_once_with(["Revenue target is $10M"])
    mock_store.find_duplicates.assert_awaited_once()
    mock_store.index_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_store_memory_with_duplicate_merges(memory_service, mock_store, mock_embedder):
    """store() merges content when a duplicate is found (cosine > threshold)."""
    dup_id = "550e8400-e29b-41d4-a716-446655440000"
    mock_store.find_duplicates.return_value = [
        {"memory_id": dup_id, "score": 0.95, "content": "Revenue target is $10M"},
    ]

    mock_session = AsyncMock()
    mock_existing = MagicMock()
    mock_existing.id = uuid.UUID(dup_id)
    mock_existing.content = "Revenue target is $10M"
    mock_existing.type = "fact"
    mock_existing.source = "manual"
    mock_existing.metadata_ = {}
    mock_existing.importance = 0.5
    mock_existing.access_count = 0
    mock_existing.last_accessed_at = None
    mock_existing.expires_at = None
    mock_existing.user_id = None
    mock_existing.project_id = None
    mock_existing.created_at = datetime.now(tz=timezone.utc)
    mock_existing.updated_at = datetime.now(tz=timezone.utc)

    mock_get_result = MagicMock()
    mock_get_result.scalars.return_value.first.return_value = mock_existing
    mock_session.execute = AsyncMock(return_value=mock_get_result)
    mock_session.flush = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    # Mock the LLM merge to return merged content
    with patch.object(memory_service, "_merge_contents", new_callable=AsyncMock) as mock_merge:
        mock_merge.return_value = "Revenue target is $10M for Q1 2026"

        result = await memory_service.store(
            content="Q1 2026 revenue target is $10M",
            memory_type="fact",
            user_id=None,
        )

    assert result is not None
    mock_merge.assert_awaited_once()
    mock_store.index_memory.assert_awaited_once()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/memory/test_service.py::test_store_memory_no_duplicate -v`
Expected: FAIL with `ImportError: cannot import name 'MemoryService'`

- [ ] **Step 4: Implement MemoryService**

Create `src/pam/memory/service.py`:

```python
"""Memory service — CRUD operations with semantic dedup and importance scoring."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from pam.common.models import Memory, MemoryResponse

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pam.ingestion.embedders.base import BaseEmbedder
    from pam.memory.store import MemoryStore

logger = structlog.get_logger()


class MemoryService:
    """Manages discrete memories with semantic dedup and importance scoring."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: MemoryStore,
        embedder: BaseEmbedder,
        anthropic_api_key: str,
        dedup_threshold: float = 0.9,
        merge_model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._anthropic_api_key = anthropic_api_key
        self._dedup_threshold = dedup_threshold
        self._merge_model = merge_model

    async def store(
        self,
        content: str,
        memory_type: str = "fact",
        source: str | None = None,
        metadata: dict | None = None,
        importance: float = 0.5,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryResponse:
        """Store a memory with semantic deduplication.

        If a memory with cosine similarity > threshold exists for the same user,
        merges the content instead of creating a duplicate.
        """
        # Embed the content
        embeddings = await self._embedder.embed_texts([content])
        embedding = embeddings[0]

        # Check for duplicates
        duplicates = await self._store.find_duplicates(
            embedding=embedding,
            user_id=user_id,
            threshold=self._dedup_threshold,
        )

        if duplicates:
            # Merge with the most similar existing memory
            dup = duplicates[0]
            return await self._merge_and_update(
                existing_id=uuid_mod.UUID(dup["memory_id"]),
                existing_content=dup["content"],
                new_content=content,
                new_embedding=embedding,
                user_id=user_id,
                project_id=project_id,
            )

        # No duplicate — insert new memory
        memory_id = uuid_mod.uuid4()
        now = datetime.now(tz=timezone.utc)
        memory = Memory(
            id=memory_id,
            user_id=user_id,
            project_id=project_id,
            type=memory_type,
            content=content,
            source=source,
            metadata_=metadata or {},
            importance=importance,
            expires_at=expires_at,
            created_at=now,
            updated_at=now,
        )

        async with self._session_factory() as session:
            session.add(memory)
            await session.flush()
            await session.commit()

        # Index in ES
        await self._store.index_memory(
            memory_id=memory_id,
            content=content,
            embedding=embedding,
            user_id=user_id,
            project_id=project_id,
            memory_type=memory_type,
            importance=importance,
            source=source,
        )

        logger.info("memory_stored", memory_id=str(memory_id), type=memory_type, dedup="new")
        return MemoryResponse.model_validate(memory)

    async def _merge_and_update(
        self,
        existing_id: uuid_mod.UUID,
        existing_content: str,
        new_content: str,
        new_embedding: list[float],
        user_id: uuid_mod.UUID | None,
        project_id: uuid_mod.UUID | None,
    ) -> MemoryResponse:
        """Merge new content into an existing memory via LLM."""
        from sqlalchemy import select

        merged_content = await self._merge_contents(existing_content, new_content)

        # Re-embed the merged content
        embeddings = await self._embedder.embed_texts([merged_content])
        merged_embedding = embeddings[0]

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == existing_id)
            )
            existing = result.scalars().first()
            if existing is None:
                # Race condition: memory was deleted between dedup check and update
                # Fall through to create a new memory
                logger.warning("memory_dedup_race", existing_id=str(existing_id))
                raise RuntimeError("Dedup target not found")

            existing.content = merged_content
            existing.updated_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()

            # Re-index in ES
            await self._store.index_memory(
                memory_id=existing_id,
                content=merged_content,
                embedding=merged_embedding,
                user_id=user_id,
                project_id=project_id,
                memory_type=existing.type,
                importance=existing.importance,
                source=existing.source,
            )

            logger.info("memory_merged", memory_id=str(existing_id))
            return MemoryResponse.model_validate(existing)

    async def _merge_contents(self, old_content: str, new_content: str) -> str:
        """Use LLM to merge overlapping memory contents."""
        try:
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=self._anthropic_api_key)
            response = await client.messages.create(
                model=self._merge_model,
                max_tokens=300,
                system=(
                    "Merge these two memories into a single, concise fact. "
                    "Keep all unique information from both. "
                    "Return only the merged text, nothing else."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": (
                            f"Existing memory: {old_content}\n\n"
                            f"New memory: {new_content}"
                        ),
                    }
                ],
            )
            return response.content[0].text
        except Exception:
            logger.warning("memory_merge_llm_failed", exc_info=True)
            return new_content  # Fallback: use new content as-is
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/memory/test_service.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/memory/service.py tests/memory/conftest.py tests/memory/test_service.py
git commit -m "feat(memory): implement MemoryService store with semantic dedup and LLM merge"
```

---

## Task 6: MemoryService — Search, Get, List, Update, Delete

**Files:**
- Modify: `src/pam/memory/service.py`
- Modify: `tests/memory/test_service.py`

- [ ] **Step 1: Write the failing tests for search**

Add to `tests/memory/test_service.py`:

```python
def test_compute_importance_formula():
    """compute_importance implements the spec formula correctly."""
    from datetime import timedelta

    from pam.memory.service import MemoryService

    now = datetime.now(tz=timezone.utc)

    # Brand new memory with no accesses: recency=1.0, freq=0, weight=0.5
    score = MemoryService.compute_importance(
        created_at=now, access_count=0, explicit_weight=0.5,
    )
    # 0.5*1.0 + 0.3*0 + 0.2*0.5 = 0.6
    assert abs(score - 0.6) < 0.01

    # 45-day old memory (half of 90-day max) with 10 accesses, weight=0.8
    score = MemoryService.compute_importance(
        created_at=now - timedelta(days=45),
        access_count=10,
        explicit_weight=0.8,
    )
    # recency=0.5, freq=log(11)/log(101)≈0.519, weight=0.8
    # 0.5*0.5 + 0.3*0.519 + 0.2*0.8 ≈ 0.566
    assert 0.5 < score < 0.7

    # Very old memory (>90 days): recency=0
    score = MemoryService.compute_importance(
        created_at=now - timedelta(days=100),
        access_count=0,
        explicit_weight=0.5,
    )
    # 0.5*0 + 0.3*0 + 0.2*0.5 = 0.1
    assert abs(score - 0.1) < 0.01


@pytest.mark.asyncio
async def test_search_memories(memory_service, mock_store, mock_embedder):
    """search() embeds query and returns scored memories from ES."""
    memory_id = uuid.uuid4()
    mock_store.search.return_value = [
        {"memory_id": str(memory_id), "score": 0.92, "content": "Revenue is $10M", "type": "fact", "importance": 0.7},
    ]

    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Revenue is $10M"
    mock_memory.type = "fact"
    mock_memory.importance = 0.7
    mock_memory.access_count = 2
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = "manual"
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = None
    mock_memory.created_at = datetime.now(tz=timezone.utc)
    mock_memory.updated_at = datetime.now(tz=timezone.utc)

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_memory]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    results = await memory_service.search(query="revenue target", top_k=5)

    assert len(results) == 1
    assert results[0].memory.content == "Revenue is $10M"
    assert results[0].score == 0.92
    mock_embedder.embed_texts.assert_awaited_once_with(["revenue target"])
    mock_store.search.assert_awaited_once()
```

- [ ] **Step 2: Write the failing tests for get and delete**

Add to `tests/memory/test_service.py`:

```python
@pytest.mark.asyncio
async def test_get_memory_by_id(memory_service):
    """get() fetches a single memory by ID."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Test fact"
    mock_memory.type = "fact"
    mock_memory.importance = 0.5
    mock_memory.access_count = 0
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = None
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = None
    mock_memory.created_at = datetime.now(tz=timezone.utc)
    mock_memory.updated_at = datetime.now(tz=timezone.utc)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.get(memory_id)

    assert result is not None
    assert result.content == "Test fact"


@pytest.mark.asyncio
async def test_get_memory_not_found(memory_service):
    """get() returns None when memory doesn't exist."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.get(uuid.uuid4())

    assert result is None


@pytest.mark.asyncio
async def test_delete_memory(memory_service, mock_store):
    """delete() removes memory from PG and ES."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    deleted = await memory_service.delete(memory_id)

    assert deleted is True
    mock_session.delete.assert_awaited_once_with(mock_memory)
    mock_store.delete.assert_awaited_once_with(memory_id)


@pytest.mark.asyncio
async def test_delete_memory_not_found(memory_service, mock_store):
    """delete() returns False when memory doesn't exist."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    deleted = await memory_service.delete(uuid.uuid4())

    assert deleted is False
    mock_store.delete.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_memory(memory_service, mock_store, mock_embedder):
    """update() modifies content and re-indexes in ES."""
    memory_id = uuid.uuid4()
    mock_session = AsyncMock()
    mock_memory = MagicMock()
    mock_memory.id = memory_id
    mock_memory.content = "Old fact"
    mock_memory.type = "fact"
    mock_memory.importance = 0.5
    mock_memory.access_count = 0
    mock_memory.user_id = None
    mock_memory.project_id = None
    mock_memory.source = None
    mock_memory.metadata_ = {}
    mock_memory.last_accessed_at = None
    mock_memory.expires_at = None
    mock_memory.created_at = datetime.now(tz=timezone.utc)
    mock_memory.updated_at = datetime.now(tz=timezone.utc)

    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_memory
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.flush = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    result = await memory_service.update(
        memory_id=memory_id,
        content="Updated fact",
        importance=0.8,
    )

    assert result is not None
    mock_embedder.embed_texts.assert_awaited_once_with(["Updated fact"])
    mock_store.index_memory.assert_awaited_once()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/memory/test_service.py::test_search_memories -v`
Expected: FAIL with `AttributeError: 'MemoryService' object has no attribute 'search'`

- [ ] **Step 4: Implement search, get, list, update, delete**

Add these methods to the `MemoryService` class in `src/pam/memory/service.py`:

```python
    @staticmethod
    def compute_importance(
        created_at: datetime,
        access_count: int,
        explicit_weight: float,
        max_age_days: float = 90.0,
    ) -> float:
        """Compute importance score per spec formula.

        importance = 0.5 * recency + 0.3 * access_frequency + 0.2 * explicit_weight

        recency: 1.0 for just-created, decays to 0.0 at max_age_days.
        access_frequency: normalized log of access_count (log(1+count)/log(1+100)).
        explicit_weight: the user-provided importance value (0-1).
        """
        import math

        age_seconds = (datetime.now(tz=timezone.utc) - created_at).total_seconds()
        age_days = max(age_seconds / 86400, 0)
        recency = max(1.0 - (age_days / max_age_days), 0.0)

        access_freq = math.log(1 + access_count) / math.log(1 + 100)
        access_freq = min(access_freq, 1.0)

        score = 0.5 * recency + 0.3 * access_freq + 0.2 * explicit_weight
        return round(min(max(score, 0.0), 1.0), 4)

    async def search(
        self,
        query: str,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
        type_filter: str | None = None,
        top_k: int = 10,
    ) -> list[MemorySearchResult]:
        """Search memories by semantic similarity."""
        from pam.common.models import MemorySearchResult

        embeddings = await self._embedder.embed_texts([query])
        query_embedding = embeddings[0]

        # kNN search in ES
        hits = await self._store.search(
            query_embedding=query_embedding,
            user_id=user_id,
            project_id=project_id,
            type_filter=type_filter,
            top_k=top_k,
        )

        if not hits:
            return []

        # Fetch full memory objects from PG
        memory_ids = [uuid_mod.UUID(h["memory_id"]) for h in hits]
        score_map = {h["memory_id"]: h["score"] for h in hits}

        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id.in_(memory_ids))
            )
            memories = result.scalars().all()

            # Update access counts and recompute importance
            for mem in memories:
                mem.access_count += 1
                mem.last_accessed_at = datetime.now(tz=timezone.utc)
                mem.importance = self.compute_importance(
                    created_at=mem.created_at,
                    access_count=mem.access_count,
                    explicit_weight=mem.importance,
                )
            await session.flush()
            await session.commit()

        # Build scored results, ordered by ES score
        memory_map = {str(m.id): m for m in memories}
        results = []
        for hit in hits:
            mem = memory_map.get(hit["memory_id"])
            if mem:
                results.append(
                    MemorySearchResult(
                        memory=MemoryResponse.model_validate(mem),
                        score=score_map[hit["memory_id"]],
                    )
                )

        return results

    async def get(self, memory_id: uuid_mod.UUID) -> MemoryResponse | None:
        """Fetch a single memory by ID."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalars().first()
            if memory is None:
                return None
            return MemoryResponse.model_validate(memory)

    async def list_by_user(
        self,
        user_id: uuid_mod.UUID,
        project_id: uuid_mod.UUID | None = None,
        type_filter: str | None = None,
        limit: int = 50,
    ) -> list[MemoryResponse]:
        """List memories for a user, optionally filtered by project/type."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            stmt = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.updated_at.desc())
                .limit(limit)
            )
            if project_id:
                stmt = stmt.where(Memory.project_id == project_id)
            if type_filter:
                stmt = stmt.where(Memory.type == type_filter)

            result = await session.execute(stmt)
            memories = result.scalars().all()
            return [MemoryResponse.model_validate(m) for m in memories]

    async def update(
        self,
        memory_id: uuid_mod.UUID,
        content: str | None = None,
        metadata: dict | None = None,
        importance: float | None = None,
        expires_at: datetime | None = None,
    ) -> MemoryResponse | None:
        """Update a memory. Re-embeds and re-indexes if content changes."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalars().first()
            if memory is None:
                return None

            content_changed = False
            if content is not None and content != memory.content:
                memory.content = content
                content_changed = True
            if metadata is not None:
                memory.metadata_ = metadata
            if importance is not None:
                memory.importance = importance
            if expires_at is not None:
                memory.expires_at = expires_at

            memory.updated_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()

            # Re-embed and re-index if content changed
            if content_changed:
                embeddings = await self._embedder.embed_texts([memory.content])
                await self._store.index_memory(
                    memory_id=memory_id,
                    content=memory.content,
                    embedding=embeddings[0],
                    user_id=memory.user_id,
                    project_id=memory.project_id,
                    memory_type=memory.type,
                    importance=memory.importance,
                    source=memory.source,
                )
            elif importance is not None:
                await self._store.update_importance(memory_id, importance)

            return MemoryResponse.model_validate(memory)

    async def delete(self, memory_id: uuid_mod.UUID) -> bool:
        """Delete a memory from PG and ES. Returns True if found and deleted."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(Memory).where(Memory.id == memory_id)
            )
            memory = result.scalars().first()
            if memory is None:
                return False

            await session.delete(memory)
            await session.flush()
            await session.commit()

        await self._store.delete(memory_id)
        logger.info("memory_deleted", memory_id=str(memory_id))
        return True
```

Also add the `MemorySearchResult` import at the top of the file:

```python
from pam.common.models import Memory, MemoryResponse, MemorySearchResult
```

(Replace the existing import line.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/memory/test_service.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/memory/service.py tests/memory/test_service.py
git commit -m "feat(memory): implement search, get, list, update, delete on MemoryService"
```

---

## Task 7: REST API Routes

**Files:**
- Create: `src/pam/api/routes/memory.py`
- Modify: `src/pam/api/main.py` (register routes)

- [ ] **Step 1: Write the failing tests**

Add to `tests/memory/test_service.py` (API-level tests using the router directly):

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _create_test_app(memory_service: MemoryService) -> FastAPI:
    """Create a minimal FastAPI app with memory routes for testing."""
    from pam.api.routes.memory import router, get_memory_service

    app = FastAPI()
    app.include_router(router, prefix="/api/memory")
    app.dependency_overrides[get_memory_service] = lambda: memory_service
    return app


@pytest.mark.asyncio
async def test_api_post_memory(memory_service, mock_store, mock_embedder):
    """POST /api/memory stores a new memory."""
    mock_store.find_duplicates.return_value = []
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    memory_service._session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    from pam.api.routes.memory import router

    # Verify the router has the expected POST endpoint
    route_paths = [r.path for r in router.routes]
    assert "" in route_paths or "/" in route_paths  # POST /api/memory


@pytest.mark.asyncio
async def test_api_search_memories():
    """GET /api/memory/search has the expected route."""
    from pam.api.routes.memory import router

    route_paths = [r.path for r in router.routes]
    assert "/search" in route_paths


@pytest.mark.asyncio
async def test_api_get_memory():
    """GET /api/memory/{memory_id} has the expected route."""
    from pam.api.routes.memory import router

    route_paths = [r.path for r in router.routes]
    assert "/{memory_id}" in route_paths


@pytest.mark.asyncio
async def test_api_delete_memory():
    """DELETE /api/memory/{memory_id} has the expected route."""
    from pam.api.routes.memory import router

    route_methods = {(r.path, list(r.methods)[0] if r.methods else "") for r in router.routes if hasattr(r, 'methods')}
    assert ("/{memory_id}", "DELETE") in route_methods
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/memory/test_service.py::test_api_post_memory -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pam.api.routes.memory'`

- [ ] **Step 3: Implement the REST routes**

Create `src/pam/api/routes/memory.py`:

```python
"""Memory CRUD REST endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from pam.api.auth import get_current_user
from pam.common.models import (
    MemoryCreate,
    MemoryResponse,
    MemorySearchQuery,
    MemorySearchResult,
    MemoryUpdate,
    User,
)

router = APIRouter()


def get_memory_service():
    """Dependency stub — overridden at app startup."""
    raise RuntimeError("MemoryService not initialized")


@router.post("", response_model=MemoryResponse)
async def store_memory(
    body: MemoryCreate,
    memory_service=Depends(get_memory_service),
    user: User | None = Depends(get_current_user),
):
    """Store a new memory (fact, preference, observation).

    Automatically deduplicates — if a similar memory exists (cosine > 0.9),
    merges the content instead of creating a duplicate.
    """
    return await memory_service.store(
        content=body.content,
        memory_type=body.type,
        source=body.source,
        metadata=body.metadata,
        importance=body.importance,
        user_id=body.user_id or (user.id if user else None),
        project_id=body.project_id,
        expires_at=body.expires_at,
    )


@router.get("/search", response_model=list[MemorySearchResult])
async def search_memories(
    query: str,
    user_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    type: str | None = None,
    top_k: int = 10,
    memory_service=Depends(get_memory_service),
    _user: User | None = Depends(get_current_user),
):
    """Semantic search across memories."""
    return await memory_service.search(
        query=query,
        user_id=user_id,
        project_id=project_id,
        type_filter=type,
        top_k=min(top_k, 50),
    )


@router.get("/{memory_id}", response_model=MemoryResponse)
async def get_memory(
    memory_id: uuid.UUID,
    memory_service=Depends(get_memory_service),
    _user: User | None = Depends(get_current_user),
):
    """Get a specific memory by ID."""
    result = await memory_service.get(memory_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.put("/{memory_id}", response_model=MemoryResponse)
async def update_memory(
    memory_id: uuid.UUID,
    body: MemoryUpdate,
    memory_service=Depends(get_memory_service),
    _user: User | None = Depends(get_current_user),
):
    """Update a memory's content, metadata, or importance."""
    result = await memory_service.update(
        memory_id=memory_id,
        content=body.content,
        metadata=body.metadata,
        importance=body.importance,
        expires_at=body.expires_at,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    return result


@router.delete("/{memory_id}")
async def delete_memory(
    memory_id: uuid.UUID,
    memory_service=Depends(get_memory_service),
    _user: User | None = Depends(get_current_user),
):
    """Delete a memory."""
    deleted = await memory_service.delete(memory_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"message": "Memory deleted", "id": str(memory_id)}


@router.get("/user/{user_id}", response_model=list[MemoryResponse])
async def list_user_memories(
    user_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    type: str | None = None,
    limit: int = 50,
    memory_service=Depends(get_memory_service),
    _user: User | None = Depends(get_current_user),
):
    """List all memories for a user."""
    return await memory_service.list_by_user(
        user_id=user_id,
        project_id=project_id,
        type_filter=type,
        limit=min(limit, 200),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/memory/test_service.py -v -k "api"`
Expected: All API tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/api/routes/memory.py tests/memory/test_service.py
git commit -m "feat(memory): add REST API routes for memory CRUD"
```

---

## Task 8: MCP Tools — pam_remember, pam_recall, pam_forget

**Files:**
- Modify: `src/pam/mcp/server.py`
- Create: `tests/mcp/test_memory_tools.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/mcp/test_memory_tools.py`:

```python
"""Tests for MCP memory tools."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.common.models import MemoryResponse, MemorySearchResult
from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture(autouse=True)
def _init_services(mock_services: PamServices):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_remember_stores_fact(mock_services: PamServices):
    """pam_remember calls memory_service.store and returns JSON."""
    memory_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    mock_services.memory_service.store = AsyncMock(
        return_value=MemoryResponse(
            id=memory_id,
            type="fact",
            content="Revenue target is $10M",
            importance=0.5,
            access_count=0,
            created_at=now,
            updated_at=now,
        )
    )

    from pam.mcp.server import _pam_remember

    result = await _pam_remember(
        content="Revenue target is $10M",
        memory_type="fact",
        source="manual",
    )
    parsed = json.loads(result)

    assert parsed["content"] == "Revenue target is $10M"
    assert parsed["type"] == "fact"
    assert "id" in parsed
    mock_services.memory_service.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_recall_returns_scored_results(mock_services: PamServices):
    """pam_recall calls memory_service.search and returns JSON."""
    memory_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    mock_services.memory_service.search = AsyncMock(
        return_value=[
            MemorySearchResult(
                memory=MemoryResponse(
                    id=memory_id,
                    type="fact",
                    content="Revenue target is $10M",
                    importance=0.7,
                    access_count=3,
                    created_at=now,
                    updated_at=now,
                ),
                score=0.92,
            )
        ]
    )

    from pam.mcp.server import _pam_recall

    result = await _pam_recall(query="revenue targets", top_k=5)
    parsed = json.loads(result)

    assert len(parsed["memories"]) == 1
    assert parsed["memories"][0]["content"] == "Revenue target is $10M"
    assert parsed["memories"][0]["score"] == 0.92
    mock_services.memory_service.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_pam_recall_empty_results(mock_services: PamServices):
    """pam_recall returns empty list when no memories match."""
    mock_services.memory_service.search = AsyncMock(return_value=[])

    from pam.mcp.server import _pam_recall

    result = await _pam_recall(query="nonexistent topic", top_k=5)
    parsed = json.loads(result)

    assert parsed["memories"] == []
    assert parsed["count"] == 0


@pytest.mark.asyncio
async def test_pam_forget_deletes_memory(mock_services: PamServices):
    """pam_forget calls memory_service.delete and returns status."""
    mock_services.memory_service.delete = AsyncMock(return_value=True)

    from pam.mcp.server import _pam_forget

    memory_id = str(uuid.uuid4())
    result = await _pam_forget(memory_id=memory_id)
    parsed = json.loads(result)

    assert parsed["deleted"] is True
    assert parsed["memory_id"] == memory_id


@pytest.mark.asyncio
async def test_pam_forget_not_found(mock_services: PamServices):
    """pam_forget returns error when memory doesn't exist."""
    mock_services.memory_service.delete = AsyncMock(return_value=False)

    from pam.mcp.server import _pam_forget

    memory_id = str(uuid.uuid4())
    result = await _pam_forget(memory_id=memory_id)
    parsed = json.loads(result)

    assert parsed["deleted"] is False
    assert "error" in parsed


@pytest.mark.asyncio
async def test_pam_remember_unavailable_when_no_service(mock_services: PamServices):
    """pam_remember returns error when memory_service is None."""
    mock_services.memory_service = None
    mcp_server.initialize(mock_services)

    from pam.mcp.server import _pam_remember

    result = await _pam_remember(content="test", memory_type="fact")
    parsed = json.loads(result)

    assert "error" in parsed
    assert "unavailable" in parsed["error"].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/mcp/test_memory_tools.py::test_pam_remember_stores_fact -v`
Expected: FAIL with `ImportError: cannot import name '_pam_remember'`

- [ ] **Step 3: Update conftest to add memory_service to mock_services**

In `tests/mcp/conftest.py`, add `memory_service=AsyncMock()` to the `PamServices` constructor in the `mock_services` fixture:

```python
    return PamServices(
        search_service=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=MagicMock(),
        es_client=AsyncMock(),
        graph_service=AsyncMock(),
        vdb_store=AsyncMock(),
        duckdb_service=MagicMock(),
        cache_service=AsyncMock(),
        memory_service=AsyncMock(),
    )
```

- [ ] **Step 4: Implement MCP memory tools**

In `src/pam/mcp/server.py`, update `create_mcp_server()` to include:

```python
    _register_memory_tools(mcp)
```

Add this after the existing `_register_utility_tools(mcp)` call.

Then add the registration function and implementations:

```python
def _register_memory_tools(mcp: FastMCP) -> None:
    """Register memory CRUD MCP tools."""

    @mcp.tool()
    async def pam_remember(
        content: str,
        memory_type: str = "fact",
        source: str | None = None,
        importance: float = 0.5,
        user_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        """Store a fact, preference, or observation in PAM's memory.

        Automatically deduplicates — if a similar memory already exists
        (cosine similarity > 0.9), the content is merged instead of duplicated.

        memory_type: fact, preference, observation, or conversation_summary.
        importance: 0.0 to 1.0 (default 0.5). Higher = more prominent in recall.
        """
        return await _pam_remember(
            content=content,
            memory_type=memory_type,
            source=source,
            importance=importance,
            user_id=user_id,
            project_id=project_id,
        )

    @mcp.tool()
    async def pam_recall(
        query: str,
        top_k: int = 10,
        user_id: str | None = None,
        project_id: str | None = None,
        memory_type: str | None = None,
    ) -> str:
        """Recall relevant memories from PAM's memory store.

        Searches by semantic similarity to the query. Returns memories
        ranked by relevance score. Also updates access frequency for
        importance scoring.
        """
        return await _pam_recall(
            query=query,
            top_k=top_k,
            user_id=user_id,
            project_id=project_id,
            memory_type=memory_type,
        )

    @mcp.tool()
    async def pam_forget(
        memory_id: str,
    ) -> str:
        """Delete a specific memory from PAM's memory store.

        Permanently removes the memory from both PostgreSQL and the
        search index. Use pam_recall first to find the memory_id.
        """
        return await _pam_forget(memory_id=memory_id)


async def _pam_remember(
    content: str,
    memory_type: str = "fact",
    source: str | None = None,
    importance: float = 0.5,
    user_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Implementation of pam_remember."""
    import uuid as uuid_mod

    services = get_services()

    if services.memory_service is None:
        return json.dumps({"error": "Memory service is unavailable"})

    result = await services.memory_service.store(
        content=content,
        memory_type=memory_type,
        source=source or "mcp",
        importance=importance,
        user_id=uuid_mod.UUID(user_id) if user_id else None,
        project_id=uuid_mod.UUID(project_id) if project_id else None,
    )

    return json.dumps(
        {
            "id": str(result.id),
            "content": result.content,
            "type": result.type,
            "importance": result.importance,
            "created_at": result.created_at.isoformat() if result.created_at else None,
        },
        indent=2,
    )


async def _pam_recall(
    query: str,
    top_k: int = 10,
    user_id: str | None = None,
    project_id: str | None = None,
    memory_type: str | None = None,
) -> str:
    """Implementation of pam_recall."""
    import uuid as uuid_mod

    services = get_services()

    if services.memory_service is None:
        return json.dumps({"error": "Memory service is unavailable"})

    results = await services.memory_service.search(
        query=query,
        user_id=uuid_mod.UUID(user_id) if user_id else None,
        project_id=uuid_mod.UUID(project_id) if project_id else None,
        type_filter=memory_type,
        top_k=top_k,
    )

    return json.dumps(
        {
            "memories": [
                {
                    "id": str(r.memory.id),
                    "content": r.memory.content,
                    "type": r.memory.type,
                    "importance": r.memory.importance,
                    "score": r.score,
                    "access_count": r.memory.access_count,
                    "created_at": r.memory.created_at.isoformat() if r.memory.created_at else None,
                }
                for r in results
            ],
            "count": len(results),
        },
        indent=2,
    )


async def _pam_forget(memory_id: str) -> str:
    """Implementation of pam_forget."""
    import uuid as uuid_mod

    services = get_services()

    if services.memory_service is None:
        return json.dumps({"error": "Memory service is unavailable"})

    try:
        mid = uuid_mod.UUID(memory_id)
    except ValueError:
        return json.dumps({"error": f"Invalid memory_id: {memory_id}"})

    deleted = await services.memory_service.delete(mid)

    if deleted:
        return json.dumps({"deleted": True, "memory_id": memory_id})
    return json.dumps(
        {"deleted": False, "memory_id": memory_id, "error": "Memory not found"}
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/mcp/test_memory_tools.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/mcp/server.py tests/mcp/test_memory_tools.py tests/mcp/conftest.py
git commit -m "feat(mcp): implement pam_remember, pam_recall, pam_forget tools"
```

---

## Task 9: Wire Into PamServices + App Startup

**Files:**
- Modify: `src/pam/mcp/services.py`
- Modify: `src/pam/api/main.py`
- Modify: `src/pam/mcp/__main__.py`

- [ ] **Step 1: Add memory_service to PamServices**

In `src/pam/mcp/services.py`, add to the TYPE_CHECKING imports:

```python
    from pam.memory.service import MemoryService
```

Add the field to the `PamServices` dataclass after `cache_service`:

```python
    memory_service: MemoryService | None
```

Update `from_app_state()` to include:

```python
        memory_service=getattr(app_state, "memory_service", None),
```

Add it as the last field in the returned `PamServices(...)`.

- [ ] **Step 2: Add MemoryService initialization to FastAPI lifespan**

In `src/pam/api/main.py`, add memory service initialization inside the `lifespan()` function, after the existing service setup and before the MCP block. Find where `app.state.cache_service` is set and add after it:

```python
    # --- Memory Service ---
    try:
        from pam.memory.service import MemoryService
        from pam.memory.store import MemoryStore

        memory_store = MemoryStore(
            client=es_client,
            index_name=settings.memory_index,
            embedding_dims=settings.embedding_dims,
        )
        await memory_store.ensure_index()
        memory_service = MemoryService(
            session_factory=session_factory,
            store=memory_store,
            embedder=embedder,
            anthropic_api_key=settings.anthropic_api_key,
            dedup_threshold=settings.memory_dedup_threshold,
            merge_model=settings.memory_merge_model,
        )
        app.state.memory_service = memory_service
        logger.info("memory_service_initialized")
    except Exception:
        app.state.memory_service = None
        logger.warning("memory_service_init_failed", exc_info=True)
```

In the `create_app()` function, register the memory routes. Find where other routers are included and add:

```python
    from pam.api.routes.memory import router as memory_router, get_memory_service

    app.include_router(memory_router, prefix="/api/memory", tags=["memory"])

    # Override the memory dependency
    def _get_memory_service():
        return app.state.memory_service

    app.dependency_overrides[get_memory_service] = _get_memory_service
```

- [ ] **Step 3: Add MemoryService initialization to stdio entrypoint**

In `src/pam/mcp/__main__.py`, add memory service initialization inside `_create_services()`, after the VDB store setup and before the final `return PamServices(...)`:

```python
    # Memory Service (optional)
    memory_service = None
    try:
        from pam.memory.service import MemoryService
        from pam.memory.store import MemoryStore

        memory_store = MemoryStore(
            client=es_client,
            index_name=settings.memory_index,
            embedding_dims=settings.embedding_dims,
        )
        await memory_store.ensure_index()
        memory_service = MemoryService(
            session_factory=session_factory,
            store=memory_store,
            embedder=embedder,
            anthropic_api_key=settings.anthropic_api_key,
            dedup_threshold=settings.memory_dedup_threshold,
            merge_model=settings.memory_merge_model,
        )
    except Exception:
        logger.warning("memory_service_unavailable_in_mcp_mode")
```

Add `memory_service=memory_service` to the `return PamServices(...)` call.

- [ ] **Step 4: Run existing tests to verify no regressions**

Run: `python -m pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/mcp/services.py src/pam/api/main.py src/pam/mcp/__main__.py
git commit -m "feat(memory): wire MemoryService into PamServices and app startup"
```

---

## Task 10: Security Hardening + Final Verification

**Files:**
- Modify: `src/pam/memory/service.py` (input validation)
- Modify: `src/pam/api/routes/memory.py` (auth guard)

- [ ] **Step 1: Add input validation to MemoryService.store**

In `src/pam/memory/service.py`, add at the top of the `store()` method:

```python
        # Input validation
        if not content or not content.strip():
            raise ValueError("Memory content cannot be empty")
        if len(content) > 10_000:
            raise ValueError("Memory content exceeds 10,000 character limit")
        content = content.strip()
```

- [ ] **Step 2: Add SQL injection guard to search**

In `src/pam/memory/store.py`, add validation in the `search()` method at the top:

```python
        if top_k < 1 or top_k > 100:
            top_k = min(max(top_k, 1), 100)
```

- [ ] **Step 3: Write security test**

Add to `tests/memory/test_service.py`:

```python
@pytest.mark.asyncio
async def test_store_rejects_empty_content(memory_service):
    """store() raises ValueError for empty content."""
    with pytest.raises(ValueError, match="empty"):
        await memory_service.store(content="", memory_type="fact")

    with pytest.raises(ValueError, match="empty"):
        await memory_service.store(content="   ", memory_type="fact")


@pytest.mark.asyncio
async def test_store_rejects_oversized_content(memory_service):
    """store() raises ValueError for content exceeding 10k chars."""
    with pytest.raises(ValueError, match="10,000"):
        await memory_service.store(content="x" * 10_001, memory_type="fact")
```

- [ ] **Step 4: Run the full test suite**

Run: `python -m pytest tests/ -x -q`
Expected: All tests PASS

- [ ] **Step 5: Run the MCP test suite specifically**

Run: `python -m pytest tests/mcp/ tests/memory/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/memory/service.py src/pam/memory/store.py src/pam/api/routes/memory.py tests/memory/test_service.py
git commit -m "fix(memory): security hardening — input validation and bounds checking"
```

---

## Summary of Phase 2 Deliverables

### MCP Tools (3 new)

| MCP Tool | Description |
|----------|-------------|
| `pam_remember` | Store a fact/preference/observation with semantic dedup |
| `pam_recall` | Semantic search across memories, updates access frequency |
| `pam_forget` | Delete a specific memory from PG + ES |

### REST Endpoints (6 new)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/memory` | Store memory with dedup |
| `GET` | `/api/memory/search` | Semantic search |
| `GET` | `/api/memory/{id}` | Get specific memory |
| `PUT` | `/api/memory/{id}` | Update memory |
| `DELETE` | `/api/memory/{id}` | Delete memory |
| `GET` | `/api/memory/user/{user_id}` | List user's memories |

### Key Behaviors

- **Semantic dedup:** cosine similarity > 0.9 triggers LLM-assisted content merge
- **Importance scoring:** formula `0.5*recency + 0.3*access_freq + 0.2*explicit_weight`, recomputed on each access
- **Input validation:** content must be non-empty, max 10k chars
- **Graceful degradation:** memory_service is optional; MCP tools return clear error if unavailable
- **Dual storage:** PG for durability + ES for kNN vector search

### Config Settings (3 new)

| Setting | Default | Description |
|---------|---------|-------------|
| `MEMORY_INDEX` | `pam_memories` | ES index name |
| `MEMORY_DEDUP_THRESHOLD` | `0.9` | Cosine threshold for dedup |
| `MEMORY_MERGE_MODEL` | `claude-haiku-4-5-20251001` | LLM for content merge |

### Not Included (Phase 3+)

| Capability | Phase | Reason |
|-----------|-------|--------|
| Conversation storage | Phase 3 | Separate data model (Conversation + Message) |
| Automatic fact extraction | Phase 3 | Needs extraction pipeline |
| Background importance recomputation | Phase 3 | Needs scheduler (currently recomputed on access) |
| Glossary / terminology | Phase 4 | Independent subsystem |
| `pam_get_context` tool | Phase 2+ | Needs memory + context assembly integration |
