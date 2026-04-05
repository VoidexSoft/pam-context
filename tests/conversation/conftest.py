"""Fixtures for conversation tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.conversation.service import ConversationService


@pytest.fixture
def mock_session():
    """Mock async database session."""
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    """Mock session factory returning mock_session as context manager."""
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx
    return factory


@pytest.fixture
def conversation_service(mock_session_factory):
    """ConversationService with mocked session factory."""
    return ConversationService(session_factory=mock_session_factory)
