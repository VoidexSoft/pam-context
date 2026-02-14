"""Tests for the async Neo4j GraphClient wrapper."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from pam.common.graph import GraphClient


@pytest.fixture
def graph_client():
    return GraphClient(
        uri="bolt://localhost:7687",
        user="neo4j",
        password="test_password",
        database="neo4j",
    )


class TestGraphClientConnect:
    async def test_connect_initializes_driver(self, graph_client):
        mock_driver = AsyncMock()
        with patch("pam.common.graph.AsyncGraphDatabase.driver", return_value=mock_driver) as mock_factory:
            await graph_client.connect()
            mock_factory.assert_called_once_with("bolt://localhost:7687", auth=("neo4j", "test_password"))
            mock_driver.verify_connectivity.assert_awaited_once()

    async def test_close_releases_driver(self, graph_client):
        mock_driver = AsyncMock()
        with patch("pam.common.graph.AsyncGraphDatabase.driver", return_value=mock_driver):
            await graph_client.connect()
            await graph_client.close()
            mock_driver.close.assert_awaited_once()
            assert graph_client._driver is None

    async def test_close_when_not_connected_is_noop(self, graph_client):
        await graph_client.close()  # Should not raise

    async def test_driver_property_raises_if_not_connected(self, graph_client):
        with pytest.raises(RuntimeError, match="not connected"):
            _ = graph_client.driver


class TestGraphClientQueries:
    @pytest.fixture
    async def connected_client(self, graph_client):
        mock_driver = AsyncMock()
        mock_session = AsyncMock()
        mock_result = AsyncMock()
        mock_result.data.return_value = [{"ok": 1}]
        mock_session.run.return_value = mock_result
        mock_session.__aenter__.return_value = mock_session
        # driver.session() is a sync call returning an async context manager
        mock_driver.session = MagicMock(return_value=mock_session)
        with patch("pam.common.graph.AsyncGraphDatabase.driver", return_value=mock_driver):
            await graph_client.connect()
        graph_client._mock_session = mock_session
        graph_client._mock_result = mock_result
        return graph_client

    async def test_execute_read(self, connected_client):
        result = await connected_client.execute_read("RETURN 1 AS ok")
        assert result == [{"ok": 1}]
        connected_client._mock_session.run.assert_awaited_once_with("RETURN 1 AS ok", {})

    async def test_execute_read_with_parameters(self, connected_client):
        await connected_client.execute_read("MATCH (n) WHERE n.name = $name RETURN n", {"name": "test"})
        connected_client._mock_session.run.assert_awaited_once_with(
            "MATCH (n) WHERE n.name = $name RETURN n", {"name": "test"}
        )

    async def test_execute_write(self, connected_client):
        result = await connected_client.execute_write("CREATE (n:Test {name: 'test'}) RETURN n")
        assert result == [{"ok": 1}]

    async def test_health_check_returns_true_when_healthy(self, connected_client):
        assert await connected_client.health_check() is True

    async def test_health_check_returns_false_on_error(self, graph_client):
        mock_driver = AsyncMock()
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.run.side_effect = Exception("Connection refused")
        mock_driver.session = MagicMock(return_value=mock_session)
        with patch("pam.common.graph.AsyncGraphDatabase.driver", return_value=mock_driver):
            await graph_client.connect()
        assert await graph_client.health_check() is False
