"""FastAPI application factory."""

from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog
from elasticsearch import AsyncElasticsearch
from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from pam.api.deps import get_db, get_es_client
from pam.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware
from pam.api.routes import admin, auth, chat, documents, graph, ingest, search
from pam.common.cache import CacheService
from pam.common.config import settings
from pam.common.logging import configure_logging
from pam.common.models import IngestionTask
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging(settings.log_level)

    # --- Database engine + session factory ---
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        pool_size=5,
        max_overflow=10,
    )
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    app.state.db_engine = engine
    app.state.session_factory = session_factory

    # --- Elasticsearch client ---
    app.state.es_client = AsyncElasticsearch(settings.elasticsearch_url)

    # Ensure ES index exists
    from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore

    es_store = ElasticsearchStore(
        app.state.es_client,
        index_name=settings.elasticsearch_index,
        embedding_dims=settings.embedding_dims,
    )
    await es_store.ensure_index()

    # --- Redis client ---
    redis_client = None
    try:
        redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await redis_client.ping()
        logger.info("redis_connected", url=settings.redis_url)
    except Exception:
        logger.warning("redis_connect_failed", exc_info=True)
        redis_client = None
    app.state.redis_client = redis_client

    # --- CacheService ---
    cache_service = None
    if redis_client:
        cache_service = CacheService(
            redis_client,
            search_ttl=settings.redis_search_ttl,
            session_ttl=settings.redis_session_ttl,
        )
    app.state.cache_service = cache_service

    # --- Embedder ---
    app.state.embedder = OpenAIEmbedder(
        api_key=settings.openai_api_key,
        model=settings.embedding_model,
        dims=settings.embedding_dims,
    )

    # --- Reranker (conditional) ---
    reranker = None
    if settings.rerank_enabled:
        from pam.retrieval.rerankers.cross_encoder import CrossEncoderReranker

        reranker = CrossEncoderReranker(model_name=settings.rerank_model)
    app.state.reranker = reranker

    # --- Search service (haystack or legacy) ---
    if settings.use_haystack_retrieval:
        from pam.retrieval.haystack_search import HaystackSearchService

        app.state.search_service = HaystackSearchService(
            es_url=settings.elasticsearch_url,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            rerank_enabled=settings.rerank_enabled,
            rerank_model=settings.rerank_model,
        )
    else:
        from pam.retrieval.hybrid_search import HybridSearchService

        app.state.search_service = HybridSearchService(
            app.state.es_client,
            index_name=settings.elasticsearch_index,
            cache=cache_service,
            reranker=reranker,
        )

    # --- DuckDB (conditional) ---
    duckdb_service = None
    if settings.duckdb_data_dir:
        from pam.agent.duckdb_service import DuckDBService

        duckdb_service = DuckDBService(
            data_dir=settings.duckdb_data_dir,
            max_rows=settings.duckdb_max_rows,
        )
        duckdb_service.register_files()
    app.state.duckdb_service = duckdb_service

    # --- Graphiti / Neo4j ---
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
        logger.warning("graphiti_connect_failed", exc_info=True)
    app.state.graph_service = graph_service

    # --- Store config values on app.state for deps.py agent creation ---
    app.state.anthropic_api_key = settings.anthropic_api_key
    app.state.agent_model = settings.agent_model

    # Warn when auth is disabled — admin routes are fully open
    if not settings.auth_required:
        logger.warning(
            "auth_disabled",
            detail="AUTH_REQUIRED=false — admin routes are open without authentication. "
            "Set AUTH_REQUIRED=true in production.",
        )

    # Clean up orphaned ingestion tasks from previous server runs
    async with session_factory() as session:
        await session.execute(
            sa_update(IngestionTask)
            .where(IngestionTask.status.in_(["pending", "running"]))
            .values(status="failed", error="Server restarted", completed_at=func.now())
        )
        await session.commit()

    yield

    # Shutdown
    if graph_service:
        await graph_service.close()
    if redis_client:
        await redis_client.aclose()
    await app.state.es_client.close()
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="PAM Context API",
        description="Business Knowledge Layer for LLMs",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Middleware (order matters — outermost first)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Correlation-ID"],
    )
    app.add_middleware(RequestLoggingMiddleware)
    app.add_middleware(CorrelationIdMiddleware)

    # Routes
    app.include_router(chat.router, prefix="/api", tags=["chat"])
    app.include_router(search.router, prefix="/api", tags=["search"])
    app.include_router(documents.router, prefix="/api", tags=["documents"])
    app.include_router(ingest.router, prefix="/api", tags=["ingest"])
    app.include_router(auth.router, prefix="/api", tags=["auth"])
    app.include_router(admin.router, prefix="/api", tags=["admin"])
    app.include_router(graph.router, prefix="/api", tags=["graph"])

    @app.get("/api/health")
    async def health(
        request: Request,
        es_client: AsyncElasticsearch = Depends(get_es_client),
        db: AsyncSession = Depends(get_db),
    ):
        services: dict[str, str] = {}

        # Check Elasticsearch
        try:
            if await es_client.ping():
                services["elasticsearch"] = "up"
            else:
                services["elasticsearch"] = "down"
        except Exception:
            logger.warning("health_check_es_failed", exc_info=True)
            services["elasticsearch"] = "down"

        # Check PostgreSQL
        try:
            await db.execute(text("SELECT 1"))
            services["postgres"] = "up"
        except Exception:
            logger.warning("health_check_pg_failed", exc_info=True)
            services["postgres"] = "down"

        # Check Redis
        redis_client = getattr(request.app.state, "redis_client", None)
        if redis_client:
            try:
                if await redis_client.ping():
                    services["redis"] = "up"
                else:
                    services["redis"] = "down"
            except Exception:
                logger.warning("health_check_redis_failed", exc_info=True)
                services["redis"] = "down"
        else:
            services["redis"] = "down"

        # Check Neo4j
        graph_service = getattr(request.app.state, "graph_service", None)
        if graph_service:
            try:
                async with graph_service.client.driver.session() as session:
                    await session.run("RETURN 1")
                services["neo4j"] = "up"
            except Exception:
                logger.warning("health_check_neo4j_failed", exc_info=True)
                services["neo4j"] = "down"
        else:
            services["neo4j"] = "down"

        all_up = all(v == "up" for v in services.values())
        status_code = 200 if all_up else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "healthy" if all_up else "unhealthy",
                "services": services,
                "auth_required": settings.auth_required,
            },
        )

    return app


app = create_app()
