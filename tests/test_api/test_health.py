"""Tests for GET /api/health endpoint."""

from unittest.mock import AsyncMock, MagicMock


class TestHealthEndpoint:
    async def test_health_all_services_up(self, app, client, mock_api_es_client, mock_api_db_session):
        # Set redis_client on app.state for health check
        mock_redis = AsyncMock()
        mock_redis.ping = AsyncMock(return_value=True)
        app.state.redis_client = mock_redis

        # Set graph_service on app.state for Neo4j health check
        mock_neo4j_session = AsyncMock()
        mock_neo4j_session.run = AsyncMock()
        mock_driver = MagicMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_neo4j_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)
        mock_graphiti_client = MagicMock()
        mock_graphiti_client.driver = mock_driver
        mock_graph_service = MagicMock()
        mock_graph_service.client = mock_graphiti_client
        app.state.graph_service = mock_graph_service

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
        # Neo4j not available
        app.state.graph_service = None

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
