"""Tests for GET /api/health endpoint."""

from unittest.mock import AsyncMock, patch

PATCH_REDIS = "pam.api.main.ping_redis"


class TestHealthEndpoint:
    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_all_services_up(self, mock_redis, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "up"
        assert data["services"]["redis"] == "up"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_es_down(self, mock_redis, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_es_exception(self, mock_redis, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(side_effect=ConnectionError("refused"))
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=True)
    async def test_health_pg_down(self, mock_redis, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg connection failed"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "down"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=False)
    async def test_health_all_services_down(self, mock_redis, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg down"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "down"
        assert data["services"]["redis"] == "down"

    @patch(PATCH_REDIS, new_callable=AsyncMock, return_value=False)
    async def test_health_redis_down(self, mock_redis, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "up"
        assert data["services"]["redis"] == "down"
