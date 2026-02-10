"""FastAPI application factory."""

from contextlib import asynccontextmanager

from elasticsearch import AsyncElasticsearch
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from pam.api.middleware import CorrelationIdMiddleware, RequestLoggingMiddleware
from pam.api.routes import chat, documents, ingest, search
from pam.common.config import settings
from pam.common.logging import configure_logging


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
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
