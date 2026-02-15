"""Tests for stateless FastAPI dependency injection functions."""

from unittest.mock import MagicMock

from pam.api.deps import (
    get_cache_service,
    get_duckdb_service,
    get_embedder,
    get_es_client,
    get_reranker,
    get_search_service,
)


class TestStatelessDeps:
    def test_get_duckdb_service_returns_from_app_state(self):
        mock_service = MagicMock()
        request = MagicMock()
        request.app.state.duckdb_service = mock_service
        assert get_duckdb_service(request) is mock_service

    def test_get_duckdb_service_returns_none_when_not_set(self):
        request = MagicMock()
        request.app.state.duckdb_service = None
        assert get_duckdb_service(request) is None

    def test_get_embedder_returns_from_app_state(self):
        mock_embedder = MagicMock()
        request = MagicMock()
        request.app.state.embedder = mock_embedder
        assert get_embedder(request) is mock_embedder

    def test_get_search_service_returns_from_app_state(self):
        mock_search = MagicMock()
        request = MagicMock()
        request.app.state.search_service = mock_search
        assert get_search_service(request) is mock_search

    def test_get_es_client_returns_from_app_state(self):
        mock_es = MagicMock()
        request = MagicMock()
        request.app.state.es_client = mock_es
        assert get_es_client(request) is mock_es

    def test_get_reranker_returns_from_app_state(self):
        mock_reranker = MagicMock()
        request = MagicMock()
        request.app.state.reranker = mock_reranker
        assert get_reranker(request) is mock_reranker

    def test_get_reranker_returns_none_when_disabled(self):
        request = MagicMock()
        request.app.state.reranker = None
        assert get_reranker(request) is None

    def test_get_cache_service_returns_from_app_state(self):
        mock_cache = MagicMock()
        request = MagicMock()
        request.app.state.cache_service = mock_cache
        assert get_cache_service(request) is mock_cache

    def test_get_cache_service_returns_none_when_no_redis(self):
        request = MagicMock()
        request.app.state.cache_service = None
        assert get_cache_service(request) is None
