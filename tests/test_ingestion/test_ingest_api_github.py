"""Tests for GitHub and sync ingest API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from pam.api.deps import get_db, get_embedder, get_es_client
from pam.api.routes.ingest import router
from pam.common.models import IngestionTask


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def app(mock_db_session):
    app = FastAPI()
    app.include_router(router)
    app.state.session_factory = MagicMock()
    app.state.cache_service = None
    app.state.graph_service = None
    app.state.vdb_store = None

    # Override dependencies that access app.state attributes
    app.dependency_overrides[get_db] = lambda: mock_db_session
    app.dependency_overrides[get_es_client] = lambda: AsyncMock()
    app.dependency_overrides[get_embedder] = lambda: AsyncMock()
    return app


@pytest.fixture
def mock_task():
    task = MagicMock(spec=IngestionTask)
    task.id = uuid.uuid4()
    return task


class TestIngestGithub:
    async def test_returns_202_with_task_id(self, app, mock_task):
        with patch("pam.api.routes.ingest.create_task", new_callable=AsyncMock, return_value=mock_task), \
             patch("pam.api.routes.ingest.spawn_github_ingestion_task") as mock_spawn, \
             patch("pam.api.routes.ingest.require_admin", return_value=None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/github", json={
                    "repo": "owner/repo",
                    "branch": "main",
                    "paths": ["docs/"],
                })
            assert resp.status_code == 202
            data = resp.json()
            assert "task_id" in data

    async def test_requires_repo_field(self, app):
        with patch("pam.api.routes.ingest.require_admin", return_value=None):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/github", json={})
            assert resp.status_code == 422


class TestIngestSync:
    async def test_returns_202_with_task_id(self, app, mock_task):
        with patch("pam.api.routes.ingest.create_task", new_callable=AsyncMock, return_value=mock_task), \
             patch("pam.api.routes.ingest.spawn_sync_task") as mock_spawn, \
             patch("pam.api.routes.ingest.require_admin", return_value=None), \
             patch("pam.api.routes.ingest.settings") as mock_settings:
            mock_settings.github_repos = [{"repo": "org/wiki"}]
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/sync", json={
                    "sources": ["github"],
                })
            assert resp.status_code == 202

    async def test_defaults_sources_to_all(self, app, mock_task):
        with patch("pam.api.routes.ingest.create_task", new_callable=AsyncMock, return_value=mock_task), \
             patch("pam.api.routes.ingest.spawn_sync_task") as mock_spawn, \
             patch("pam.api.routes.ingest.require_admin", return_value=None), \
             patch("pam.api.routes.ingest.settings") as mock_settings:
            mock_settings.github_repos = []
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/ingest/sync", json={})
            assert resp.status_code == 202
            call_kwargs = mock_spawn.call_args
            sources_arg = call_kwargs.kwargs.get("sources") or call_kwargs[0][1]
            assert "github" in sources_arg
