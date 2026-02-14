"""Tests for the Redis cache layer."""

import json
import uuid
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
        return CacheService(mock_redis)

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
            yield  # noqa: F841 - make it an async generator

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
        return CacheService(mock_redis)

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
