"""Tests for OpenAIEmbedder — embedding with batching, caching, cost tracking."""

from unittest.mock import AsyncMock, Mock, patch

from pam.common.logging import CostTracker
from pam.ingestion.embedders.openai_embedder import BATCH_SIZE, OpenAIEmbedder


def _make_embed_response(count: int, dims: int = 1536):
    """Create a mock embeddings response with `count` items."""
    data = []
    for i in range(count):
        item = Mock()
        item.embedding = [float(i) / 10] * dims
        data.append(item)
    usage = Mock()
    usage.total_tokens = count * 10
    response = Mock()
    response.data = data
    response.usage = usage
    return response


class TestOpenAIEmbedder:
    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_embed_single_text(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=_make_embed_response(1))
        mock_client_cls.return_value = mock_client

        embedder = OpenAIEmbedder(api_key="test-key", model="text-embedding-3-small", dims=1536)
        result = await embedder.embed_texts(["hello"])

        assert len(result) == 1
        assert len(result[0]) == 1536
        mock_client.embeddings.create.assert_called_once()

    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_embed_batching(self, mock_client_cls):
        """Texts exceeding BATCH_SIZE should be split into multiple calls."""
        mock_client = AsyncMock()
        # Return correct number of embeddings per batch
        mock_client.embeddings.create = AsyncMock(
            side_effect=[
                _make_embed_response(BATCH_SIZE),
                _make_embed_response(5),
            ]
        )
        mock_client_cls.return_value = mock_client

        embedder = OpenAIEmbedder(api_key="test-key", model="text-embedding-3-small", dims=1536)
        texts = [f"text {i}" for i in range(BATCH_SIZE + 5)]
        result = await embedder.embed_texts(texts)

        assert len(result) == BATCH_SIZE + 5
        assert mock_client.embeddings.create.call_count == 2

    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_properties(self, mock_client_cls):
        mock_client_cls.return_value = AsyncMock()
        embedder = OpenAIEmbedder(api_key="key", model="custom-model", dims=768)
        assert embedder.dimensions == 768
        assert embedder.model_name == "custom-model"

    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_cost_tracking(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=_make_embed_response(1))
        mock_client_cls.return_value = mock_client

        tracker = CostTracker()
        embedder = OpenAIEmbedder(api_key="key", model="text-embedding-3-small", dims=1536, cost_tracker=tracker)
        await embedder.embed_texts(["test"])

        assert len(tracker.calls) == 1
        assert tracker.total_tokens > 0
        assert tracker.total_cost >= 0


class TestEmbedWithCache:
    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_cache_miss_then_hit(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=_make_embed_response(1))
        mock_client_cls.return_value = mock_client

        embedder = OpenAIEmbedder(api_key="key", model="text-embedding-3-small", dims=1536)

        # First call: cache miss
        result1 = await embedder.embed_texts_with_cache(["hello"], ["hash1"])
        assert len(result1) == 1
        assert mock_client.embeddings.create.call_count == 1

        # Second call with same hash: cache hit
        result2 = await embedder.embed_texts_with_cache(["hello"], ["hash1"])
        assert len(result2) == 1
        assert mock_client.embeddings.create.call_count == 1  # no new API call

    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_partial_cache_hit(self, mock_client_cls):
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=_make_embed_response(1))
        mock_client_cls.return_value = mock_client

        embedder = OpenAIEmbedder(api_key="key", model="text-embedding-3-small", dims=1536)
        # Pre-populate cache
        embedder._cache["hash1"] = [0.5] * 1536

        result = await embedder.embed_texts_with_cache(
            ["cached text", "new text"],
            ["hash1", "hash2"],
        )
        assert len(result) == 2
        assert result[0] == [0.5] * 1536  # from cache
        mock_client.embeddings.create.assert_called_once()  # only for "new text"

    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_lru_eviction(self, mock_client_cls):
        """Cache evicts oldest entries when exceeding max size."""
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=_make_embed_response(1))
        mock_client_cls.return_value = mock_client

        embedder = OpenAIEmbedder(api_key="key", model="text-embedding-3-small", dims=1536)
        embedder._cache_max_size = 3  # small for testing

        # Fill cache to capacity
        for i in range(3):
            await embedder.embed_texts_with_cache([f"text{i}"], [f"hash{i}"])

        assert len(embedder._cache) == 3
        assert "hash0" in embedder._cache

        # Add one more — should evict hash0 (oldest)
        await embedder.embed_texts_with_cache(["text3"], ["hash3"])

        assert len(embedder._cache) == 3
        assert "hash0" not in embedder._cache
        assert "hash3" in embedder._cache

    @patch("pam.ingestion.embedders.openai_embedder.AsyncOpenAI")
    async def test_lru_access_refreshes_entry(self, mock_client_cls):
        """Accessing a cached entry moves it to end, preventing eviction."""
        mock_client = AsyncMock()
        mock_client.embeddings.create = AsyncMock(return_value=_make_embed_response(1))
        mock_client_cls.return_value = mock_client

        embedder = OpenAIEmbedder(api_key="key", model="text-embedding-3-small", dims=1536)
        embedder._cache_max_size = 3

        # Fill cache: hash0, hash1, hash2
        for i in range(3):
            await embedder.embed_texts_with_cache([f"text{i}"], [f"hash{i}"])

        # Access hash0 — moves it to end
        await embedder.embed_texts_with_cache(["text0"], ["hash0"])

        # Add hash3 — should evict hash1 (now oldest), not hash0
        await embedder.embed_texts_with_cache(["text3"], ["hash3"])

        assert "hash0" in embedder._cache  # refreshed, still present
        assert "hash1" not in embedder._cache  # evicted
        assert "hash3" in embedder._cache
