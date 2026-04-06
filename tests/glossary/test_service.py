"""Tests for GlossaryTerm model and schemas."""

import pytest

from pam.common.models import GlossaryTerm


def test_glossary_term_model_has_required_fields():
    """GlossaryTerm ORM model has all expected columns."""
    columns = {c.name for c in GlossaryTerm.__table__.columns}
    expected = {
        "id", "project_id", "canonical", "aliases", "definition",
        "category", "metadata", "created_at", "updated_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


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
