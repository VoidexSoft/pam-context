"""Tests for enhanced change history with graph entity timeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.agent.agent import RetrievalAgent


@pytest.fixture
def mock_graph_query_service():
    service = AsyncMock()
    service.get_entity_history = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    return session


@pytest.fixture
def agent(mock_db_session, mock_graph_query_service):
    return RetrievalAgent(
        search_service=AsyncMock(),
        embedder=AsyncMock(),
        api_key="test-key",
        db_session=mock_db_session,
        graph_query_service=mock_graph_query_service,
    )


def _mock_sync_log(action: str = "created", segments: int = 5):
    log = MagicMock()
    log.created_at = "2026-02-14T10:00:00"
    log.action = action
    log.segments_affected = segments
    log.details = None
    return log


class TestEnhancedChangeHistory:
    async def test_includes_graph_history_when_entity_name_provided(
        self, agent, mock_db_session, mock_graph_query_service
    ):
        # Mock sync_log results
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_mock_sync_log()]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_graph_query_service.get_entity_history.return_value = [
            {"rel_type": "DEFINED_IN", "target_name": "Metrics Guide", "target_label": "Document",
             "valid_from": "2026-01-01", "valid_to": None, "document_title": "Metrics Guide"},
        ]

        result, _ = await agent._get_change_history({"entity_name": "DAU"})
        assert "Document changes" in result
        assert "Entity graph history" in result
        assert "DEFINED_IN" in result
        assert "Metrics Guide" in result

    async def test_no_graph_history_without_entity_name(
        self, agent, mock_db_session, mock_graph_query_service
    ):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_mock_sync_log()]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result, _ = await agent._get_change_history({"limit": 10})
        assert "Entity graph history" not in result
        mock_graph_query_service.get_entity_history.assert_not_awaited()

    async def test_no_graph_history_without_graph_service(self, mock_db_session):
        agent = RetrievalAgent(
            search_service=AsyncMock(),
            embedder=AsyncMock(),
            api_key="test-key",
            db_session=mock_db_session,
            graph_query_service=None,
        )
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_mock_sync_log()]
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        result, _ = await agent._get_change_history({"entity_name": "DAU"})
        assert "Entity graph history" not in result

    async def test_graph_history_failure_doesnt_block(
        self, agent, mock_db_session, mock_graph_query_service
    ):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [_mock_sync_log()]
        mock_db_session.execute = AsyncMock(return_value=mock_result)
        mock_graph_query_service.get_entity_history.side_effect = Exception("Neo4j down")

        result, _ = await agent._get_change_history({"entity_name": "DAU"})
        assert "Document changes" in result
        assert "Entity graph history" not in result

    async def test_empty_sync_log_with_entity_graph_history(
        self, agent, mock_db_session, mock_graph_query_service
    ):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db_session.execute = AsyncMock(return_value=mock_result)

        mock_graph_query_service.get_entity_history.return_value = [
            {"rel_type": "OWNED_BY", "target_name": "Growth", "target_label": "Team",
             "valid_from": "2026-01-15", "valid_to": "2026-02-01", "document_title": None},
        ]

        result, _ = await agent._get_change_history({"entity_name": "DAU"})
        assert "No document change history" in result
        assert "Entity graph history" in result
        assert "OWNED_BY" in result
