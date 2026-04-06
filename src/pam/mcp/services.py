"""Service container for MCP server dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from elasticsearch import AsyncElasticsearch
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from pam.agent.duckdb_service import DuckDBService
    from pam.common.cache import CacheService
    from pam.conversation.service import ConversationService
    from pam.graph.service import GraphitiService
    from pam.ingestion.embedders.base import BaseEmbedder
    from pam.ingestion.stores.entity_relationship_store import EntityRelationshipVDBStore
    from pam.glossary.service import GlossaryService
    from pam.memory.service import MemoryService
    from pam.retrieval.search_protocol import SearchService

logger = structlog.get_logger()


@dataclass
class PamServices:
    """Holds all service instances needed by MCP tools."""

    search_service: SearchService
    embedder: BaseEmbedder
    session_factory: async_sessionmaker[AsyncSession]
    es_client: AsyncElasticsearch
    graph_service: GraphitiService | None
    vdb_store: EntityRelationshipVDBStore | None
    duckdb_service: DuckDBService | None
    cache_service: CacheService | None
    memory_service: MemoryService | None
    conversation_service: ConversationService | None
    glossary_service: GlossaryService | None


def from_app_state(app_state: Any) -> PamServices:
    """Extract PamServices from a FastAPI app.state object."""
    return PamServices(
        search_service=app_state.search_service,
        embedder=app_state.embedder,
        session_factory=app_state.session_factory,
        es_client=app_state.es_client,
        graph_service=getattr(app_state, "graph_service", None),
        vdb_store=getattr(app_state, "vdb_store", None),
        duckdb_service=getattr(app_state, "duckdb_service", None),
        cache_service=getattr(app_state, "cache_service", None),
        memory_service=getattr(app_state, "memory_service", None),
        conversation_service=getattr(app_state, "conversation_service", None),
        glossary_service=getattr(app_state, "glossary_service", None),
    )
