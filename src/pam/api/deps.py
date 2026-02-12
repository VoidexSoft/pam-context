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


_embedder: OpenAIEmbedder | None = None


def get_embedder() -> OpenAIEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = OpenAIEmbedder()
    return _embedder


_reranker: BaseReranker | None = None
_reranker_initialized: bool = False


def get_reranker() -> BaseReranker | None:
    global _reranker, _reranker_initialized
    if not _reranker_initialized:
        if settings.rerank_enabled:
            from pam.retrieval.rerankers.cross_encoder import CrossEncoderReranker

            _reranker = CrossEncoderReranker(model_name=settings.rerank_model)
        _reranker_initialized = True
    return _reranker


_search_service: HybridSearchService | None = None


def get_search_service(
    es_client: AsyncElasticsearch = Depends(get_es_client),
    cache: CacheService | None = Depends(get_cache_service),
    reranker: BaseReranker | None = Depends(get_reranker),
) -> HybridSearchService:
    global _search_service
    if _search_service is None:
        if settings.use_haystack_retrieval:
            from pam.retrieval.haystack_search import HaystackSearchService

            _search_service = HaystackSearchService(  # type: ignore[return-value]
                cache=cache,
                rerank_enabled=settings.rerank_enabled,
                rerank_model=settings.rerank_model,
            )
        else:
            _search_service = HybridSearchService(es_client, cache=cache, reranker=reranker)
    return _search_service


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
