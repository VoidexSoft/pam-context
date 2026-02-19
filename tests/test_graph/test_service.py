"""Tests for GraphitiService lifecycle (create / close)."""

from unittest.mock import AsyncMock, MagicMock, patch

from pam.graph.service import GraphitiService


class TestGraphitiServiceInit:
    def test_init_stores_client(self):
        mock_client = MagicMock()
        service = GraphitiService(mock_client)
        assert service._client is mock_client

    def test_client_property_returns_stored_client(self):
        mock_client = MagicMock()
        service = GraphitiService(mock_client)
        assert service.client is mock_client


class TestGraphitiServiceClose:
    async def test_close_calls_client_close(self):
        mock_client = AsyncMock()
        service = GraphitiService(mock_client)
        await service.close()
        mock_client.close.assert_awaited_once()


class TestGraphitiServiceCreate:
    @patch("pam.graph.service.Graphiti")
    @patch("pam.graph.service.OpenAIEmbedder")
    @patch("pam.graph.service.AnthropicClient")
    async def test_create_returns_graphiti_service(
        self, mock_anthropic_cls, mock_embedder_cls, mock_graphiti_cls
    ):
        mock_graphiti_instance = AsyncMock()
        mock_graphiti_cls.return_value = mock_graphiti_instance

        result = await GraphitiService.create(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
            anthropic_api_key="sk-ant-test",
            openai_api_key="sk-test",
            anthropic_model="claude-sonnet-4-5-20250514",
            embedding_model="text-embedding-3-small",
        )

        assert isinstance(result, GraphitiService)
        assert result.client is mock_graphiti_instance

    @patch("pam.graph.service.Graphiti")
    @patch("pam.graph.service.OpenAIEmbedder")
    @patch("pam.graph.service.AnthropicClient")
    async def test_create_calls_build_indices_and_constraints(
        self, mock_anthropic_cls, mock_embedder_cls, mock_graphiti_cls
    ):
        mock_graphiti_instance = AsyncMock()
        mock_graphiti_cls.return_value = mock_graphiti_instance

        await GraphitiService.create(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
            anthropic_api_key="sk-ant-test",
            openai_api_key="sk-test",
            anthropic_model="claude-sonnet-4-5-20250514",
            embedding_model="text-embedding-3-small",
        )

        mock_graphiti_instance.build_indices_and_constraints.assert_awaited_once()

    @patch("pam.graph.service.Graphiti")
    @patch("pam.graph.service.OpenAIEmbedder")
    @patch("pam.graph.service.AnthropicClient")
    async def test_create_passes_llm_client_and_embedder(
        self, mock_anthropic_cls, mock_embedder_cls, mock_graphiti_cls
    ):
        mock_graphiti_instance = AsyncMock()
        mock_graphiti_cls.return_value = mock_graphiti_instance

        await GraphitiService.create(
            neo4j_uri="bolt://localhost:7687",
            neo4j_user="neo4j",
            neo4j_password="test",
            anthropic_api_key="sk-ant-test",
            openai_api_key="sk-test",
            anthropic_model="claude-sonnet-4-5-20250514",
            embedding_model="text-embedding-3-small",
        )

        mock_anthropic_cls.assert_called_once()
        mock_embedder_cls.assert_called_once()
        # Graphiti should be constructed with the uri, user, password, and both clients
        mock_graphiti_cls.assert_called_once()
        call_kwargs = mock_graphiti_cls.call_args
        assert call_kwargs[0][0] == "bolt://localhost:7687"
        assert call_kwargs[0][1] == "neo4j"
        assert call_kwargs[0][2] == "test"
