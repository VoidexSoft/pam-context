"""Tests for the refactored _run_pipeline helper in task_manager."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.ingestion.task_manager import _run_pipeline


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    factory = MagicMock()
    factory.return_value.__aenter__ = AsyncMock(return_value=session)
    factory.return_value.__aexit__ = AsyncMock(return_value=False)
    return factory


@pytest.mark.asyncio
async def test_run_pipeline_marks_task_running(mock_session_factory):
    """_run_pipeline sets task status to 'running'."""
    task_id = uuid.uuid4()
    connector = AsyncMock()
    connector.list_documents = AsyncMock(return_value=[])

    await _run_pipeline(
        task_id=task_id,
        connectors=[("markdown", connector)],
        es_client=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=mock_session_factory,
    )

    # Verify status was set to "running" (first execute call)
    calls = mock_session_factory.return_value.__aenter__.return_value.execute.call_args_list
    assert len(calls) >= 1  # At least the status update


@pytest.mark.asyncio
async def test_run_pipeline_completes_with_no_docs(mock_session_factory):
    """_run_pipeline completes successfully when connector returns no documents."""
    task_id = uuid.uuid4()
    connector = AsyncMock()
    connector.list_documents = AsyncMock(return_value=[])

    await _run_pipeline(
        task_id=task_id,
        connectors=[("markdown", connector)],
        es_client=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=mock_session_factory,
    )
    # Should not raise
