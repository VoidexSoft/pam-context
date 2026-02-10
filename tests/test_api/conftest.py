"""API test fixtures — TestClient with dependency overrides."""

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from pam.agent.agent import AgentResponse, RetrievalAgent
from pam.api.deps import get_agent, get_db, get_embedder, get_es_client, get_search_service
from pam.api.main import create_app
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.retrieval.hybrid_search import HybridSearchService


@pytest.fixture
def mock_agent():
    agent = AsyncMock(spec=RetrievalAgent)
    agent.answer = AsyncMock(
        return_value=AgentResponse(
            answer="Test answer",
            citations=[],
            token_usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            latency_ms=100.0,
            tool_calls=0,
        )
    )
    return agent


@pytest.fixture
def mock_search_service():
    service = AsyncMock(spec=HybridSearchService)
    service.search = AsyncMock(return_value=[])
    service.search_from_query = AsyncMock(return_value=[])
    return service


@pytest.fixture
def mock_api_embedder():
    embedder = AsyncMock(spec=OpenAIEmbedder)
    embedder.embed_texts = AsyncMock(return_value=[[0.1] * 1536])
    embedder.dimensions = 1536
    embedder.model_name = "text-embedding-3-large"
    return embedder


@pytest.fixture
def mock_api_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.close = AsyncMock()
    return session


@pytest.fixture
def mock_api_es_client():
    client = AsyncMock()
    return client


@pytest.fixture
def app(mock_agent, mock_search_service, mock_api_embedder, mock_api_db_session, mock_api_es_client):
    """Create app with all dependencies overridden."""
    application = create_app()
    application.dependency_overrides[get_agent] = lambda: mock_agent
    application.dependency_overrides[get_search_service] = lambda: mock_search_service
    application.dependency_overrides[get_embedder] = lambda: mock_api_embedder
    application.dependency_overrides[get_db] = lambda: mock_api_db_session
    application.dependency_overrides[get_es_client] = lambda: mock_api_es_client
    return application


@pytest.fixture
async def client(app):
    """Async test client that bypasses lifespan."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
