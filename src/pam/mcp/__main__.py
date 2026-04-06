"""MCP stdio entrypoint — run with: python -m pam.mcp

Initializes all PAM services and starts the MCP server over stdio transport.
LLM clients (Claude Code, Cursor) connect to this process via stdin/stdout.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from pam.common.config import get_settings
from pam.common.logging import configure_logging

if TYPE_CHECKING:
    from pam.retrieval.search_protocol import SearchService

logger = structlog.get_logger()


async def _create_services():
    """Initialize all PAM services for standalone MCP mode."""
    import redis.asyncio as aioredis
    from elasticsearch import AsyncElasticsearch
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from pam.common.cache import CacheService
    from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
    from pam.mcp.services import PamServices

    settings = get_settings()

    engine = create_async_engine(settings.database_url, echo=False, pool_size=5, max_overflow=10)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    es_client = AsyncElasticsearch(settings.elasticsearch_url)
    embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dims=settings.embedding_dims,
    )

    cache_service = None
    try:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        cache_service = CacheService(
            redis_client,
            search_ttl=settings.redis_search_ttl,
            session_ttl=settings.redis_session_ttl,
        )
    except Exception:
        logger.warning("redis_unavailable_in_mcp_mode")

    search_service: SearchService
    if settings.use_haystack_retrieval:
        from pam.retrieval.haystack_search import HaystackSearchService

        search_service = HaystackSearchService(
            es_url=settings.elasticsearch_url,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            rerank_enabled=settings.rerank_enabled,
            rerank_model=settings.rerank_model,
        )
    else:
        from pam.retrieval.hybrid_search import HybridSearchService

        search_service = HybridSearchService(
            es_client,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            reranker=None,
        )

    duckdb_service = None
    if settings.duckdb_data_dir:
        from pam.agent.duckdb_service import DuckDBService

        duckdb_service = DuckDBService(
            data_dir=settings.duckdb_data_dir,
            max_rows=settings.duckdb_max_rows,
        )
        duckdb_service.register_files()

    graph_service = None
    try:
        from pam.graph.service import GraphitiService

        graph_service = await GraphitiService.create(
            neo4j_uri=settings.neo4j_uri,
            neo4j_user=settings.neo4j_user,
            neo4j_password=settings.neo4j_password,
            anthropic_api_key=settings.anthropic_api_key,
            openai_api_key=settings.openai_api_key,
            anthropic_model=settings.graphiti_model,
            embedding_model=settings.graphiti_embedding_model,
        )
    except Exception:
        logger.warning("graphiti_unavailable_in_mcp_mode")

    vdb_store = None
    try:
        from pam.ingestion.stores.entity_relationship_store import EntityRelationshipVDBStore

        vdb_store = EntityRelationshipVDBStore(
            client=es_client,
            entity_index=settings.entity_index,
            relationship_index=settings.relationship_index,
            embedding_dims=settings.embedding_dims,
        )
    except Exception:
        logger.warning("vdb_store_unavailable_in_mcp_mode")

    # Memory Service (optional)
    memory_service = None
    try:
        from pam.memory.service import MemoryService

        memory_service = await MemoryService.create_from_settings(
            session_factory=session_factory,
            es_client=es_client,
            embedder=embedder,
            settings=settings,
        )
    except Exception:
        logger.warning("memory_service_unavailable_in_mcp_mode", exc_info=True)

    services = PamServices(
        search_service=search_service,
        embedder=embedder,
        session_factory=session_factory,
        es_client=es_client,
        graph_service=graph_service,
        vdb_store=vdb_store,
        duckdb_service=duckdb_service,
        cache_service=cache_service,
        memory_service=memory_service,
        conversation_service=None,
    )
    return services, engine


def main() -> None:
    """Run the MCP server over stdio transport."""
    settings = get_settings()
    configure_logging(settings.log_level)

    async def _run():
        services, engine = await _create_services()

        from pam.mcp.server import create_mcp_server, initialize

        initialize(services)
        server = create_mcp_server()
        logger.info("mcp_stdio_server_starting")
        try:
            await server.run_stdio_async()
        finally:
            if services.graph_service is not None:
                await services.graph_service.close()
            if services.cache_service is not None and hasattr(services.cache_service, "client"):
                await services.cache_service.client.aclose()
            await services.es_client.close()
            await engine.dispose()
            logger.info("mcp_stdio_server_stopped")

    asyncio.run(_run())


if __name__ == "__main__":
    main()
