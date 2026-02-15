"""Tests for GET /api/health endpoint."""

from unittest.mock import AsyncMock


class TestHealthEndpoint:
    async def test_health_all_services_up(self, app, client, mock_api_es_client, mock_api_db_session):
        # Set redis_client on app.state for health check
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        app.state.redis_client = mock_redis

        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "up"
        assert data["services"]["redis"] == "up"

    async def test_health_es_down(self, app, client, mock_api_es_client, mock_api_db_session):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        app.state.redis_client = mock_redis

        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    async def test_health_es_exception(self, app, client, mock_api_es_client, mock_api_db_session):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        app.state.redis_client = mock_redis

        mock_api_es_client.ping = AsyncMock(side_effect=ConnectionError("refused"))
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    async def test_health_pg_down(self, app, client, mock_api_es_client, mock_api_db_session):
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        app.state.redis_client = mock_redis

        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg connection failed"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "down"

    async def test_health_all_services_down(self, app, client, mock_api_es_client, mock_api_db_session):
        # Redis not available
        app.state.redis_client = None

        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg down"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "down"
        assert data["services"]["redis"] == "down"

    async def test_health_redis_down(self, app, client, mock_api_es_client, mock_api_db_session):
        # Redis client exists but ping fails
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=False)
        app.state.redis_client = mock_redis

        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "up"
        assert data["services"]["redis"] == "down"
