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
