"""FastAPI dependency injection."""

from collections.abc import AsyncGenerator

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pam.agent.agent import RetrievalAgent
from pam.common.database import async_session_factory
from pam.common.logging import CostTracker
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.retrieval.hybrid_search import HybridSearchService


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


def get_es_client(request: Request) -> AsyncElasticsearch:
    return request.app.state.es_client


def get_embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder()


def get_search_service(
    es_client: AsyncElasticsearch = Depends(get_es_client),
) -> HybridSearchService:
    return HybridSearchService(es_client)


def get_agent(
    search_service: HybridSearchService = Depends(get_search_service),
    embedder: OpenAIEmbedder = Depends(get_embedder),
) -> RetrievalAgent:
    return RetrievalAgent(
        search_service=search_service,
        embedder=embedder,
        cost_tracker=CostTracker(),
    )
