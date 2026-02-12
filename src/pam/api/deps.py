"""FastAPI dependency injection."""

from collections.abc import AsyncGenerator

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
        yield session


def get_es_client(request: Request) -> AsyncElasticsearch:
    return request.app.state.es_client


def get_cache_service(request: Request) -> CacheService | None:
    redis_client = getattr(request.app.state, "redis_client", None)
    if redis_client is None:
        return None
    return CacheService(redis_client)


def get_embedder() -> OpenAIEmbedder:
    return OpenAIEmbedder()


def get_reranker() -> BaseReranker | None:
    if not settings.rerank_enabled:
        return None
    from pam.retrieval.rerankers.cross_encoder import CrossEncoderReranker

    return CrossEncoderReranker(model_name=settings.rerank_model)


def get_search_service(
    es_client: AsyncElasticsearch = Depends(get_es_client),
    cache: CacheService | None = Depends(get_cache_service),
    reranker: BaseReranker | None = Depends(get_reranker),
) -> HybridSearchService:
    if settings.use_haystack_retrieval:
        from pam.retrieval.haystack_search import HaystackSearchService

        return HaystackSearchService(  # type: ignore[return-value]
            cache=cache,
            rerank_enabled=settings.rerank_enabled,
            rerank_model=settings.rerank_model,
        )
    return HybridSearchService(es_client, cache=cache, reranker=reranker)


def get_duckdb_service():
    from pam.agent.duckdb_service import DuckDBService

    if not settings.duckdb_data_dir:
        return None
    service = DuckDBService()
    service.register_files()
    return service


def get_agent(
    search_service: HybridSearchService = Depends(get_search_service),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    db: AsyncSession = Depends(get_db),
) -> RetrievalAgent:
    return RetrievalAgent(
        search_service=search_service,
        embedder=embedder,
        cost_tracker=CostTracker(),
        db_session=db,
        duckdb_service=get_duckdb_service(),
    )
