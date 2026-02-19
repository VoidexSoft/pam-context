"""Tests for GET /api/graph/status endpoint."""

from unittest.mock import AsyncMock, MagicMock


class TestGraphStatusEndpoint:
    async def test_graph_status_connected(self, app, client):
        """Happy path: Neo4j returns entity counts and last sync time."""
        # Build a mock graph_service with a mock Neo4j driver session
        mock_session = AsyncMock()

        # Entity count query result
        entity_data = [
            {"labels": ["Entity", "Person"], "count": 5},
            {"labels": ["Entity", "Technology"], "count": 3},
        ]
        # Last sync query result
        sync_record = {"last_sync": "2026-02-19T12:00:00Z"}

        mock_result_entities = AsyncMock()
        mock_result_entities.data = AsyncMock(return_value=entity_data)

        mock_result_sync = AsyncMock()
        mock_result_sync.single = AsyncMock(return_value=sync_record)

        mock_session.run = AsyncMock(side_effect=[mock_result_entities, mock_result_sync])

        # Build the driver context manager chain
        mock_driver = MagicMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_graphiti_client = MagicMock()
        mock_graphiti_client.driver = mock_driver

        mock_graph_service = MagicMock()
        mock_graph_service.client = mock_graphiti_client

        app.state.graph_service = mock_graph_service

        response = await client.get("/api/graph/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["entity_counts"]["Person"] == 5
        assert data["entity_counts"]["Technology"] == 3
        assert data["total_entities"] == 8
        assert data["last_sync_time"] == "2026-02-19T12:00:00Z"

    async def test_graph_status_connected_no_sync(self, app, client):
        """Connected but no episodic nodes -- last_sync_time is null."""
        mock_session = AsyncMock()

        entity_data = []
        sync_record = {"last_sync": None}

        mock_result_entities = AsyncMock()
        mock_result_entities.data = AsyncMock(return_value=entity_data)

        mock_result_sync = AsyncMock()
        mock_result_sync.single = AsyncMock(return_value=sync_record)

        mock_session.run = AsyncMock(side_effect=[mock_result_entities, mock_result_sync])

        mock_driver = MagicMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_graphiti_client = MagicMock()
        mock_graphiti_client.driver = mock_driver

        mock_graph_service = MagicMock()
        mock_graph_service.client = mock_graphiti_client

        app.state.graph_service = mock_graph_service

        response = await client.get("/api/graph/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["entity_counts"] == {}
        assert data["total_entities"] == 0
        assert data["last_sync_time"] is None

    async def test_graph_status_disconnected(self, app, client):
        """Neo4j session raises an exception -- returns disconnected status."""
        mock_driver = MagicMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(
            side_effect=ConnectionError("Neo4j unreachable")
        )
        mock_driver.session.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_graphiti_client = MagicMock()
        mock_graphiti_client.driver = mock_driver

        mock_graph_service = MagicMock()
        mock_graph_service.client = mock_graphiti_client

        app.state.graph_service = mock_graph_service

        response = await client.get("/api/graph/status")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        assert "error" in data
