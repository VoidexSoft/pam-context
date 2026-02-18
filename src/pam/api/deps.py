"""FastAPI dependency injection — stateless functions reading from app.state."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, cast

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pam.agent.agent import RetrievalAgent
from pam.common.cache import CacheService
from pam.common.logging import CostTracker
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.retrieval.rerankers.base import BaseReranker
from pam.retrieval.search_protocol import SearchService

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
    return cast(AsyncElasticsearch, request.app.state.es_client)


def get_embedder(request: Request) -> OpenAIEmbedder:
    return cast(OpenAIEmbedder, request.app.state.embedder)


def get_search_service(request: Request) -> SearchService:
    return cast(SearchService, request.app.state.search_service)


def get_reranker(request: Request) -> BaseReranker | None:
    return cast(BaseReranker | None, request.app.state.reranker)


def get_duckdb_service(request: Request) -> DuckDBService | None:
    return cast("DuckDBService | None", request.app.state.duckdb_service)


def get_cache_service(request: Request) -> CacheService | None:
    return cast(CacheService | None, request.app.state.cache_service)


async def get_agent(
    request: Request,
    search_service: SearchService = Depends(get_search_service),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    db: AsyncSession = Depends(get_db),
) -> RetrievalAgent:
    duckdb_service = get_duckdb_service(request)
    return RetrievalAgent(
        search_service=search_service,
        embedder=embedder,
        api_key=cast(str, request.app.state.anthropic_api_key),
        model=cast(str, request.app.state.agent_model),
        cost_tracker=CostTracker(),
        db_session=db,
        duckdb_service=duckdb_service,
    )
