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
        "id", "project_id", "canonical", "aliases", "definition",
        "category", "metadata", "created_at", "updated_at",
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
