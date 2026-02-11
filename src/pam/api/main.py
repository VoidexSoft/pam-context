"""FastAPI application factory."""

import structlog
from contextlib import asynccontextmanager

from elasticsearch import AsyncElasticsearch
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from pam.api.deps import get_db, get_es_client
from pam.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware
from pam.api.routes import chat, documents, ingest, search
from pam.common.config import settings
from pam.common.logging import configure_logging

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

    yield

    # Shutdown
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

        all_up = all(v == "up" for v in services.values())
        status_code = 200 if all_up else 503
        return JSONResponse(
            status_code=status_code,
            content={
                "status": "healthy" if all_up else "unhealthy",
                "services": services,
            },
        )

    return app


app = create_app()
