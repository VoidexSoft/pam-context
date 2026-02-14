"""Tests for GET /api/health endpoint."""

from unittest.mock import AsyncMock, patch

import pytest

PATCH_REDIS = "pam.api.main.ping_redis"


@pytest.fixture
def _mock_neo4j_up(app):
    """Set a mock graph_client on app.state that reports healthy."""
    mock_gc = AsyncMock()
    mock_gc.health_check = AsyncMock(return_value=True)
    app.state.graph_client = mock_gc
    yield
    del app.state.graph_client


@pytest.fixture
def _mock_neo4j_down(app):
    """Set a mock graph_client on app.state that reports unhealthy."""
    mock_gc = AsyncMock()
    mock_gc.health_check = AsyncMock(return_value=False)
    app.state.graph_client = mock_gc
    yield
    del app.state.graph_client


class TestHealthEndpoint:
    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_all_services_up(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session, _mock_neo4j_up
    ):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "up"
        assert data["services"]["redis"] == "up"
        assert data["services"]["neo4j"] == "up"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_es_down(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session, _mock_neo4j_up
    ):
        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_es_exception(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session, _mock_neo4j_up
    ):
        mock_api_es_client.ping = AsyncMock(side_effect=ConnectionError("refused"))
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_pg_down(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session, _mock_neo4j_up
    ):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg connection failed"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "down"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=False)
    async def test_health_all_services_down(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session, _mock_neo4j_down
    ):
        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg down"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "down"
        assert data["services"]["redis"] == "down"
        assert data["services"]["neo4j"] == "down"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=False)
    async def test_health_redis_down(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session, _mock_neo4j_up
    ):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "up"
        assert data["services"]["redis"] == "down"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_neo4j_down(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session, _mock_neo4j_down
    ):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["neo4j"] == "down"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_neo4j_not_configured(
        self, mock_redis, client, mock_api_es_client, mock_api_db_session
    ):
        """When graph_client is not on app.state, neo4j reports as down."""
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        data = response.json()
        assert data["services"]["neo4j"] == "down"
