# Universal Memory Layer — Phase 4: Semantic Metadata Layer

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Finch-inspired glossary service that stores curated domain terminology (canonical terms + aliases) and resolves aliases in user queries before search, improving retrieval recall.

**Architecture:** A `GlossaryService` wraps PostgreSQL (durable storage) and Elasticsearch (kNN semantic search + keyword matching on aliases). When a user queries "What's the GBs target?", the alias resolver expands "GBs" to "Gross Bookings" before the query hits search. Three access layers: REST API (`/api/glossary`), MCP tools (`pam_glossary_add`, `pam_glossary_search`, `pam_glossary_resolve`), and the Python service directly. Context assembly gains a glossary section for relevant terms.

**Tech Stack:** SQLAlchemy 2.x (async, PG ARRAY type for aliases), Elasticsearch 8.x (dense_vector kNN + keyword matching), OpenAI embeddings (text-embedding-3-large, 1536d), Alembic migration, FastAPI routes, FastMCP tools, pytest

---

## File Structure

### New Files

```
src/pam/glossary/
  __init__.py              # Re-exports GlossaryService, GlossaryStore
  store.py                 # GlossaryStore — ES index ops (index, search, delete)
  service.py               # GlossaryService — CRUD, semantic search, dedup
  resolver.py              # AliasResolver — fuzzy alias matching + query expansion

src/pam/api/routes/glossary.py  # REST endpoints: POST, GET, PUT, DELETE, search, resolve, list

alembic/versions/010_add_glossary_terms.py  # Migration for glossary_terms table

tests/glossary/
  __init__.py
  conftest.py              # Mock fixtures for GlossaryService, GlossaryStore
  test_store.py            # GlossaryStore unit tests
  test_service.py          # GlossaryService unit tests
  test_resolver.py         # AliasResolver unit tests
```

### Modified Files

```
src/pam/common/models.py        # Add GlossaryTerm ORM model + Pydantic schemas
src/pam/common/config.py        # Add glossary_index, glossary_dedup_threshold settings
src/pam/mcp/server.py           # Add _register_glossary_tools + pam://glossary resource
src/pam/mcp/services.py         # Add glossary_service field to PamServices
src/pam/api/main.py             # Initialize GlossaryService + register glossary routes
src/pam/agent/context_assembly.py  # Add glossary_tokens budget + glossary section
src/pam/agent/agent.py          # Integrate alias resolution before search
```

---

## Task 1: GlossaryTerm ORM Model + Pydantic Schemas

**Files:**
- Modify: `src/pam/common/models.py`
- Create: `tests/glossary/__init__.py`
- Test: `tests/glossary/test_service.py` (first test only)

- [ ] **Step 1: Write the failing test**

Create `tests/glossary/__init__.py` (empty file).

Create `tests/glossary/test_service.py`:

```python
"""Tests for GlossaryTerm model and schemas."""

from pam.common.models import GlossaryTerm


def test_glossary_term_model_has_required_fields():
    """GlossaryTerm ORM model has all expected columns."""
    columns = {c.name for c in GlossaryTerm.__table__.columns}
    expected = {
        "id", "project_id", "canonical", "aliases", "definition",
        "category", "metadata", "created_at", "updated_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/glossary/test_service.py::test_glossary_term_model_has_required_fields -v`
Expected: FAIL with `ImportError: cannot import name 'GlossaryTerm'`

- [ ] **Step 3: Add GlossaryTerm ORM model to models.py**

Add the following import at the top of `src/pam/common/models.py` (add `ARRAY` to the postgresql imports):

```python
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
```

Add this after the `Message` class and before the Pydantic schemas section:

```python
class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    canonical: Mapped[str] = mapped_column(String(300), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default=text("'{}'::text[]"))
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "category IN ('metric', 'team', 'product', 'acronym', 'concept', 'other')",
            name="ck_glossary_terms_category",
        ),
        UniqueConstraint("project_id", "canonical", name="uq_glossary_terms_project_canonical"),
        {"comment": "Curated domain terminology with aliases for query expansion"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/glossary/test_service.py::test_glossary_term_model_has_required_fields -v`
Expected: PASS

- [ ] **Step 5: Add Pydantic schemas for Glossary**

Add the following to `src/pam/common/models.py` after the Conversation schemas section:

```python
# -- Glossary Schemas --


class GlossaryTermCreate(BaseModel):
    canonical: str = Field(min_length=1, max_length=300)
    aliases: list[str] = Field(default_factory=list)
    definition: str = Field(min_length=1, max_length=5_000)
    category: Literal["metric", "team", "product", "acronym", "concept", "other"] = "concept"
    metadata: dict = Field(default_factory=dict)
    project_id: uuid.UUID | None = None


class GlossaryTermResponse(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID | None = None
    canonical: str
    aliases: list[str] = Field(default_factory=list)
    definition: str
    category: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class GlossaryTermUpdate(BaseModel):
    canonical: str | None = Field(default=None, min_length=1, max_length=300)
    aliases: list[str] | None = None
    definition: str | None = Field(default=None, min_length=1, max_length=5_000)
    category: Literal["metric", "team", "product", "acronym", "concept", "other"] | None = None
    metadata: dict | None = None


class GlossarySearchResult(BaseModel):
    term: GlossaryTermResponse
    score: float


class GlossaryResolveResult(BaseModel):
    original_query: str
    expanded_query: str
    resolved_terms: list[dict] = Field(default_factory=list)
```

- [ ] **Step 6: Write schema tests**

Add to `tests/glossary/test_service.py`:

```python
import pytest

from pam.common.models import (
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
)


def test_glossary_term_create_defaults():
    """GlossaryTermCreate has correct defaults."""
    tc = GlossaryTermCreate(canonical="Gross Bookings", definition="Total fare amount")
    assert tc.category == "concept"
    assert tc.aliases == []
    assert tc.metadata == {}
    assert tc.project_id is None


def test_glossary_term_create_with_aliases():
    """GlossaryTermCreate accepts aliases."""
    tc = GlossaryTermCreate(
        canonical="Gross Bookings",
        aliases=["GBs", "gross books"],
        definition="Total fare amount before deductions",
        category="metric",
    )
    assert tc.aliases == ["GBs", "gross books"]
    assert tc.category == "metric"


def test_glossary_term_create_rejects_empty_canonical():
    """GlossaryTermCreate rejects empty canonical."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GlossaryTermCreate(canonical="", definition="Something")


def test_glossary_term_create_rejects_invalid_category():
    """GlossaryTermCreate rejects invalid category."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        GlossaryTermCreate(canonical="Test", definition="Def", category="invalid")
```

- [ ] **Step 7: Run all glossary tests**

Run: `python -m pytest tests/glossary/test_service.py -v`
Expected: All PASS

- [ ] **Step 8: Commit**

```bash
git add tests/glossary/__init__.py tests/glossary/test_service.py src/pam/common/models.py
git commit -m "feat(glossary): add GlossaryTerm ORM model and Pydantic schemas"
```

---

## Task 2: Alembic Migration

**Files:**
- Create: `alembic/versions/010_add_glossary_terms.py`

- [ ] **Step 1: Write the migration**

Create `alembic/versions/010_add_glossary_terms.py`:

```python
"""Add glossary_terms table for semantic metadata layer.

Revision ID: 010
Revises: 009
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "glossary_terms",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "project_id",
            UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("canonical", sa.String(300), nullable=False),
        sa.Column("aliases", ARRAY(sa.Text), server_default=sa.text("'{}'::text[]")),
        sa.Column("definition", sa.Text, nullable=False),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "category IN ('metric', 'team', 'product', 'acronym', 'concept', 'other')",
            name="ck_glossary_terms_category",
        ),
        sa.UniqueConstraint("project_id", "canonical", name="uq_glossary_terms_project_canonical"),
        comment="Curated domain terminology with aliases for query expansion",
    )
    op.create_index("ix_glossary_terms_project_id", "glossary_terms", ["project_id"])
    op.create_index("ix_glossary_terms_category", "glossary_terms", ["category"])
    op.create_index("ix_glossary_terms_canonical", "glossary_terms", ["canonical"])


def downgrade() -> None:
    op.drop_index("ix_glossary_terms_canonical", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_category", table_name="glossary_terms")
    op.drop_index("ix_glossary_terms_project_id", table_name="glossary_terms")
    op.drop_table("glossary_terms")
```

- [ ] **Step 2: Verify migration syntax**

Run: `python -m py_compile alembic/versions/010_add_glossary_terms.py`
Expected: No output (clean compile)

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/010_add_glossary_terms.py
git commit -m "feat(glossary): add Alembic migration for glossary_terms table"
```

---

## Task 3: Configuration Settings

**Files:**
- Modify: `src/pam/common/config.py`
- Test: `tests/glossary/test_service.py` (add config test)

- [ ] **Step 1: Write the failing test**

Add to `tests/glossary/test_service.py`:

```python
def test_glossary_config_settings_exist():
    """Config has glossary-related settings."""
    from pam.common.config import Settings

    fields = Settings.model_fields
    assert "glossary_index" in fields
    assert "glossary_dedup_threshold" in fields
    assert "glossary_context_budget" in fields
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/glossary/test_service.py::test_glossary_config_settings_exist -v`
Expected: FAIL with `AssertionError`

- [ ] **Step 3: Add glossary settings to config.py**

Add the following to `src/pam/common/config.py` in the `Settings` class, after the `# Memory Service` section:

```python
    # Glossary / Semantic Metadata
    glossary_index: str = "pam_glossary"  # ES index for glossary term embeddings
    glossary_dedup_threshold: float = 0.92  # Cosine similarity threshold for term dedup
    glossary_context_budget: int = 1000  # Token budget for glossary terms in context assembly
```

Also update the `_check_constraints` validator to validate `glossary_dedup_threshold`. Add after the `memory_dedup_threshold` check:

```python
        if not 0.0 <= self.glossary_dedup_threshold <= 1.0:
            raise ValueError(f"glossary_dedup_threshold must be 0.0-1.0, got {self.glossary_dedup_threshold}")
```

And update the total_budget calculation to include glossary:

```python
        total_budget = (
            self.context_entity_budget
            + self.context_relationship_budget
            + self.context_memory_budget
            + self.conversation_context_max_tokens
            + self.glossary_context_budget
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/glossary/test_service.py::test_glossary_config_settings_exist -v`
Expected: PASS

- [ ] **Step 5: Update context_max_tokens default to accommodate glossary budget**

In `config.py`, increase `context_max_tokens` default from 16000 to 17000 to accommodate the new glossary budget:

```python
    context_max_tokens: int = 17000
```

- [ ] **Step 6: Run existing config tests to ensure no regressions**

Run: `python -m pytest tests/ -k "config" -v --no-header 2>&1 | head -30`
Expected: All existing config tests pass

- [ ] **Step 7: Commit**

```bash
git add src/pam/common/config.py tests/glossary/test_service.py
git commit -m "feat(glossary): add glossary config settings and context budget"
```

---

## Task 4: GlossaryStore (Elasticsearch)

**Files:**
- Create: `src/pam/glossary/__init__.py`
- Create: `src/pam/glossary/store.py`
- Create: `tests/glossary/conftest.py`
- Create: `tests/glossary/test_store.py`

- [ ] **Step 1: Write the failing test for index mapping**

Create `tests/glossary/conftest.py`:

```python
"""Shared fixtures for glossary tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.glossary.store import GlossaryStore


@pytest.fixture()
def mock_es_client() -> AsyncMock:
    """Create a mock Elasticsearch client."""
    client = AsyncMock()
    client.indices = AsyncMock()
    client.indices.exists = AsyncMock(return_value=False)
    client.indices.create = AsyncMock()
    client.options = MagicMock(return_value=AsyncMock())
    return client


@pytest.fixture()
def glossary_store(mock_es_client: AsyncMock) -> GlossaryStore:
    """Create a GlossaryStore with mocked ES client."""
    return GlossaryStore(
        client=mock_es_client,
        index_name="test_glossary",
        embedding_dims=1536,
    )


@pytest.fixture()
def mock_embedder() -> AsyncMock:
    """Create a mock embedder."""
    embedder = AsyncMock()
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    return embedder


@pytest.fixture()
def mock_store() -> AsyncMock:
    """Create a mock GlossaryStore."""
    store = AsyncMock(spec=GlossaryStore)
    store.find_duplicates = AsyncMock(return_value=[])
    store.index_term = AsyncMock()
    store.search = AsyncMock(return_value=[])
    store.search_by_alias = AsyncMock(return_value=[])
    store.delete = AsyncMock()
    return store


@pytest.fixture()
def mock_session_factory() -> MagicMock:
    """Create a mock async session factory."""
    factory = MagicMock()
    session = AsyncMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory
```

Create `tests/glossary/test_store.py`:

```python
"""Tests for GlossaryStore ES operations."""

from __future__ import annotations

import uuid

import pytest

from pam.glossary.store import GlossaryStore, get_glossary_index_mapping


def test_glossary_index_mapping_structure():
    """Index mapping has correct fields and types."""
    mapping = get_glossary_index_mapping(1536)
    props = mapping["mappings"]["properties"]

    assert props["embedding"]["type"] == "dense_vector"
    assert props["embedding"]["dims"] == 1536
    assert props["embedding"]["similarity"] == "cosine"
    assert props["canonical"]["type"] == "keyword"
    assert props["aliases"]["type"] == "keyword"
    assert props["definition"]["type"] == "text"
    assert props["category"]["type"] == "keyword"
    assert props["project_id"]["type"] == "keyword"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/glossary/test_store.py::test_glossary_index_mapping_structure -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pam.glossary'`

- [ ] **Step 3: Create the GlossaryStore**

Create `src/pam/glossary/__init__.py`:

```python
"""Glossary / Semantic Metadata Layer -- curated domain terminology."""
```

Create `src/pam/glossary/store.py`:

```python
"""Elasticsearch store for glossary term embeddings and search."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from uuid import UUID

import structlog

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch

logger = structlog.get_logger()


def get_glossary_index_mapping(embedding_dims: int) -> dict:
    """Build the ES index mapping for glossary terms."""
    return {
        "mappings": {
            "properties": {
                "canonical": {"type": "keyword", "normalizer": "lowercase"},
                "canonical_text": {"type": "text", "analyzer": "standard"},
                "aliases": {"type": "keyword", "normalizer": "lowercase"},
                "aliases_text": {"type": "text", "analyzer": "standard"},
                "definition": {"type": "text", "analyzer": "standard"},
                "category": {"type": "keyword"},
                "project_id": {"type": "keyword"},
                "embedding": {
                    "type": "dense_vector",
                    "dims": embedding_dims,
                    "index": True,
                    "similarity": "cosine",
                },
                "created_at": {"type": "date"},
                "updated_at": {"type": "date"},
            }
        },
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "normalizer": {
                    "lowercase": {
                        "type": "custom",
                        "filter": ["lowercase"],
                    }
                }
            },
        },
    }


class GlossaryStore:
    """Elasticsearch store for glossary term vector + keyword search."""

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
        """Create the glossary index if it does not exist."""
        exists = await self._client.indices.exists(index=self._index_name)
        if not exists:
            mapping = get_glossary_index_mapping(self._embedding_dims)
            await self._client.indices.create(index=self._index_name, body=mapping)
            logger.info("glossary_index_created", index=self._index_name)

    async def index_term(
        self,
        term_id: UUID,
        canonical: str,
        aliases: list[str],
        definition: str,
        embedding: list[float],
        category: str,
        project_id: UUID | None = None,
    ) -> None:
        """Index a glossary term for kNN + keyword search."""
        doc: dict[str, Any] = {
            "canonical": canonical,
            "canonical_text": canonical,
            "aliases": [a.strip() for a in aliases if a.strip()],
            "aliases_text": " ".join(a.strip() for a in aliases if a.strip()),
            "definition": definition,
            "embedding": embedding,
            "category": category,
        }
        if project_id:
            doc["project_id"] = str(project_id)

        await self._client.index(
            index=self._index_name,
            id=str(term_id),
            document=doc,
            refresh="wait_for",
        )

    async def search(
        self,
        query_embedding: list[float],
        project_id: UUID | None = None,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic kNN search for glossary terms."""
        if top_k < 1 or top_k > 100:
            top_k = min(max(top_k, 1), 100)

        filters: list[dict] = []
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})
        if category:
            filters.append({"term": {"category": category}})

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
                "term_id": hit["_id"],
                "score": hit["_score"],
                "canonical": hit["_source"].get("canonical", ""),
                "aliases": hit["_source"].get("aliases", []),
                "definition": hit["_source"].get("definition", ""),
                "category": hit["_source"].get("category", ""),
            }
            for hit in result["hits"]["hits"]
        ]

    async def search_by_alias(
        self,
        alias: str,
        project_id: UUID | None = None,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Keyword search on canonical + aliases fields (case-insensitive).

        Uses multi_match across keyword (exact, lowercased) and text (analyzed) fields.
        """
        filters: list[dict] = []
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})

        query: dict[str, Any] = {
            "bool": {
                "should": [
                    {"term": {"canonical": alias.lower()}},
                    {"term": {"aliases": alias.lower()}},
                    {"match": {"canonical_text": {"query": alias, "boost": 2.0}}},
                    {"match": {"aliases_text": {"query": alias, "boost": 1.5}}},
                    {"match": {"definition": {"query": alias, "boost": 0.5}}},
                ],
                "minimum_should_match": 1,
            }
        }
        if filters:
            query["bool"]["filter"] = filters

        result = await self._client.search(
            index=self._index_name,
            query=query,
            size=top_k,
        )

        return [
            {
                "term_id": hit["_id"],
                "score": hit["_score"],
                "canonical": hit["_source"].get("canonical", ""),
                "aliases": hit["_source"].get("aliases", []),
                "definition": hit["_source"].get("definition", ""),
                "category": hit["_source"].get("category", ""),
            }
            for hit in result["hits"]["hits"]
        ]

    async def find_duplicates(
        self,
        embedding: list[float],
        project_id: UUID | None,
        threshold: float = 0.92,
    ) -> list[dict[str, Any]]:
        """Find semantically similar terms for dedup check."""
        filters: list[dict] = []
        if project_id:
            filters.append({"term": {"project_id": str(project_id)}})

        normalized_threshold = (1.0 + threshold) / 2.0
        knn: dict[str, Any] = {
            "field": "embedding",
            "query_vector": embedding,
            "k": 5,
            "num_candidates": 50,
            "similarity": normalized_threshold,
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
                "term_id": hit["_id"],
                "score": hit["_score"],
                "canonical": hit["_source"].get("canonical", ""),
            }
            for hit in result["hits"]["hits"]
        ]

    async def delete(self, term_id: UUID) -> None:
        """Remove a term from the ES index. Tolerates missing docs."""
        await self._client.options(ignore_status=404).delete(
            index=self._index_name,
            id=str(term_id),
            refresh="wait_for",
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/glossary/test_store.py::test_glossary_index_mapping_structure -v`
Expected: PASS

- [ ] **Step 5: Write remaining store tests**

Add to `tests/glossary/test_store.py`:

```python
@pytest.mark.asyncio
async def test_ensure_index_creates_when_missing(glossary_store, mock_es_client):
    """ensure_index creates the index when it doesn't exist."""
    mock_es_client.indices.exists.return_value = False

    await glossary_store.ensure_index()

    mock_es_client.indices.create.assert_awaited_once()
    call_kwargs = mock_es_client.indices.create.call_args
    assert call_kwargs.kwargs["index"] == "test_glossary"


@pytest.mark.asyncio
async def test_ensure_index_skips_when_exists(glossary_store, mock_es_client):
    """ensure_index is a no-op when index already exists."""
    mock_es_client.indices.exists.return_value = True

    await glossary_store.ensure_index()

    mock_es_client.indices.create.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_term(glossary_store, mock_es_client):
    """index_term indexes a glossary term in ES."""
    term_id = uuid.uuid4()
    embedding = [0.1] * 1536

    await glossary_store.index_term(
        term_id=term_id,
        canonical="Gross Bookings",
        aliases=["GBs", "gross books"],
        definition="Total fare amount before deductions",
        embedding=embedding,
        category="metric",
        project_id=uuid.uuid4(),
    )

    mock_es_client.index.assert_awaited_once()
    call_kwargs = mock_es_client.index.call_args.kwargs
    assert call_kwargs["index"] == "test_glossary"
    assert call_kwargs["id"] == str(term_id)
    assert call_kwargs["document"]["canonical"] == "Gross Bookings"
    assert call_kwargs["document"]["aliases"] == ["GBs", "gross books"]


@pytest.mark.asyncio
async def test_search_terms(glossary_store, mock_es_client):
    """search returns scored term IDs from kNN search."""
    term_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(term_id),
                    "_score": 0.95,
                    "_source": {
                        "canonical": "Gross Bookings",
                        "aliases": ["GBs"],
                        "definition": "Total fare amount",
                        "category": "metric",
                    },
                }
            ]
        }
    }

    results = await glossary_store.search(
        query_embedding=[0.1] * 1536,
        top_k=5,
    )

    assert len(results) == 1
    assert results[0]["canonical"] == "Gross Bookings"
    assert results[0]["score"] == 0.95


@pytest.mark.asyncio
async def test_search_by_alias(glossary_store, mock_es_client):
    """search_by_alias finds terms by keyword match on canonical/aliases."""
    term_id = uuid.uuid4()
    mock_es_client.search.return_value = {
        "hits": {
            "hits": [
                {
                    "_id": str(term_id),
                    "_score": 8.5,
                    "_source": {
                        "canonical": "Gross Bookings",
                        "aliases": ["GBs", "gross books"],
                        "definition": "Total fare amount",
                        "category": "metric",
                    },
                }
            ]
        }
    }

    results = await glossary_store.search_by_alias(alias="GBs")

    assert len(results) == 1
    assert results[0]["canonical"] == "Gross Bookings"
    mock_es_client.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_term(glossary_store, mock_es_client):
    """delete removes a term from ES."""
    term_id = uuid.uuid4()
    options_mock = mock_es_client.options.return_value

    await glossary_store.delete(term_id)

    mock_es_client.options.assert_called_once_with(ignore_status=404)
    options_mock.delete.assert_awaited_once()
```

- [ ] **Step 6: Run all store tests**

Run: `python -m pytest tests/glossary/test_store.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/pam/glossary/__init__.py src/pam/glossary/store.py tests/glossary/conftest.py tests/glossary/test_store.py
git commit -m "feat(glossary): add GlossaryStore ES index with kNN + keyword search"
```

---

## Task 5: GlossaryService (CRUD + Semantic Search)

**Files:**
- Create: `src/pam/glossary/service.py`
- Test: `tests/glossary/test_service.py` (add service tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/glossary/test_service.py`:

```python
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from pam.glossary.service import GlossaryService
from pam.common.models import GlossaryTerm


@pytest.mark.asyncio
async def test_add_term_no_duplicate(mock_session_factory, mock_store, mock_embedder):
    """add() inserts a new term when no duplicate exists."""
    mock_store.find_duplicates.return_value = []

    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
        dedup_threshold=0.92,
    )

    result = await service.add(
        canonical="Gross Bookings",
        aliases=["GBs", "gross books"],
        definition="Total fare amount before deductions",
        category="metric",
    )

    assert result is not None
    assert result.canonical == "Gross Bookings"
    assert result.category == "metric"
    mock_embedder.embed_texts.assert_awaited_once()
    mock_store.index_term.assert_awaited_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/glossary/test_service.py::test_add_term_no_duplicate -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pam.glossary.service'`

- [ ] **Step 3: Create GlossaryService**

Create `src/pam/glossary/service.py`:

```python
"""Glossary service -- CRUD operations with semantic dedup."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog

from pam.common.models import GlossaryTerm, GlossaryTermResponse, GlossarySearchResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pam.glossary.store import GlossaryStore
    from pam.ingestion.embedders.base import BaseEmbedder

logger = structlog.get_logger()


def _term_to_response(term: GlossaryTerm) -> GlossaryTermResponse:
    """Convert a GlossaryTerm ORM instance to a GlossaryTermResponse."""
    return GlossaryTermResponse(
        id=term.id,
        project_id=term.project_id,
        canonical=term.canonical,
        aliases=term.aliases if term.aliases else [],
        definition=term.definition,
        category=term.category,
        metadata=term.metadata_ if isinstance(term.metadata_, dict) else {},
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


class GlossaryService:
    """Manages glossary terms with semantic dedup and alias search."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        store: GlossaryStore,
        embedder: BaseEmbedder,
        dedup_threshold: float = 0.92,
    ) -> None:
        self._session_factory = session_factory
        self._store = store
        self._embedder = embedder
        self._dedup_threshold = dedup_threshold

    @classmethod
    async def create_from_settings(
        cls,
        session_factory: async_sessionmaker[AsyncSession],
        es_client: object,
        embedder: BaseEmbedder,
        settings: object,
    ) -> GlossaryService:
        """Factory to create GlossaryService + GlossaryStore from app settings."""
        from pam.glossary.store import GlossaryStore

        store = GlossaryStore(
            client=es_client,  # type: ignore[arg-type]
            index_name=settings.glossary_index,  # type: ignore[attr-defined]
            embedding_dims=settings.embedding_dims,  # type: ignore[attr-defined]
        )
        await store.ensure_index()
        return cls(
            session_factory=session_factory,
            store=store,
            embedder=embedder,
            dedup_threshold=settings.glossary_dedup_threshold,  # type: ignore[attr-defined]
        )

    async def add(
        self,
        canonical: str,
        definition: str,
        category: str = "concept",
        aliases: list[str] | None = None,
        metadata: dict | None = None,
        project_id: uuid_mod.UUID | None = None,
    ) -> GlossaryTermResponse:
        """Add a glossary term with semantic deduplication.

        If a term with cosine similarity > threshold exists for the same project,
        raises ValueError with the duplicate's canonical name.
        """
        if not canonical or not canonical.strip():
            raise ValueError("Canonical term cannot be empty")
        if not definition or not definition.strip():
            raise ValueError("Definition cannot be empty")
        canonical = canonical.strip()
        definition = definition.strip()
        aliases = [a.strip() for a in (aliases or []) if a.strip()]

        # Embed the definition for semantic search
        embed_text = f"{canonical}: {definition}"
        embeddings = await self._embedder.embed_texts([embed_text])
        embedding = embeddings[0]

        # Check for duplicates
        duplicates = await self._store.find_duplicates(
            embedding=embedding,
            project_id=project_id,
            threshold=self._dedup_threshold,
        )
        if duplicates:
            dup = duplicates[0]
            raise ValueError(
                f"A similar term already exists: '{dup['canonical']}' "
                f"(similarity: {dup['score']:.2f}). Update the existing term instead."
            )

        # Insert new term
        term_id = uuid_mod.uuid4()
        now = datetime.now(tz=timezone.utc)
        term = GlossaryTerm(
            id=term_id,
            project_id=project_id,
            canonical=canonical,
            aliases=aliases,
            definition=definition,
            category=category,
            metadata_=metadata or {},
            created_at=now,
            updated_at=now,
        )

        async with self._session_factory() as session:
            session.add(term)
            await session.flush()
            await session.commit()

        # Index in ES -- rollback PG if this fails
        try:
            await self._store.index_term(
                term_id=term_id,
                canonical=canonical,
                aliases=aliases,
                definition=definition,
                embedding=embedding,
                category=category,
                project_id=project_id,
            )
        except Exception:
            from sqlalchemy import delete as sa_delete

            async with self._session_factory() as rollback_session:
                await rollback_session.execute(
                    sa_delete(GlossaryTerm).where(GlossaryTerm.id == term_id)
                )
                await rollback_session.commit()
            logger.error("glossary_es_index_failed", term_id=str(term_id), exc_info=True)
            raise

        logger.info("glossary_term_added", term_id=str(term_id), canonical=canonical)
        return _term_to_response(term)

    async def search(
        self,
        query: str,
        project_id: uuid_mod.UUID | None = None,
        category: str | None = None,
        top_k: int = 10,
    ) -> list[GlossarySearchResult]:
        """Search glossary terms by semantic similarity."""
        embeddings = await self._embedder.embed_texts([query])
        query_embedding = embeddings[0]

        hits = await self._store.search(
            query_embedding=query_embedding,
            project_id=project_id,
            category=category,
            top_k=top_k,
        )

        if not hits:
            return []

        # Fetch full term objects from PG
        term_ids = [uuid_mod.UUID(h["term_id"]) for h in hits]
        score_map = {h["term_id"]: h["score"] for h in hits}

        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id.in_(term_ids))
            )
            terms = result.scalars().all()

        term_map = {str(t.id): t for t in terms}
        results = []
        for hit in hits:
            term = term_map.get(hit["term_id"])
            if term:
                results.append(
                    GlossarySearchResult(
                        term=_term_to_response(term),
                        score=score_map[hit["term_id"]],
                    )
                )

        return results

    async def search_by_alias(
        self,
        alias: str,
        project_id: uuid_mod.UUID | None = None,
        top_k: int = 5,
    ) -> list[GlossarySearchResult]:
        """Search glossary terms by keyword match on canonical/aliases."""
        hits = await self._store.search_by_alias(
            alias=alias,
            project_id=project_id,
            top_k=top_k,
        )

        if not hits:
            return []

        term_ids = [uuid_mod.UUID(h["term_id"]) for h in hits]
        score_map = {h["term_id"]: h["score"] for h in hits}

        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id.in_(term_ids))
            )
            terms = result.scalars().all()

        term_map = {str(t.id): t for t in terms}
        results = []
        for hit in hits:
            term = term_map.get(hit["term_id"])
            if term:
                results.append(
                    GlossarySearchResult(
                        term=_term_to_response(term),
                        score=score_map[hit["term_id"]],
                    )
                )

        return results

    async def get(self, term_id: uuid_mod.UUID) -> GlossaryTermResponse | None:
        """Fetch a single term by ID."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id == term_id)
            )
            term = result.scalars().first()
            if term is None:
                return None
            return _term_to_response(term)

    async def list_terms(
        self,
        project_id: uuid_mod.UUID | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GlossaryTermResponse]:
        """List glossary terms, optionally filtered by project/category."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            stmt = select(GlossaryTerm).order_by(GlossaryTerm.canonical)
            if project_id:
                stmt = stmt.where(GlossaryTerm.project_id == project_id)
            if category:
                stmt = stmt.where(GlossaryTerm.category == category)
            stmt = stmt.offset(offset).limit(limit)

            result = await session.execute(stmt)
            terms = result.scalars().all()
            return [_term_to_response(t) for t in terms]

    async def update(
        self,
        term_id: uuid_mod.UUID,
        canonical: str | None = None,
        aliases: list[str] | None = None,
        definition: str | None = None,
        category: str | None = None,
        metadata: dict | None = None,
    ) -> GlossaryTermResponse | None:
        """Update a glossary term. Re-embeds and re-indexes if content changes."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id == term_id)
            )
            term = result.scalars().first()
            if term is None:
                return None

            content_changed = False
            if canonical is not None and canonical != term.canonical:
                term.canonical = canonical
                content_changed = True
            if aliases is not None:
                term.aliases = [a.strip() for a in aliases if a.strip()]
                content_changed = True
            if definition is not None and definition != term.definition:
                term.definition = definition
                content_changed = True
            if category is not None:
                term.category = category
            if metadata is not None:
                term.metadata_ = metadata

            term.updated_at = datetime.now(tz=timezone.utc)
            await session.flush()
            await session.commit()

            response = _term_to_response(term)
            t_canonical = term.canonical
            t_aliases = term.aliases or []
            t_definition = term.definition
            t_category = term.category
            t_project_id = term.project_id

        # Re-index in ES if content changed
        if content_changed:
            embed_text = f"{t_canonical}: {t_definition}"
            embeddings = await self._embedder.embed_texts([embed_text])
            await self._store.index_term(
                term_id=term_id,
                canonical=t_canonical,
                aliases=t_aliases,
                definition=t_definition,
                embedding=embeddings[0],
                category=t_category,
                project_id=t_project_id,
            )

        return response

    async def delete(self, term_id: uuid_mod.UUID) -> bool:
        """Delete a glossary term from PG and ES. Returns True if found and deleted."""
        from sqlalchemy import select

        async with self._session_factory() as session:
            result = await session.execute(
                select(GlossaryTerm).where(GlossaryTerm.id == term_id)
            )
            term = result.scalars().first()
            if term is None:
                return False

            await session.delete(term)
            await session.flush()
            await session.commit()

        await self._store.delete(term_id)
        logger.info("glossary_term_deleted", term_id=str(term_id))
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/glossary/test_service.py::test_add_term_no_duplicate -v`
Expected: PASS

- [ ] **Step 5: Write additional service tests**

Add to `tests/glossary/test_service.py`:

```python
@pytest.mark.asyncio
async def test_add_term_rejects_duplicate(mock_session_factory, mock_store, mock_embedder):
    """add() raises ValueError when a semantically similar term exists."""
    mock_store.find_duplicates.return_value = [
        {"term_id": str(uuid.uuid4()), "score": 0.95, "canonical": "Gross Bookings"}
    ]

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )

    with pytest.raises(ValueError, match="similar term already exists"):
        await service.add(
            canonical="Total Bookings",
            definition="Total fare amount before deductions",
            category="metric",
        )


@pytest.mark.asyncio
async def test_add_term_rejects_empty_canonical(mock_session_factory, mock_store, mock_embedder):
    """add() raises ValueError for empty canonical."""
    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        await service.add(canonical="", definition="Something")


@pytest.mark.asyncio
async def test_search_returns_scored_results(mock_session_factory, mock_store, mock_embedder):
    """search() returns GlossarySearchResult list."""
    term_id = uuid.uuid4()
    mock_store.search.return_value = [
        {
            "term_id": str(term_id),
            "score": 0.9,
            "canonical": "Gross Bookings",
            "aliases": ["GBs"],
            "definition": "Total fare",
            "category": "metric",
        }
    ]

    # Mock PG query
    mock_term = GlossaryTerm(
        id=term_id,
        canonical="Gross Bookings",
        aliases=["GBs"],
        definition="Total fare",
        category="metric",
        metadata_={},
        created_at=datetime.now(tz=timezone.utc),
        updated_at=datetime.now(tz=timezone.utc),
    )
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_term]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )

    results = await service.search(query="gross bookings")

    assert len(results) == 1
    assert results[0].term.canonical == "Gross Bookings"
    assert results[0].score == 0.9


@pytest.mark.asyncio
async def test_delete_returns_false_when_not_found(mock_session_factory, mock_store, mock_embedder):
    """delete() returns False when term doesn't exist."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )

    result = await service.delete(uuid.uuid4())
    assert result is False
```

- [ ] **Step 6: Run all service tests**

Run: `python -m pytest tests/glossary/test_service.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/pam/glossary/service.py tests/glossary/test_service.py
git commit -m "feat(glossary): add GlossaryService with CRUD and semantic dedup"
```

---

## Task 6: Alias Resolver (Query Expansion)

**Files:**
- Create: `src/pam/glossary/resolver.py`
- Create: `tests/glossary/test_resolver.py`

- [ ] **Step 1: Write the failing test**

Create `tests/glossary/test_resolver.py`:

```python
"""Tests for AliasResolver query expansion."""

from __future__ import annotations

import re
from unittest.mock import AsyncMock

import pytest

from pam.glossary.resolver import AliasResolver


@pytest.fixture()
def mock_glossary_store() -> AsyncMock:
    """Mock GlossaryStore for resolver tests."""
    store = AsyncMock()
    store.search_by_alias = AsyncMock(return_value=[])
    return store


@pytest.fixture()
def resolver(mock_glossary_store) -> AliasResolver:
    return AliasResolver(store=mock_glossary_store)


@pytest.mark.asyncio
async def test_resolve_expands_known_alias(resolver, mock_glossary_store):
    """resolve() expands known aliases to canonical terms."""
    mock_glossary_store.search_by_alias.return_value = [
        {
            "term_id": "abc",
            "score": 10.0,
            "canonical": "Gross Bookings",
            "aliases": ["GBs", "gross books"],
            "definition": "Total fare amount",
            "category": "metric",
        }
    ]

    result = await resolver.resolve("What's the GBs target?")

    assert "Gross Bookings" in result.expanded_query
    assert len(result.resolved_terms) == 1
    assert result.resolved_terms[0]["canonical"] == "Gross Bookings"
    assert result.original_query == "What's the GBs target?"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/glossary/test_resolver.py::test_resolve_expands_known_alias -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'pam.glossary.resolver'`

- [ ] **Step 3: Create AliasResolver**

Create `src/pam/glossary/resolver.py`:

```python
"""Alias resolution and query expansion using glossary terms."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from uuid import UUID

    from pam.glossary.store import GlossaryStore

logger = structlog.get_logger()


@dataclass
class ResolvedQuery:
    """Result of alias resolution."""

    original_query: str
    expanded_query: str
    resolved_terms: list[dict] = field(default_factory=list)


class AliasResolver:
    """Resolves aliases in user queries to canonical glossary terms.

    Strategy:
    1. Tokenize query into candidate words/phrases
    2. For each candidate, search glossary aliases (keyword match)
    3. If a match is found with score above threshold, note the expansion
    4. Return the expanded query with resolved terms appended
    """

    def __init__(
        self,
        store: GlossaryStore,
        min_score: float = 3.0,
        project_id: UUID | None = None,
    ) -> None:
        self._store = store
        self._min_score = min_score
        self._project_id = project_id

    async def resolve(
        self,
        query: str,
        project_id: UUID | None = None,
    ) -> ResolvedQuery:
        """Resolve aliases in a query string to canonical terms.

        Extracts candidate tokens from the query, searches each against
        the glossary, and appends canonical expansions.
        """
        pid = project_id or self._project_id
        candidates = self._extract_candidates(query)

        if not candidates:
            return ResolvedQuery(original_query=query, expanded_query=query)

        resolved_terms: list[dict] = []
        seen_canonicals: set[str] = set()

        for candidate in candidates:
            hits = await self._store.search_by_alias(
                alias=candidate,
                project_id=pid,
                top_k=1,
            )
            if not hits:
                continue

            hit = hits[0]
            if hit["score"] < self._min_score:
                continue

            canonical = hit["canonical"]
            if canonical.lower() in seen_canonicals:
                continue

            # Verify the candidate actually matches an alias or canonical
            all_names = [canonical.lower()] + [a.lower() for a in hit.get("aliases", [])]
            if candidate.lower() not in all_names:
                continue

            seen_canonicals.add(canonical.lower())
            resolved_terms.append({
                "matched": candidate,
                "canonical": canonical,
                "definition": hit.get("definition", ""),
                "category": hit.get("category", ""),
            })

        if not resolved_terms:
            return ResolvedQuery(original_query=query, expanded_query=query)

        # Build expanded query: original + glossary context
        expansions = []
        for rt in resolved_terms:
            if rt["matched"].lower() != rt["canonical"].lower():
                expansions.append(f'{rt["matched"]} (= {rt["canonical"]})')

        expanded = query
        if expansions:
            expanded = f"{query} [Glossary: {'; '.join(expansions)}]"

        logger.info(
            "alias_resolved",
            original=query[:100],
            resolved_count=len(resolved_terms),
        )

        return ResolvedQuery(
            original_query=query,
            expanded_query=expanded,
            resolved_terms=resolved_terms,
        )

    def _extract_candidates(self, query: str) -> list[str]:
        """Extract candidate tokens that might be aliases.

        Focuses on:
        - Quoted terms
        - Uppercase abbreviations (GBs, EMEA)
        - Individual words (filtered by length and stop words)
        """
        candidates: list[str] = []
        seen: set[str] = set()

        def _add(token: str) -> None:
            t = token.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                candidates.append(t)

        # Quoted terms: "Gross Bookings"
        for match in re.finditer(r'"([^"]+)"', query):
            _add(match.group(1))

        # Uppercase abbreviations: GBs, EMEA, US&C
        for match in re.finditer(r'\b[A-Z][A-Z&]+[a-z]?\b', query):
            _add(match.group())

        # Individual words (3+ chars, not stop words)
        stop_words = {
            "the", "what", "how", "why", "who", "when", "where",
            "is", "are", "was", "were", "and", "for", "our",
            "last", "this", "that", "with", "from", "have", "has",
        }
        for word in re.findall(r'\b\w+\b', query):
            if len(word) >= 3 and word.lower() not in stop_words:
                _add(word)

        return candidates
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/glossary/test_resolver.py::test_resolve_expands_known_alias -v`
Expected: PASS

- [ ] **Step 5: Write additional resolver tests**

Add to `tests/glossary/test_resolver.py`:

```python
@pytest.mark.asyncio
async def test_resolve_no_matches_returns_original(resolver, mock_glossary_store):
    """resolve() returns original query when no aliases match."""
    mock_glossary_store.search_by_alias.return_value = []

    result = await resolver.resolve("What is the revenue?")

    assert result.expanded_query == "What is the revenue?"
    assert result.resolved_terms == []


@pytest.mark.asyncio
async def test_resolve_skips_low_score(resolver, mock_glossary_store):
    """resolve() skips matches below min_score threshold."""
    mock_glossary_store.search_by_alias.return_value = [
        {
            "term_id": "abc",
            "score": 1.0,  # Below default min_score of 3.0
            "canonical": "Gross Bookings",
            "aliases": ["GBs"],
            "definition": "Total fare",
            "category": "metric",
        }
    ]

    result = await resolver.resolve("What's the GBs target?")

    assert result.expanded_query == "What's the GBs target?"
    assert result.resolved_terms == []


@pytest.mark.asyncio
async def test_resolve_deduplicates_canonicals(resolver, mock_glossary_store):
    """resolve() doesn't add the same canonical term twice."""
    mock_glossary_store.search_by_alias.side_effect = [
        [{"term_id": "abc", "score": 10.0, "canonical": "Gross Bookings",
          "aliases": ["GBs"], "definition": "Total fare", "category": "metric"}],
        [{"term_id": "abc", "score": 10.0, "canonical": "Gross Bookings",
          "aliases": ["GBs"], "definition": "Total fare", "category": "metric"}],
        [],
        [],
        [],
    ]

    result = await resolver.resolve("GBs and GBs trend")

    canonical_matches = [rt["canonical"] for rt in result.resolved_terms]
    assert canonical_matches.count("Gross Bookings") <= 1


def test_extract_candidates_abbreviations(resolver):
    """_extract_candidates picks up uppercase abbreviations."""
    candidates = resolver._extract_candidates("What's the GBs in EMEA?")
    candidate_lower = [c.lower() for c in candidates]
    assert "gbs" in candidate_lower
    assert "emea" in candidate_lower


def test_extract_candidates_quoted(resolver):
    """_extract_candidates picks up quoted terms."""
    candidates = resolver._extract_candidates('Look up "Gross Bookings" please')
    assert "Gross Bookings" in candidates


def test_extract_candidates_filters_stop_words(resolver):
    """_extract_candidates filters out stop words."""
    candidates = resolver._extract_candidates("what is the target")
    candidate_lower = [c.lower() for c in candidates]
    assert "what" not in candidate_lower
    assert "the" not in candidate_lower
    assert "target" in candidate_lower
```

- [ ] **Step 6: Run all resolver tests**

Run: `python -m pytest tests/glossary/test_resolver.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
git add src/pam/glossary/resolver.py tests/glossary/test_resolver.py
git commit -m "feat(glossary): add AliasResolver for query expansion"
```

---

## Task 7: REST API Routes

**Files:**
- Create: `src/pam/api/routes/glossary.py`

- [ ] **Step 1: Create the glossary routes**

Create `src/pam/api/routes/glossary.py`:

```python
"""Glossary CRUD REST endpoints."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from pam.api.auth import get_current_user
from pam.api.rate_limit import limiter
from pam.common.config import settings
from pam.common.models import (
    GlossaryResolveResult,
    GlossarySearchResult,
    GlossaryTermCreate,
    GlossaryTermResponse,
    GlossaryTermUpdate,
    User,
)

router = APIRouter()


def get_glossary_service():
    """Dependency stub -- overridden at app startup."""
    raise RuntimeError("GlossaryService not initialized")


@router.post("", response_model=GlossaryTermResponse, status_code=201)
@limiter.limit(settings.rate_limit_default)
async def add_term(
    request: Request,  # noqa: ARG001
    body: GlossaryTermCreate,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Add a new glossary term.

    Returns 409 if a semantically similar term already exists.
    """
    try:
        return await glossary_service.add(
            canonical=body.canonical,
            aliases=body.aliases,
            definition=body.definition,
            category=body.category,
            metadata=body.metadata,
            project_id=body.project_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/search", response_model=list[GlossarySearchResult])
@limiter.limit(settings.rate_limit_search)
async def search_terms(
    request: Request,  # noqa: ARG001
    query: str,
    project_id: uuid.UUID | None = None,
    category: str | None = None,
    top_k: int = Query(default=10, ge=1, le=50),
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Semantic search across glossary terms."""
    return await glossary_service.search(
        query=query,
        project_id=project_id,
        category=category,
        top_k=top_k,
    )


@router.post("/resolve", response_model=GlossaryResolveResult)
@limiter.limit(settings.rate_limit_search)
async def resolve_aliases(
    request: Request,  # noqa: ARG001
    query: str,
    project_id: uuid.UUID | None = None,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Resolve aliases in a query string to canonical glossary terms.

    Returns the expanded query with resolved terms noted.
    """
    from pam.glossary.resolver import AliasResolver

    resolver = AliasResolver(
        store=glossary_service._store,
        project_id=project_id,
    )
    result = await resolver.resolve(query=query, project_id=project_id)
    return GlossaryResolveResult(
        original_query=result.original_query,
        expanded_query=result.expanded_query,
        resolved_terms=result.resolved_terms,
    )


@router.get("", response_model=list[GlossaryTermResponse])
@limiter.limit(settings.rate_limit_default)
async def list_terms(
    request: Request,  # noqa: ARG001
    project_id: uuid.UUID | None = None,
    category: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """List glossary terms, optionally filtered by project and category."""
    return await glossary_service.list_terms(
        project_id=project_id,
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/{term_id}", response_model=GlossaryTermResponse)
@limiter.limit(settings.rate_limit_default)
async def get_term(
    request: Request,  # noqa: ARG001
    term_id: uuid.UUID,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Get a specific glossary term by ID."""
    result = await glossary_service.get(term_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return result


@router.patch("/{term_id}", response_model=GlossaryTermResponse)
@limiter.limit(settings.rate_limit_default)
async def update_term(
    request: Request,  # noqa: ARG001
    term_id: uuid.UUID,
    body: GlossaryTermUpdate,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Update a glossary term's fields."""
    result = await glossary_service.update(
        term_id=term_id,
        canonical=body.canonical,
        aliases=body.aliases,
        definition=body.definition,
        category=body.category,
        metadata=body.metadata,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return result


@router.delete("/{term_id}")
@limiter.limit(settings.rate_limit_default)
async def delete_term(
    request: Request,  # noqa: ARG001
    term_id: uuid.UUID,
    glossary_service=Depends(get_glossary_service),
    _user: User | None = Depends(get_current_user),
):
    """Delete a glossary term."""
    deleted = await glossary_service.delete(term_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Glossary term not found")
    return {"message": "Glossary term deleted", "id": str(term_id)}
```

- [ ] **Step 2: Verify syntax**

Run: `python -m py_compile src/pam/api/routes/glossary.py`
Expected: No output (clean compile)

- [ ] **Step 3: Commit**

```bash
git add src/pam/api/routes/glossary.py
git commit -m "feat(glossary): add REST API routes for glossary CRUD + resolve"
```

---

## Task 8: App Startup Wiring

**Files:**
- Modify: `src/pam/api/main.py`
- Modify: `src/pam/mcp/services.py`

- [ ] **Step 1: Add glossary_service to PamServices**

In `src/pam/mcp/services.py`, add to the TYPE_CHECKING imports:

```python
    from pam.glossary.service import GlossaryService
```

Add field to PamServices dataclass (after `conversation_service`):

```python
    glossary_service: GlossaryService | None
```

Update `from_app_state()` to include:

```python
        glossary_service=getattr(app_state, "glossary_service", None),
```

- [ ] **Step 2: Wire GlossaryService in main.py lifespan**

In `src/pam/api/main.py`, update the routes import to include `glossary`:

```python
from pam.api.routes import admin, auth, chat, conversation, documents, glossary, graph, ingest, memory, search
```

In the lifespan function, add after the Conversation Service block (after the `except Exception:` that catches conversation init failures):

```python
    # --- Glossary Service ---
    try:
        from pam.glossary.service import GlossaryService

        glossary_service = await GlossaryService.create_from_settings(
            session_factory=session_factory,
            es_client=app.state.es_client,
            embedder=app.state.embedder,
            settings=settings,
        )
        app.state.glossary_service = glossary_service
        logger.info("glossary_service_initialized")
    except Exception:
        app.state.glossary_service = None
        logger.warning("glossary_service_init_failed", exc_info=True)
```

In `create_app()`, add the router after the conversation router:

```python
    app.include_router(glossary.router, prefix="/api/glossary", tags=["glossary"])
```

Add the dependency override after the conversation override block:

```python
    # Override the glossary service dependency
    from pam.api.routes.glossary import get_glossary_service as _get_glossary_svc

    def _glossary_svc_override():
        svc = getattr(app.state, "glossary_service", None)
        if svc is None:
            raise RuntimeError("GlossaryService not initialized")
        return svc

    app.dependency_overrides[_get_glossary_svc] = _glossary_svc_override
```

- [ ] **Step 3: Verify the app compiles**

Run: `python -c "from pam.api.main import create_app; print('OK')"`
Expected: `OK` (may fail if env vars are missing, but no import errors)

- [ ] **Step 4: Commit**

```bash
git add src/pam/api/main.py src/pam/mcp/services.py
git commit -m "feat(glossary): wire GlossaryService into app startup and DI"
```

---

## Task 9: MCP Tools + Resource

**Files:**
- Modify: `src/pam/mcp/server.py`

- [ ] **Step 1: Add glossary tool registration call**

In `create_mcp_server()`, add a call to `_register_glossary_tools(mcp)` before `_register_resources(mcp)`:

```python
    _register_glossary_tools(mcp)
```

Update the instructions string to mention glossary:

```python
    mcp = FastMCP(
        "PAM Context",
        instructions=(
            "Business Knowledge Layer for LLMs -- search documents, query knowledge graph, "
            "trigger ingestion, store and recall memories, manage domain glossary"
        ),
    )
```

- [ ] **Step 2: Add the glossary tool registration function**

Add before `_register_resources`:

```python
def _register_glossary_tools(mcp: FastMCP) -> None:
    """Register glossary MCP tools."""

    @mcp.tool()
    async def pam_glossary_add(
        canonical: str,
        definition: str,
        category: str = "concept",
        aliases: list[str] | None = None,
        project_id: str | None = None,
    ) -> str:
        """Add a new term to PAM's glossary.

        Stores a domain term with its canonical name, definition, aliases, and category.
        Deduplicates: if a semantically similar term exists, returns an error.

        category: metric, team, product, acronym, concept, or other.
        aliases: alternative names/abbreviations (e.g., ["GBs", "gross books"]).
        """
        return await _pam_glossary_add(
            canonical=canonical,
            definition=definition,
            category=category,
            aliases=aliases,
            project_id=project_id,
        )

    @mcp.tool()
    async def pam_glossary_search(
        query: str,
        top_k: int = 10,
        project_id: str | None = None,
        category: str | None = None,
    ) -> str:
        """Search PAM's glossary for domain terminology.

        Returns terms ranked by semantic similarity to the query.
        """
        return await _pam_glossary_search(
            query=query,
            top_k=top_k,
            project_id=project_id,
            category=category,
        )

    @mcp.tool()
    async def pam_glossary_resolve(
        query: str,
        project_id: str | None = None,
    ) -> str:
        """Resolve aliases in a query string using PAM's glossary.

        Expands abbreviations and aliases to their canonical forms.
        Example: "What's the GBs target?" expands GBs to Gross Bookings.
        """
        return await _pam_glossary_resolve(query=query, project_id=project_id)
```

- [ ] **Step 3: Add the implementation functions**

Add after the `_register_glossary_tools` function:

```python
async def _pam_glossary_add(
    canonical: str,
    definition: str,
    category: str = "concept",
    aliases: list[str] | None = None,
    project_id: str | None = None,
) -> str:
    """Implementation of pam_glossary_add."""
    import uuid as uuid_mod

    services = get_services()
    if services.glossary_service is None:
        return json.dumps({"error": "Glossary service is unavailable"})

    try:
        parsed_project_id = uuid_mod.UUID(project_id) if project_id else None
    except ValueError:
        return json.dumps({"error": f"Invalid project_id: {project_id}"})

    try:
        result = await services.glossary_service.add(
            canonical=canonical,
            definition=definition,
            category=category,
            aliases=aliases or [],
            project_id=parsed_project_id,
        )
    except ValueError as exc:
        return json.dumps({"error": str(exc)})

    return json.dumps(
        {
            "id": str(result.id),
            "canonical": result.canonical,
            "aliases": result.aliases,
            "definition": result.definition,
            "category": result.category,
            "created_at": result.created_at.isoformat() if result.created_at else None,
        },
        indent=2,
    )


async def _pam_glossary_search(
    query: str,
    top_k: int = 10,
    project_id: str | None = None,
    category: str | None = None,
) -> str:
    """Implementation of pam_glossary_search."""
    import uuid as uuid_mod

    services = get_services()
    if services.glossary_service is None:
        return json.dumps({"error": "Glossary service is unavailable"})

    try:
        parsed_project_id = uuid_mod.UUID(project_id) if project_id else None
    except ValueError:
        return json.dumps({"error": f"Invalid project_id: {project_id}"})

    results = await services.glossary_service.search(
        query=query,
        project_id=parsed_project_id,
        category=category,
        top_k=top_k,
    )

    return json.dumps(
        {
            "terms": [
                {
                    "id": str(r.term.id),
                    "canonical": r.term.canonical,
                    "aliases": r.term.aliases,
                    "definition": r.term.definition,
                    "category": r.term.category,
                    "score": r.score,
                }
                for r in results
            ],
            "count": len(results),
        },
        indent=2,
    )


async def _pam_glossary_resolve(
    query: str,
    project_id: str | None = None,
) -> str:
    """Implementation of pam_glossary_resolve."""
    import uuid as uuid_mod

    services = get_services()
    if services.glossary_service is None:
        return json.dumps({"error": "Glossary service is unavailable"})

    try:
        parsed_project_id = uuid_mod.UUID(project_id) if project_id else None
    except ValueError:
        return json.dumps({"error": f"Invalid project_id: {project_id}"})

    from pam.glossary.resolver import AliasResolver

    resolver = AliasResolver(
        store=services.glossary_service._store,
        project_id=parsed_project_id,
    )
    result = await resolver.resolve(query=query, project_id=parsed_project_id)

    return json.dumps(
        {
            "original_query": result.original_query,
            "expanded_query": result.expanded_query,
            "resolved_terms": result.resolved_terms,
        },
        indent=2,
    )
```

- [ ] **Step 4: Add pam://glossary resource**

In the `_register_resources` function, add after the existing entity resources:

```python
    @mcp.resource("pam://glossary")
    async def glossary_resource() -> str:
        """Domain glossary -- curated terminology with aliases and definitions."""
        return await _get_glossary()
```

Add the implementation function:

```python
async def _get_glossary() -> str:
    """Implementation of pam://glossary resource."""
    services = get_services()
    if services.glossary_service is None:
        return json.dumps({"terms": [], "error": "Glossary service is unavailable"})

    terms = await services.glossary_service.list_terms(limit=100)

    return json.dumps(
        {
            "terms": [
                {
                    "canonical": t.canonical,
                    "aliases": t.aliases,
                    "definition": t.definition,
                    "category": t.category,
                }
                for t in terms
            ],
            "count": len(terms),
        },
        indent=2,
    )
```

- [ ] **Step 5: Verify syntax**

Run: `python -m py_compile src/pam/mcp/server.py`
Expected: No output (clean compile)

- [ ] **Step 6: Commit**

```bash
git add src/pam/mcp/server.py
git commit -m "feat(glossary): add MCP tools pam_glossary_add/search/resolve + pam://glossary resource"
```

---

## Task 10: Context Assembly Integration

**Files:**
- Modify: `src/pam/agent/context_assembly.py`
- Test: `tests/glossary/test_service.py` (add context tests)

- [ ] **Step 1: Write the failing test**

Add to `tests/glossary/test_service.py`:

```python
def test_context_budget_includes_glossary():
    """ContextBudget has a glossary_tokens field."""
    from pam.agent.context_assembly import ContextBudget

    budget = ContextBudget()
    assert hasattr(budget, "glossary_tokens")
    assert budget.glossary_tokens > 0


def test_assembled_context_includes_glossary():
    """AssembledContext has glossary_tokens_used field."""
    from pam.agent.context_assembly import AssembledContext

    ctx = AssembledContext(
        text="test",
        entity_tokens_used=0,
        relationship_tokens_used=0,
        chunk_tokens_used=0,
        total_tokens=0,
        glossary_tokens_used=100,
    )
    assert ctx.glossary_tokens_used == 100
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/glossary/test_service.py::test_context_budget_includes_glossary -v`
Expected: FAIL with `AttributeError`

- [ ] **Step 3: Add glossary_tokens to ContextBudget**

In `src/pam/agent/context_assembly.py`, update `ContextBudget`:

```python
@dataclass
class ContextBudget:
    """Token budget configuration for context assembly."""

    entity_tokens: int = 4000
    relationship_tokens: int = 6000
    max_total_tokens: int = 17000
    max_item_tokens: int = 500
    memory_tokens: int = 2000
    conversation_tokens: int = 2000
    glossary_tokens: int = 1000
```

- [ ] **Step 4: Add glossary_tokens_used to AssembledContext**

```python
@dataclass
class AssembledContext:
    """Result of the context assembly pipeline."""

    text: str
    entity_tokens_used: int
    relationship_tokens_used: int
    chunk_tokens_used: int
    total_tokens: int
    memory_tokens_used: int = 0
    conversation_tokens_used: int = 0
    glossary_tokens_used: int = 0
```

- [ ] **Step 5: Update _build_context_string to accept glossary**

Add `glossary_terms: list[dict] | None = None` parameter. Add detection:

```python
    has_glossary = bool(glossary_terms)
```

Update the all-empty check to include `has_glossary`. Add to summary_bits:

```python
    if has_glossary:
        summary_bits.append(f"{len(glossary_terms)} glossary terms")
```

Add glossary section rendering (after User Memories, before Recent Conversation):

```python
    # --- Glossary Terms ---
    if has_glossary:
        parts.append("## Domain Glossary")
        for g in glossary_terms:
            canonical = g.get("canonical", "")
            definition = g.get("definition", "")
            aliases = g.get("aliases", [])
            alias_str = f" (aka {', '.join(aliases)})" if aliases else ""
            parts.append(f"- **{canonical}**{alias_str}: {definition}")
        parts.append("")
```

- [ ] **Step 6: Update assemble_context to handle glossary**

Add `glossary_results: list[dict] | None = None` parameter. After conversation truncation, add:

```python
    # ---- Glossary truncation ----
    glossary_results = glossary_results or []
    glossary_sorted = sorted(glossary_results, key=lambda x: x.get("score", 0), reverse=True)
    glossary_truncated, glossary_tokens_used, _ = truncate_list_by_token_budget(
        glossary_sorted, "definition", budget.glossary_tokens, budget.max_item_tokens,
    )
```

Update chunk_budget to subtract glossary tokens:

```python
    chunk_budget = _calculate_chunk_budget(
        budget.max_total_tokens - memory_tokens_used - conversation_tokens_used - glossary_tokens_used,
        budget.entity_tokens,
        budget.relationship_tokens,
        entity_tokens_used,
        relationship_tokens_used,
    )
```

Pass `glossary_terms=glossary_truncated if glossary_truncated else None` to `_build_context_string`.

Update total_tokens:

```python
    total_tokens = (
        entity_tokens_used + relationship_tokens_used + chunk_tokens_used
        + memory_tokens_used + conversation_tokens_used + glossary_tokens_used
    )
```

Add glossary to the logger.debug call and set `glossary_tokens_used` in the return.

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/glossary/test_service.py::test_context_budget_includes_glossary tests/glossary/test_service.py::test_assembled_context_includes_glossary -v`
Expected: PASS

- [ ] **Step 8: Run existing context assembly tests for regressions**

Run: `python -m pytest tests/test_agent/test_context_assembly.py -v`
Expected: All PASS (existing callers don't pass `glossary_results`, default `None` is used)

- [ ] **Step 9: Commit**

```bash
git add src/pam/agent/context_assembly.py tests/glossary/test_service.py
git commit -m "feat(glossary): add glossary token budget and section to context assembly"
```

---

## Task 11: Agent Integration (Query Expansion Before Search)

**Files:**
- Modify: `src/pam/agent/agent.py`
- Modify: `src/pam/api/deps.py`

- [ ] **Step 1: Add glossary_service to RetrievalAgent**

In `src/pam/agent/agent.py`, add to TYPE_CHECKING imports:

```python
    from pam.glossary.service import GlossaryService
```

Add `glossary_service` parameter to `__init__` (after the last existing optional parameter):

```python
        glossary_service: GlossaryService | None = None,
```

Store it:

```python
        self.glossary_service = glossary_service
```

- [ ] **Step 2: Add alias resolution to _smart_search**

In the `_smart_search` method, add alias resolution after Step A (keyword extraction) and before Step A2 (mode classification). Insert:

```python
        # Step A1: Resolve glossary aliases
        resolved_terms: list[dict] = []
        if self.glossary_service is not None:
            try:
                from pam.glossary.resolver import AliasResolver

                resolver = AliasResolver(store=self.glossary_service._store)
                resolved = await resolver.resolve(query)
                if resolved.resolved_terms:
                    resolved_terms = resolved.resolved_terms
                    # Enhance ES query with canonical terms for better BM25 recall
                    expansions = [rt["canonical"] for rt in resolved_terms
                                  if rt["matched"].lower() != rt["canonical"].lower()]
                    if expansions:
                        query = f"{query} {' '.join(expansions)}"
                        logger.info("smart_search_query_expanded", expansions=expansions)
            except Exception:
                logger.warning("smart_search_alias_resolution_failed", exc_info=True)
```

- [ ] **Step 3: Pass glossary results to context assembly**

In `_smart_search`, find where `assemble_context` is called. Before that call, add:

```python
            # Fetch relevant glossary terms for context
            glossary_context: list[dict] = []
            if resolved_terms:
                for rt in resolved_terms:
                    glossary_context.append({
                        "canonical": rt["canonical"],
                        "definition": rt.get("definition", ""),
                        "aliases": [],
                        "score": 1.0,
                    })
```

Then add `glossary_results=glossary_context if glossary_context else None` to the `assemble_context()` call.

- [ ] **Step 4: Wire glossary_service in agent dependency**

In `src/pam/api/deps.py`, find the function that creates the agent (likely `get_agent`). Add `glossary_service` to the agent constructor call:

```python
    glossary_service=getattr(request.app.state, "glossary_service", None),
```

- [ ] **Step 5: Run existing agent tests for regressions**

Run: `python -m pytest tests/test_agent/ -v --no-header 2>&1 | tail -20`
Expected: All existing tests PASS (glossary_service defaults to None)

- [ ] **Step 6: Commit**

```bash
git add src/pam/agent/agent.py src/pam/api/deps.py
git commit -m "feat(glossary): integrate alias resolution into agent smart_search"
```

---

## Task 12: Module Exports + Final Verification

**Files:**
- Modify: `src/pam/glossary/__init__.py`

- [ ] **Step 1: Update __init__.py with re-exports**

```python
"""Glossary / Semantic Metadata Layer -- curated domain terminology."""

from pam.glossary.resolver import AliasResolver
from pam.glossary.service import GlossaryService
from pam.glossary.store import GlossaryStore

__all__ = ["AliasResolver", "GlossaryService", "GlossaryStore"]
```

- [ ] **Step 2: Run the full test suite**

Run: `python -m pytest tests/ -v --no-header 2>&1 | tail -40`
Expected: All tests PASS

- [ ] **Step 3: Run linting**

Run: `ruff check src/pam/glossary/ tests/glossary/ src/pam/api/routes/glossary.py`
Expected: No errors (or fix any that appear)

- [ ] **Step 4: Verify the app starts cleanly**

Run: `python -c "from pam.api.main import create_app; app = create_app(); print('App created:', app.title)"`
Expected: `App created: PAM Context API`

- [ ] **Step 5: Final commit**

```bash
git add src/pam/glossary/__init__.py
git commit -m "feat(glossary): add module re-exports and finalize Phase 4"
```
