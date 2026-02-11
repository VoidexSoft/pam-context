"""Tests for GET /api/health endpoint."""

from unittest.mock import AsyncMock

import pytest


class TestHealthEndpoint:
    async def test_health_all_services_up(self, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "up"

    async def test_health_es_down(self, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    async def test_health_es_exception(self, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(side_effect=ConnectionError("refused"))
        mock_api_db_session.execute = AsyncMock()

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "up"

    async def test_health_pg_down(self, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=True)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg connection failed"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "up"
        assert data["services"]["postgres"] == "down"

    async def test_health_all_services_down(self, client, mock_api_es_client, mock_api_db_session):
        mock_api_es_client.ping = AsyncMock(return_value=False)
        mock_api_db_session.execute = AsyncMock(side_effect=Exception("pg down"))

        response = await client.get("/api/health")

        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["services"]["elasticsearch"] == "down"
        assert data["services"]["postgres"] == "down"
