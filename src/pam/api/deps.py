"""FastAPI dependency injection."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from pam.agent.agent import RetrievalAgent
from pam.common.cache import CacheService
from pam.common.config import settings
from pam.common.database import async_session_factory
from pam.common.logging import CostTracker
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.retrieval.hybrid_search import HybridSearchService
from pam.retrieval.rerankers.base import BaseReranker


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


def get_es_client(request: Request) -> AsyncElasticsearch:
    client: AsyncElasticsearch = request.app.state.es_client
    return client


def get_cache_service(request: Request) -> CacheService | None:
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is None:
        return None
    return CacheService(
        redis_client,
        search_ttl=settings.redis_search_ttl,
        session_ttl=settings.redis_session_ttl,
    )


_embedder: OpenAIEmbedder | None = None
_embedder_lock = asyncio.Lock()


async def get_embedder() -> OpenAIEmbedder:
    global _embedder
    if _embedder is None:
        async with _embedder_lock:
            if _embedder is None:
                _embedder = OpenAIEmbedder(
                    api_key=settings.openai_api_key,
                    model=settings.embedding_model,
                    dims=settings.embedding_dims,
                )
    return _embedder


_reranker: BaseReranker | None = None
_reranker_initialized: bool = False
_reranker_lock = asyncio.Lock()


async def get_reranker() -> BaseReranker | None:
    global _reranker, _reranker_initialized
    if not _reranker_initialized:
        async with _reranker_lock:
            if not _reranker_initialized:
                if settings.rerank_enabled:
                    from pam.retrieval.rerankers.cross_encoder import CrossEncoderReranker

                    _reranker = CrossEncoderReranker(model_name=settings.rerank_model)
                _reranker_initialized = True
    return _reranker


_search_service: Any = None
_search_service_lock = asyncio.Lock()


async def get_search_service(
    request: Request,
) -> HybridSearchService:
    global _search_service
    if _search_service is None:
        async with _search_service_lock:
            if _search_service is None:
                es_client = get_es_client(request)
                cache = get_cache_service(request)
                reranker = await get_reranker()
                if settings.use_haystack_retrieval:
                    from pam.retrieval.haystack_search import HaystackSearchService

                    _search_service = HaystackSearchService(
                        es_url=settings.elasticsearch_url,
                        index_name=settings.elasticsearch_index,
                        rerank_model=settings.rerank_model,
                        cache=cache,
                        rerank_enabled=settings.rerank_enabled,
                    )
                else:
                    _search_service = HybridSearchService(
                        es_client,
                        index_name=settings.elasticsearch_index,
                        cache=cache,
                        reranker=reranker,
                    )
    return _search_service  # type: ignore[no-any-return]


_duckdb_service = None
_duckdb_initialized: bool = False
_duckdb_lock = asyncio.Lock()


async def get_duckdb_service():
    global _duckdb_service, _duckdb_initialized
    if not _duckdb_initialized:
        async with _duckdb_lock:
            if not _duckdb_initialized:
                from pam.agent.duckdb_service import DuckDBService

                if settings.duckdb_data_dir:
                    _duckdb_service = DuckDBService(
                        data_dir=settings.duckdb_data_dir,
                        max_rows=settings.duckdb_max_rows,
                    )
                    _duckdb_service.register_files()
                _duckdb_initialized = True
    return _duckdb_service


async def get_agent(
    search_service: HybridSearchService = Depends(get_search_service),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    db: AsyncSession = Depends(get_db),
) -> RetrievalAgent:
    duckdb_service = await get_duckdb_service()
    return RetrievalAgent(
        search_service=search_service,
        embedder=embedder,
        api_key=settings.anthropic_api_key,
        model=settings.agent_model,
        cost_tracker=CostTracker(),
        db_session=db,
        duckdb_service=duckdb_service,
    )
