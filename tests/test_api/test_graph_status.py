"""Tests for graph endpoints — status, null guards, neighborhood, entities, history."""

from unittest.mock import AsyncMock, MagicMock


def _mock_pg_counts(mock_db, doc_count=5, synced_count=3):
    """Configure db mock for the two PG count queries in graph_status.

    graph_status calls db.execute() twice:
      1. SELECT count(*) FROM document           → doc_count
      2. SELECT count(*) FROM document WHERE ...  → synced_count
    """
    total_result = MagicMock()
    total_result.scalar.return_value = doc_count

    synced_result = MagicMock()
    synced_result.scalar.return_value = synced_count

    mock_db.execute = AsyncMock(side_effect=[total_result, synced_result])


class TestGraphStatusEndpoint:
    async def test_graph_status_connected(self, app, client, mock_api_db_session):
        """Happy path: Neo4j returns entity counts and last sync time."""
        _mock_pg_counts(mock_api_db_session, doc_count=5, synced_count=3)

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
        assert data["document_count"] == 5
        assert data["graph_synced_count"] == 3

    async def test_graph_status_connected_no_sync(self, app, client, mock_api_db_session):
        """Connected but no episodic nodes -- last_sync_time is null."""
        _mock_pg_counts(mock_api_db_session, doc_count=0, synced_count=0)

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
        assert data["document_count"] == 0
        assert data["graph_synced_count"] == 0

    async def test_graph_status_disconnected(self, app, client, mock_api_db_session):
        """Neo4j session raises an exception -- returns disconnected status."""
        _mock_pg_counts(mock_api_db_session, doc_count=8, synced_count=3)

        mock_driver = MagicMock()
        mock_driver.session.return_value.__aenter__ = AsyncMock(side_effect=ConnectionError("Neo4j unreachable"))
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
        assert data["document_count"] == 8
        assert data["graph_synced_count"] == 3


class TestPhase11GraphNullGuards:
    """Phase 11: graph_status unavailable path and null guards on data endpoints."""

    async def test_graph_status_unavailable_returns_pg_counts(self, app, client, mock_api_db_session):
        """graph_service=None → 200 with status=unavailable and PG document counts."""
        _mock_pg_counts(mock_api_db_session, doc_count=10, synced_count=7)
        # app.state.graph_service is already None from conftest

        response = await client.get("/api/graph/status")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unavailable"
        assert data["document_count"] == 10
        assert data["graph_synced_count"] == 7
        assert data["total_entities"] == 0
        assert data["entity_counts"] == {}
        assert data["last_sync_time"] is None

    async def test_neighborhood_503_when_graph_service_none(self, client):
        """graph_service=None on neighborhood endpoint → 503 with structured error."""
        response = await client.get("/api/graph/neighborhood/SomeEntity")
        assert response.status_code == 503
        assert response.json()["detail"] == "Graph service unavailable"

    async def test_entities_503_when_graph_service_none(self, client):
        """graph_service=None on entities endpoint → 503 with structured error."""
        response = await client.get("/api/graph/entities")
        assert response.status_code == 503
        assert response.json()["detail"] == "Graph service unavailable"

    async def test_entity_history_503_when_graph_service_none(self, client):
        """graph_service=None on entity history endpoint → 503 with structured error."""
        response = await client.get("/api/graph/entity/SomeEntity/history")
        assert response.status_code == 503
        assert response.json()["detail"] == "Graph service unavailable"
