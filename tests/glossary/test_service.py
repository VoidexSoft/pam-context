"""Tests for GlossaryTerm model and schemas."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.common.models import (
    GlossaryTerm,
    GlossaryTermCreate,
)
from pam.glossary.service import GlossaryService


def test_glossary_term_model_has_required_fields():
    """GlossaryTerm ORM model has all expected columns."""
    columns = {c.name for c in GlossaryTerm.__table__.columns}
    expected = {
        "id",
        "project_id",
        "canonical",
        "aliases",
        "definition",
        "category",
        "metadata",
        "created_at",
        "updated_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


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


def test_glossary_config_settings_exist():
    """Config has glossary-related settings."""
    from pam.common.config import Settings

    fields = Settings.model_fields
    assert "glossary_index" in fields
    assert "glossary_dedup_threshold" in fields
    assert "glossary_context_budget" in fields


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
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
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


@pytest.mark.asyncio
async def test_add_term_rejects_empty_definition(mock_session_factory, mock_store, mock_embedder):
    """add() raises ValueError for empty definition."""
    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    with pytest.raises(ValueError, match="Definition cannot be empty"):
        await service.add(canonical="Foo", definition="")


@pytest.mark.asyncio
async def test_add_term_rolls_back_es_on_pg_failure(mock_session_factory, mock_store, mock_embedder):
    """add() deletes ES doc when PG commit fails."""
    mock_store.find_duplicates.return_value = []

    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock(side_effect=RuntimeError("pg down"))
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )

    with pytest.raises(RuntimeError, match="pg down"):
        await service.add(canonical="Foo", definition="Bar definition")

    mock_store.delete.assert_awaited_once()


@pytest.mark.asyncio
async def test_search_returns_empty_when_no_hits(mock_session_factory, mock_store, mock_embedder):
    """search() returns [] when store has no hits."""
    mock_store.search.return_value = []
    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    results = await service.search(query="anything")
    assert results == []


@pytest.mark.asyncio
async def test_search_by_alias_returns_results(mock_session_factory, mock_store, mock_embedder):
    """search_by_alias() returns scored results from keyword match."""
    term_id = uuid.uuid4()
    mock_store.search_by_alias.return_value = [{"term_id": str(term_id), "score": 5.5, "canonical": "GB"}]
    mock_term = GlossaryTerm(
        id=term_id,
        canonical="Gross Bookings",
        aliases=["GBs"],
        definition="Total fare",
        category="metric",
        metadata_={},
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
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
    results = await service.search_by_alias(alias="GBs")
    assert len(results) == 1
    assert results[0].score == 5.5


@pytest.mark.asyncio
async def test_search_by_alias_empty(mock_session_factory, mock_store, mock_embedder):
    """search_by_alias() returns [] when store empty."""
    mock_store.search_by_alias.return_value = []
    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    results = await service.search_by_alias(alias="x")
    assert results == []


@pytest.mark.asyncio
async def test_get_returns_term(mock_session_factory, mock_store, mock_embedder):
    """get() returns the term when found."""
    term_id = uuid.uuid4()
    mock_term = GlossaryTerm(
        id=term_id,
        canonical="Foo",
        aliases=[],
        definition="def",
        category="concept",
        metadata_={},
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = mock_term
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    res = await service.get(term_id)
    assert res is not None
    assert res.canonical == "Foo"


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(mock_session_factory, mock_store, mock_embedder):
    """get() returns None when term absent."""
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
    res = await service.get(uuid.uuid4())
    assert res is None


@pytest.mark.asyncio
async def test_list_terms_with_filters(mock_session_factory, mock_store, mock_embedder):
    """list_terms() applies project_id and category filters."""
    term = GlossaryTerm(
        id=uuid.uuid4(),
        canonical="A",
        aliases=[],
        definition="d",
        category="metric",
        metadata_={},
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [term]
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    results = await service.list_terms(project_id=uuid.uuid4(), category="metric", limit=10, offset=0)
    assert len(results) == 1
    assert results[0].canonical == "A"


@pytest.mark.asyncio
async def test_update_returns_none_when_missing(mock_session_factory, mock_store, mock_embedder):
    """update() returns None when term not found."""
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
    res = await service.update(uuid.uuid4(), canonical="New")
    assert res is None


@pytest.mark.asyncio
async def test_update_reindexes_when_content_changes(mock_session_factory, mock_store, mock_embedder):
    """update() re-embeds and re-indexes when canonical/definition/aliases change."""
    term_id = uuid.uuid4()
    term = GlossaryTerm(
        id=term_id,
        canonical="Old",
        aliases=[],
        definition="old def",
        category="concept",
        metadata_={},
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = term
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    res = await service.update(
        term_id,
        canonical="New",
        aliases=["alt"],
        definition="new def",
        category="metric",
        metadata={"k": "v"},
    )
    assert res is not None
    mock_store.index_term.assert_awaited_once()
    mock_embedder.embed_texts.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_skips_reindex_when_only_metadata_changes(mock_session_factory, mock_store, mock_embedder):
    """update() does not re-index when only metadata/category change."""
    term_id = uuid.uuid4()
    term = GlossaryTerm(
        id=term_id,
        canonical="Same",
        aliases=[],
        definition="same",
        category="concept",
        metadata_={},
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    mock_session = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = term
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    res = await service.update(term_id, category="metric", metadata={"x": 1})
    assert res is not None
    mock_store.index_term.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_returns_true_when_found(mock_session_factory, mock_store, mock_embedder):
    """delete() removes term from PG + ES and returns True."""
    term_id = uuid.uuid4()
    term = GlossaryTerm(
        id=term_id,
        canonical="Foo",
        aliases=[],
        definition="def",
        category="concept",
        metadata_={},
        created_at=datetime.now(tz=UTC),
        updated_at=datetime.now(tz=UTC),
    )
    mock_session = AsyncMock()
    mock_session.delete = AsyncMock()
    mock_session.flush = AsyncMock()
    mock_session.commit = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.first.return_value = term
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    ok = await service.delete(term_id)
    assert ok is True
    mock_store.delete.assert_awaited_once_with(term_id)


def test_create_resolver_returns_alias_resolver(mock_session_factory, mock_store, mock_embedder):
    """create_resolver() returns an AliasResolver bound to the service's store."""
    from pam.glossary.resolver import AliasResolver

    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    resolver = service.create_resolver(min_score=2.0)
    assert isinstance(resolver, AliasResolver)


@pytest.mark.asyncio
async def test_resolve_aliases_delegates_to_resolver(mock_session_factory, mock_store, mock_embedder):
    """resolve_aliases() uses a fresh resolver to resolve the query."""
    mock_store.search_by_alias.return_value = []
    service = GlossaryService(
        session_factory=mock_session_factory,
        store=mock_store,
        embedder=mock_embedder,
    )
    resolved = await service.resolve_aliases("show me GBs", project_id=uuid.uuid4())
    assert resolved.expanded_query == "show me GBs"


@pytest.mark.asyncio
async def test_create_from_settings_builds_service(mock_session_factory, mock_embedder):
    """create_from_settings() wires up a GlossaryStore and returns a service."""
    from unittest.mock import patch

    es_client = AsyncMock()
    settings = MagicMock()
    settings.glossary_index = "glossary_test"
    settings.embedding_dims = 1536
    settings.glossary_dedup_threshold = 0.9

    with patch("pam.glossary.store.GlossaryStore.ensure_index", new=AsyncMock()):
        svc = await GlossaryService.create_from_settings(
            session_factory=mock_session_factory,
            es_client=es_client,
            embedder=mock_embedder,
            settings=settings,
        )
    assert isinstance(svc, GlossaryService)
    assert svc._dedup_threshold == 0.9
