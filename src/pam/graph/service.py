"""GraphitiService -- thin wrapper around the Graphiti client.

Provides a factory method that initialises the Graphiti client with Anthropic
LLM and OpenAI embedder, builds indices/constraints, and exposes a clean
``close()`` for shutdown.
"""

from __future__ import annotations

import structlog
from graphiti_core import Graphiti
from graphiti_core.embedder.openai import OpenAIEmbedder, OpenAIEmbedderConfig
from graphiti_core.llm_client.anthropic_client import AnthropicClient
from graphiti_core.llm_client.config import LLMConfig

logger = structlog.get_logger()


class GraphitiService:
    """Lifecycle wrapper for the Graphiti knowledge-graph client."""

    def __init__(self, client: Graphiti) -> None:
        self._client = client

    @classmethod
    async def create(
        cls,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        anthropic_api_key: str,
        openai_api_key: str,
        anthropic_model: str,
        embedding_model: str,
    ) -> GraphitiService:
        """Create and initialise a GraphitiService.

        Connects to Neo4j, configures the Anthropic LLM client and OpenAI
        embedder, then builds indices and constraints.
        """
        llm_client = AnthropicClient(
            LLMConfig(api_key=anthropic_api_key, model=anthropic_model),
        )
        embedder = OpenAIEmbedder(
            OpenAIEmbedderConfig(api_key=openai_api_key, model=embedding_model),
        )
        client = Graphiti(
            neo4j_uri,
            neo4j_user,
            neo4j_password,
            llm_client=llm_client,
            embedder=embedder,
        )
        await client.build_indices_and_constraints()
        logger.info("graphiti_initialized", neo4j_uri=neo4j_uri, model=anthropic_model)
        return cls(client)

    @property
    def client(self) -> Graphiti:
        """Return the underlying Graphiti client."""
        return self._client

    async def close(self) -> None:
        """Shut down the Graphiti client and release resources."""
        await self._client.close()
        logger.info("graphiti_closed")
