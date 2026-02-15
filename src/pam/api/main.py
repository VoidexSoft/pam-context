"""FastAPI application factory."""

from contextlib import asynccontextmanager

import structlog
from elasticsearch import AsyncElasticsearch
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, text
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.deps import get_db, get_es_client
from pam.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware
from pam.api.routes import admin, auth, chat, documents, ingest, search
from pam.common.cache import close_redis, get_redis, ping_redis
from pam.common.config import settings
from pam.common.database import async_session_factory
from pam.common.logging import configure_logging
from pam.common.models import IngestionTask

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    configure_logging(settings.log_level)

    app.state.es_client = AsyncElasticsearch(settings.elasticsearch_url)

    # Ensure ES index exists
    from pam.ingestion.stores.elasticsearch_store import ElasticsearchStore

    es_store = ElasticsearchStore(app.state.es_client)
    await es_store.ensure_index()

    # Initialize Redis
    try:
        app.state.redis_client = await get_redis()
        logger.info("redis_connected", url=settings.redis_url)
    except Exception:
        logger.warning("redis_connect_failed", exc_info=True)
        app.state.redis_client = None

    # Clean up orphaned ingestion tasks from previous server runs
    async with async_session_factory() as session:
        await session.execute(
            sa_update(IngestionTask)
            .where(IngestionTask.status.in_(["pending", "running"]))
            .values(status="failed", error="Server restarted", completed_at=func.now())
        )
        await session.commit()

    yield

    # Shutdown
    await close_redis()
    await app.state.es_client.close()


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
        allow_methods=["*"],
        allow_headers=["*"],
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

    @app.get("/api/health")
    async def health(
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
        try:
            if await ping_redis():
                services["redis"] = "up"
            else:
                services["redis"] = "down"
        except Exception:
            logger.warning("health_check_redis_failed", exc_info=True)
            services["redis"] = "down"

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
