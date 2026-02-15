"""FastAPI dependency injection — stateless functions reading from app.state."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pam.agent.agent import RetrievalAgent
from pam.common.cache import CacheService
from pam.common.logging import CostTracker
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.retrieval.hybrid_search import HybridSearchService
from pam.retrieval.rerankers.base import BaseReranker

if TYPE_CHECKING:
    from pam.agent.duckdb_service import DuckDBService


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    session_factory = request.app.state.session_factory
    async with session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_es_client(request: Request) -> AsyncElasticsearch:
    return request.app.state.es_client  # type: ignore[no-any-return]


def get_embedder(request: Request) -> OpenAIEmbedder:
    return request.app.state.embedder  # type: ignore[no-any-return]


def get_search_service(request: Request) -> HybridSearchService:
    return request.app.state.search_service  # type: ignore[no-any-return]


def get_reranker(request: Request) -> BaseReranker | None:
    return request.app.state.reranker  # type: ignore[no-any-return]


def get_duckdb_service(request: Request) -> DuckDBService | None:
    return request.app.state.duckdb_service  # type: ignore[no-any-return]


def get_cache_service(request: Request) -> CacheService | None:
    return request.app.state.cache_service  # type: ignore[no-any-return]


async def get_agent(
    request: Request,
    search_service: HybridSearchService = Depends(get_search_service),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    db: AsyncSession = Depends(get_db),
) -> RetrievalAgent:
    duckdb_service = get_duckdb_service(request)
    return RetrievalAgent(
        search_service=search_service,
        embedder=embedder,
        api_key=request.app.state.anthropic_api_key,
        model=request.app.state.agent_model,
        cost_tracker=CostTracker(),
        db_session=db,
        duckdb_service=duckdb_service,
    )
