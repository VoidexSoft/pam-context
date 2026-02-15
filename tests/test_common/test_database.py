"""Tests for pam.common.database — Async engine, session factory, and get_db."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pam.common.database import get_db, get_engine, get_session_factory, reset_database


class TestEngineConfiguration:
    def test_pool_size(self):
        """Engine should be created with pool_size=5."""
        engine = get_engine()
        assert engine.pool.size() == 5

    def test_max_overflow(self):
        """Engine should be created with max_overflow=10."""
        engine = get_engine()
        assert engine.pool._max_overflow == 10

    def test_echo_disabled(self):
        """Engine should have echo=False for production use."""
        engine = get_engine()
        assert engine.echo is False


class TestSessionFactory:
    def test_session_class_is_async_session(self):
        """Factory should produce AsyncSession instances."""
        factory = get_session_factory()
        assert factory.class_ is AsyncSession

    def test_expire_on_commit_is_false(self):
        """Factory should disable expire_on_commit to allow post-commit attribute access."""
        factory = get_session_factory()
        assert factory.kw.get("expire_on_commit") is False


class TestResetDatabase:
    def test_reset_clears_caches(self):
        """reset_database should clear both engine and session factory caches."""
        # Ensure caches are populated
        get_engine()
        get_session_factory()

        # Check cache info before reset
        assert get_engine.cache_info().currsize == 1
        assert get_session_factory.cache_info().currsize == 1

        reset_database()

        assert get_engine.cache_info().currsize == 0
        assert get_session_factory.cache_info().currsize == 0


class TestGetDb:
    @pytest.mark.asyncio
    async def test_yields_session(self):
        """get_db should yield a session from the factory."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = None

        mock_factory = MagicMock(return_value=mock_context)

        with patch("pam.common.database.get_session_factory", return_value=mock_factory):
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

        with patch("pam.common.database.get_session_factory", return_value=mock_factory):
            gen = get_db()
            await gen.__anext__()
            # Exhaust the generator to trigger cleanup
            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()
            mock_context.__aexit__.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_on_exception(self):
        """get_db should rollback the session if an exception occurs."""
        mock_session = AsyncMock(spec=AsyncSession)
        mock_context = AsyncMock()
        mock_context.__aenter__.return_value = mock_session
        mock_context.__aexit__.return_value = False

        mock_factory = MagicMock(return_value=mock_context)

        with patch("pam.common.database.get_session_factory", return_value=mock_factory):
            gen = get_db()
            await gen.__anext__()
            # Throw an exception into the generator
            with pytest.raises(ValueError):
                await gen.athrow(ValueError("test error"))
            mock_session.rollback.assert_called_once()
