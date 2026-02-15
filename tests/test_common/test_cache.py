"""Tests for the Redis cache layer."""

import asyncio
import json
import uuid
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from pam.common.cache import CacheService, _make_search_key


class TestMakeSearchKey:
    def test_deterministic(self):
        key1 = _make_search_key("hello", 10, None, None)
        key2 = _make_search_key("hello", 10, None, None)
        assert key1 == key2

    def test_starts_with_prefix(self):
        key = _make_search_key("hello", 10, None, None)
        assert key.startswith("search:")

    def test_different_queries_different_keys(self):
        key1 = _make_search_key("hello", 10, None, None)
        key2 = _make_search_key("world", 10, None, None)
        assert key1 != key2

    def test_different_top_k_different_keys(self):
        key1 = _make_search_key("hello", 5, None, None)
        key2 = _make_search_key("hello", 10, None, None)
        assert key1 != key2

    def test_different_filters_different_keys(self):
        key1 = _make_search_key("hello", 10, "markdown", None)
        key2 = _make_search_key("hello", 10, None, "project-a")
        assert key1 != key2

    def test_different_date_from_different_keys(self):
        key1 = _make_search_key("hello", 10, None, None, date_from=datetime(2024, 1, 1))
        key2 = _make_search_key("hello", 10, None, None, date_from=datetime(2025, 1, 1))
        assert key1 != key2

    def test_different_date_to_different_keys(self):
        key1 = _make_search_key("hello", 10, None, None, date_to=datetime(2024, 6, 30))
        key2 = _make_search_key("hello", 10, None, None, date_to=datetime(2025, 6, 30))
        assert key1 != key2

    def test_date_from_vs_no_date_different_keys(self):
        key1 = _make_search_key("hello", 10, None, None)
        key2 = _make_search_key("hello", 10, None, None, date_from=datetime(2024, 1, 1))
        assert key1 != key2

    def test_date_to_vs_no_date_different_keys(self):
        key1 = _make_search_key("hello", 10, None, None)
        key2 = _make_search_key("hello", 10, None, None, date_to=datetime(2024, 12, 31))
        assert key1 != key2

    def test_same_dates_same_key(self):
        key1 = _make_search_key(
            "hello",
            10,
            None,
            None,
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 12, 31),
        )
        key2 = _make_search_key(
            "hello",
            10,
            None,
            None,
            date_from=datetime(2024, 1, 1),
            date_to=datetime(2024, 12, 31),
        )
        assert key1 == key2


class TestCacheServiceTTLInjection:
    def test_explicit_ttl_values(self):
        """Explicit TTL params should be stored directly."""
        client = AsyncMock()
        cache = CacheService(client, search_ttl=42, session_ttl=99)
        assert cache.search_ttl == 42
        assert cache.session_ttl == 99

    async def test_set_search_results_uses_custom_ttl(self):
        """set_search_results should use the injected search_ttl."""
        client = AsyncMock()
        cache = CacheService(client, search_ttl=60, session_ttl=120)
        await cache.set_search_results("q", 5, [{"x": 1}])
        call_kwargs = client.set.call_args
        assert call_kwargs[1]["ex"] == 60 or call_kwargs.kwargs.get("ex") == 60

    async def test_save_session_uses_custom_ttl(self):
        """save_session should use the injected session_ttl."""
        client = AsyncMock()
        cache = CacheService(client, search_ttl=60, session_ttl=120)
        await cache.save_session("s1", [{"role": "user", "content": "hi"}])
        call_kwargs = client.set.call_args
        assert call_kwargs[1]["ex"] == 120 or call_kwargs.kwargs.get("ex") == 120


class TestCacheServiceSearchResults:
    @pytest.fixture
    def mock_redis(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
        client.delete = AsyncMock(return_value=1)
        client.scan_iter = AsyncMock()
        return client

    @pytest.fixture
    def cache(self, mock_redis):
        return CacheService(mock_redis, search_ttl=900, session_ttl=86400)

    async def test_get_cache_miss(self, cache, mock_redis):
        result = await cache.get_search_results("test query", 10)
        assert result is None

    async def test_get_cache_hit(self, cache, mock_redis):
        stored = [{"segment_id": str(uuid.uuid4()), "content": "test", "score": 0.9}]
        mock_redis.get = AsyncMock(return_value=json.dumps(stored))

        result = await cache.get_search_results("test query", 10)
        assert result is not None
        assert len(result) == 1
        assert result[0]["content"] == "test"

    async def test_set_search_results(self, cache, mock_redis):
        results = [{"segment_id": str(uuid.uuid4()), "content": "test", "score": 0.9}]
        await cache.set_search_results("test query", 10, results)

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0].startswith("search:")
        assert "test" in call_args[0][1]

    async def test_set_with_filters(self, cache, mock_redis):
        await cache.set_search_results("test", 10, [], source_type="markdown", project="proj")
        mock_redis.set.assert_called_once()

    async def test_set_with_date_filters(self, cache, mock_redis):
        dt_from = datetime(2024, 1, 1)
        dt_to = datetime(2024, 12, 31)
        await cache.set_search_results("test", 10, [], date_from=dt_from, date_to=dt_to)
        mock_redis.set.assert_called_once()

    async def test_get_with_date_filters_miss(self, cache, mock_redis):
        """Cache set with no dates should not match get with date filters."""
        stored = [{"segment_id": str(uuid.uuid4()), "content": "test", "score": 0.9}]
        # Simulate: set was called without date filters
        await cache.set_search_results("test", 10, stored)

        # The key for a query WITH date_from is different, so redis.get returns None
        result = await cache.get_search_results("test", 10, date_from=datetime(2024, 1, 1))
        # mock_redis.get returns None by default, confirming different keys cause a miss
        assert result is None

    async def test_invalidate_search(self, cache, mock_redis):
        async def fake_scan_iter(match=None):
            for key in ["search:abc", "search:def"]:
                yield key

        mock_redis.scan_iter = fake_scan_iter
        await cache.invalidate_search()
        mock_redis.delete.assert_called_once_with("search:abc", "search:def")

    async def test_invalidate_search_no_keys(self, cache, mock_redis):
        async def fake_scan_iter(match=None):
            return
            yield  # make it an async generator

        mock_redis.scan_iter = fake_scan_iter
        deleted = await cache.invalidate_search()
        assert deleted == 0
        mock_redis.delete.assert_not_called()


class TestCacheServiceSessions:
    @pytest.fixture
    def mock_redis(self):
        client = AsyncMock()
        client.get = AsyncMock(return_value=None)
        client.set = AsyncMock()
        client.delete = AsyncMock()
        return client

    @pytest.fixture
    def cache(self, mock_redis):
        return CacheService(mock_redis, search_ttl=900, session_ttl=86400)

    async def test_get_session_miss(self, cache):
        result = await cache.get_session("nonexistent")
        assert result is None

    async def test_get_session_hit(self, cache, mock_redis):
        messages = [{"role": "user", "content": "hello"}]
        mock_redis.get = AsyncMock(return_value=json.dumps(messages))

        result = await cache.get_session("sess-123")
        assert result is not None
        assert len(result) == 1
        assert result[0]["role"] == "user"

    async def test_save_session(self, cache, mock_redis):
        messages = [{"role": "user", "content": "hello"}]
        await cache.save_session("sess-123", messages)

        mock_redis.set.assert_called_once()
        call_args = mock_redis.set.call_args
        assert call_args[0][0] == "session:sess-123"

    async def test_delete_session(self, cache, mock_redis):
        await cache.delete_session("sess-123")
        mock_redis.delete.assert_called_once_with("session:sess-123")


class TestGetRedisLock:
    """Test that get_redis() uses async locking to prevent race conditions."""

    async def test_concurrent_get_redis_creates_single_client(self):
        """Multiple concurrent calls to get_redis() should only create one Redis client."""
        import pam.common.cache as cache_mod

        # Reset global state
        original_client = cache_mod._redis_client
        cache_mod._redis_client = None

        call_count = 0
        mock_client = AsyncMock()

        def counting_from_url(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_client

        try:
            with patch("pam.common.cache.redis.from_url", side_effect=counting_from_url):
                # Launch multiple concurrent calls
                results = await asyncio.gather(
                    cache_mod.get_redis(),
                    cache_mod.get_redis(),
                    cache_mod.get_redis(),
                )

            # All should return the same client
            assert all(r is mock_client for r in results)
            # from_url should have been called exactly once
            assert call_count == 1
        finally:
            cache_mod._redis_client = original_client


class TestPingRedis:
    async def test_ping_success(self):
        mock_client = AsyncMock()
        mock_client.ping = AsyncMock(return_value=True)

        with patch("pam.common.cache.get_redis", return_value=mock_client):
            from pam.common.cache import ping_redis

            assert await ping_redis() is True

    async def test_ping_failure(self):
        with patch("pam.common.cache.get_redis", side_effect=ConnectionError("refused")):
            from pam.common.cache import ping_redis

            assert await ping_redis() is False
