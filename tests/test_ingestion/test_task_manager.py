"""Tests for background ingestion task manager."""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

from pam.common.models import IngestionTask
from pam.ingestion.pipeline import IngestionResult
from pam.ingestion.task_manager import (
    _running_tasks,
    create_task,
    get_task,
    list_tasks,
    run_ingestion_background,
    spawn_ingestion_task,
)


class TestCreateTask:
    async def test_creates_pending_task(self):
        session = AsyncMock()
        session.add = MagicMock()
        session.commit = AsyncMock()
        session.refresh = AsyncMock()

        task = await create_task("/tmp/docs", session)
        session.add.assert_called_once()
        session.commit.assert_called_once()
        assert isinstance(task, IngestionTask)
        assert task.folder_path == "/tmp/docs"


class TestGetTask:
    async def test_returns_task(self):
        task_id = uuid.uuid4()
        mock_task = MagicMock(spec=IngestionTask)

        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = mock_task
        session.execute.return_value = result_mock

        result = await get_task(task_id, session)
        assert result is mock_task

    async def test_returns_none_when_not_found(self):
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        session.execute.return_value = result_mock

        result = await get_task(uuid.uuid4(), session)
        assert result is None


class TestListTasks:
    async def test_returns_list(self):
        session = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        session.execute.return_value = result_mock

        tasks = await list_tasks(session, limit=10)
        assert tasks == []


class TestRunIngestionBackground:
    @patch("pam.ingestion.task_manager.async_session_factory")
    @patch("pam.ingestion.task_manager.MarkdownConnector")
    @patch("pam.ingestion.task_manager.DoclingParser")
    @patch("pam.ingestion.task_manager.ElasticsearchStore")
    @patch("pam.ingestion.task_manager.IngestionPipeline")
    async def test_successful_run(
        self, mock_pipeline_cls, mock_es_cls, mock_parser_cls, mock_connector_cls, mock_session_factory
    ):
        task_id = uuid.uuid4()

        # Mock sessions
        status_session = AsyncMock()
        pipeline_session = AsyncMock()

        # get_task returns a task with incrementable fields
        mock_task_row = MagicMock()
        mock_task_row.processed_documents = 0
        mock_task_row.succeeded = 0
        mock_task_row.skipped = 0
        mock_task_row.failed = 0
        mock_task_row.results = []

        status_result = MagicMock()
        status_result.scalar_one_or_none.return_value = mock_task_row
        status_session.execute.return_value = status_result
        status_session.commit = AsyncMock()

        # Make async context managers return sessions
        status_cm = AsyncMock()
        status_cm.__aenter__.return_value = status_session
        status_cm.__aexit__.return_value = None

        pipeline_cm = AsyncMock()
        pipeline_cm.__aenter__.return_value = pipeline_session
        pipeline_cm.__aexit__.return_value = None

        call_count = 0

        def session_factory_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return status_cm
            return pipeline_cm

        mock_session_factory.side_effect = session_factory_side_effect

        # Mock connector
        mock_connector = AsyncMock()
        mock_doc_info = MagicMock()
        mock_doc_info.source_id = "doc1.md"
        mock_connector.list_documents.return_value = [mock_doc_info]
        mock_connector_cls.return_value = mock_connector

        # Mock pipeline
        mock_pipeline = AsyncMock()
        mock_pipeline.ingest_all = AsyncMock(
            return_value=[IngestionResult(source_id="doc1.md", title="Doc 1", segments_created=3)]
        )
        mock_pipeline_cls.return_value = mock_pipeline

        es_client = AsyncMock()
        embedder = AsyncMock()

        await run_ingestion_background(task_id, "/tmp/docs", es_client, embedder)

        # Verify pipeline was created and run
        mock_pipeline_cls.assert_called_once()
        mock_pipeline.ingest_all.assert_called_once()

    @patch("pam.ingestion.task_manager.async_session_factory")
    async def test_error_marks_task_failed(self, mock_session_factory):
        task_id = uuid.uuid4()

        # First session (status) raises an error during setup
        status_session = AsyncMock()
        status_session.execute.side_effect = Exception("DB connection failed")

        status_cm = AsyncMock()
        status_cm.__aenter__.return_value = status_session
        status_cm.__aexit__.return_value = None

        # Error session for the except block
        err_session = AsyncMock()
        err_session.execute = AsyncMock()
        err_session.commit = AsyncMock()

        err_cm = AsyncMock()
        err_cm.__aenter__.return_value = err_session
        err_cm.__aexit__.return_value = None

        call_count = 0

        def session_factory_side_effect():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return status_cm
            return err_cm

        mock_session_factory.side_effect = session_factory_side_effect

        es_client = AsyncMock()
        embedder = AsyncMock()

        # Should not raise — error is caught and task marked failed
        await run_ingestion_background(task_id, "/tmp/docs", es_client, embedder)

        # Error session should have been used to update status
        err_session.execute.assert_called()
        err_session.commit.assert_called()


class TestSpawnIngestionTask:
    @patch("pam.ingestion.task_manager.run_ingestion_background", new_callable=AsyncMock)
    async def test_populates_running_tasks_and_creates_named_task(self, mock_run_bg):
        """spawn_ingestion_task should register an asyncio task in _running_tasks with a proper name."""
        task_id = uuid.uuid4()
        es_client = AsyncMock()
        embedder = AsyncMock()

        # Clean up any leftover state
        _running_tasks.pop(task_id, None)

        try:
            spawn_ingestion_task(task_id, "/tmp/test_docs", es_client, embedder)

            # Verify it was added to _running_tasks
            assert task_id in _running_tasks
            asyncio_task = _running_tasks[task_id]

            # Verify the task has the expected name
            assert asyncio_task.get_name() == f"ingest-{task_id}"

            # Cancel and await to clean up
            asyncio_task.cancel()
            try:
                await asyncio_task
            except (asyncio.CancelledError, Exception):
                pass
        finally:
            # Ensure cleanup
            _running_tasks.pop(task_id, None)
