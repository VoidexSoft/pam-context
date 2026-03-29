"""Tests for CLI connector task manager functions."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.ingestion.task_manager import (
    run_github_ingestion_background,
    run_sync_background,
)


@pytest.fixture
def mock_session_factory():
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    factory = MagicMock(return_value=session)
    return factory


@pytest.fixture
def mock_es_client():
    return AsyncMock()


@pytest.fixture
def mock_embedder():
    embedder = AsyncMock()
    embedder.dimensions = 1536
    return embedder


class TestRunGithubIngestionBackground:
    async def test_creates_github_connector_and_runs_pipeline(
        self, mock_session_factory, mock_es_client, mock_embedder
    ):
        task_id = uuid.uuid4()
        repo_config = {"repo": "owner/repo", "branch": "main", "paths": ["docs/"], "extensions": [".md"]}

        with patch("pam.ingestion.task_manager.GitHubConnector") as MockGH, \
             patch("pam.ingestion.task_manager.DoclingParser"), \
             patch("pam.ingestion.task_manager.ElasticsearchStore"), \
             patch("pam.ingestion.task_manager.IngestionPipeline") as MockPipeline:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.list_documents = AsyncMock(return_value=[])
            MockGH.return_value = mock_gh_instance

            mock_pipeline = AsyncMock()
            mock_pipeline.ingest_all = AsyncMock(return_value=[])
            MockPipeline.return_value = mock_pipeline

            await run_github_ingestion_background(
                task_id=task_id,
                repo_config=repo_config,
                es_client=mock_es_client,
                embedder=mock_embedder,
                session_factory=mock_session_factory,
            )

        MockGH.assert_called_once_with(
            repo="owner/repo", branch="main", paths=["docs/"], extensions=[".md"],
        )


class TestRunSyncBackground:
    async def test_iterates_github_sources(
        self, mock_session_factory, mock_es_client, mock_embedder
    ):
        task_id = uuid.uuid4()
        github_repos = [{"repo": "org/wiki", "branch": "main", "paths": [], "extensions": [".md"]}]

        with patch("pam.ingestion.task_manager.GitHubConnector") as MockGH, \
             patch("pam.ingestion.task_manager.DoclingParser"), \
             patch("pam.ingestion.task_manager.ElasticsearchStore"), \
             patch("pam.ingestion.task_manager.IngestionPipeline") as MockPipeline:
            mock_gh_instance = AsyncMock()
            mock_gh_instance.list_documents = AsyncMock(return_value=[])
            MockGH.return_value = mock_gh_instance

            mock_pipeline = AsyncMock()
            mock_pipeline.ingest_all = AsyncMock(return_value=[])
            MockPipeline.return_value = mock_pipeline

            await run_sync_background(
                task_id=task_id,
                sources=["github"],
                github_repos=github_repos,
                es_client=mock_es_client,
                embedder=mock_embedder,
                session_factory=mock_session_factory,
            )

        MockGH.assert_called_once()
