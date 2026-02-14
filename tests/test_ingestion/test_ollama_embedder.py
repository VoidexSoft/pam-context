"""Tests for Ollama embedder."""

from unittest.mock import AsyncMock, Mock, patch

import pytest

from pam.ingestion.embedders.ollama_embedder import OllamaEmbedder


class TestOllamaEmbedder:
    def test_properties(self):
        embedder = OllamaEmbedder(
            base_url="http://localhost:11434",
            model="nomic-embed-text",
            dims=768,
        )
        assert embedder.dimensions == 768
        assert embedder.model_name == "nomic-embed-text"

    async def test_embed_texts(self):
        embedder = OllamaEmbedder(
            base_url="http://localhost:11434",
            model="nomic-embed-text",
            dims=768,
        )

        mock_response = Mock()
        mock_response.json.return_value = {
            "embeddings": [[0.1] * 768, [0.2] * 768],
        }
        mock_response.raise_for_status = Mock()

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_async_client = AsyncMock()
            mock_async_client.post = AsyncMock(return_value=mock_response)
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_async_client

            results = await embedder.embed_texts(["hello", "world"])

        assert len(results) == 2
        assert len(results[0]) == 768

        # Verify the API call
        call_args = mock_async_client.post.call_args
        assert "/api/embed" in call_args[0][0]
        payload = call_args[1]["json"]
        assert payload["model"] == "nomic-embed-text"
        assert payload["input"] == ["hello", "world"]

    async def test_embed_texts_batching(self):
        """Test that large inputs are batched."""
        embedder = OllamaEmbedder(
            base_url="http://localhost:11434",
            model="nomic-embed-text",
            dims=768,
        )

        texts = [f"text {i}" for i in range(75)]  # More than BATCH_SIZE (50)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()

        call_count = 0

        async def mock_post(url, json=None):
            nonlocal call_count
            call_count += 1
            batch_size = len(json["input"])
            resp = Mock()
            resp.json.return_value = {
                "embeddings": [[0.1] * 768 for _ in range(batch_size)],
            }
            resp.raise_for_status = Mock()
            return resp

        with patch("httpx.AsyncClient") as mock_httpx:
            mock_async_client = AsyncMock()
            mock_async_client.post = mock_post
            mock_async_client.__aenter__ = AsyncMock(return_value=mock_async_client)
            mock_async_client.__aexit__ = AsyncMock(return_value=None)
            mock_httpx.return_value = mock_async_client

            results = await embedder.embed_texts(texts)

        assert len(results) == 75
        assert call_count == 2  # 50 + 25
