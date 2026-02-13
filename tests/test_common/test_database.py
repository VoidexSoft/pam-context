"""Tests for pam.common.database — Async engine, session factory, and get_db."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pam.common.database import async_session_factory, engine, get_db


class TestEngineConfiguration:
    def test_pool_size(self):
        """Engine should be created with pool_size=5."""
        assert engine.pool.size() == 5

    def test_max_overflow(self):
        """Engine should be created with max_overflow=10."""
        assert engine.pool._max_overflow == 10

    def test_echo_disabled(self):
        """Engine should have echo=False for production use."""
        assert engine.echo is False


class TestSessionFactory:
    def test_session_class_is_async_session(self):
        """Factory should produce AsyncSession instances."""
        assert async_session_factory.class_ is AsyncSession

    def test_expire_on_commit_is_false(self):
        """Factory should disable expire_on_commit to allow post-commit attribute access."""
        assert async_session_factory.kw.get("expire_on_commit") is False


class TestGetDb:
    @pytest.mark.asyncio
    async def test_yields_session(self):
        """get_db should yield a session from the factory."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = None

        mock_factory = MagicMock(return_value=mock_context)

        with patch("pam.common.database.async_session_factory", mock_factory):
            gen = get_db()
            session = await gen.__anext__()
            assert session is mock_session

    @pytest.mark.asyncio
    async def test_closes_session_after_use(self):
        """get_db should close the session context manager after yielding."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = None

        mock_factory = MagicMock(return_value=mock_context)

        with patch("pam.common.database.async_session_factory", mock_factory):
            gen = get_db()
            await gen.__anext__()
            # Exhaust the generator to trigger cleanup
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            mock_context.__aexit__.assert_called_once()
