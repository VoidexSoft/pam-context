"""OpenAI embedding implementation with batching, retry, and caching."""

import time
from collections import OrderedDict

import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from pam.common.config import settings
from pam.common.logging import CostTracker
from pam.ingestion.embedders.base import BaseEmbedder

logger = structlog.get_logger()

BATCH_SIZE = 100  # OpenAI recommends max 2048, but 100 is safer for rate limits


class OpenAIEmbedder(BaseEmbedder):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        dims: int | None = None,
        cost_tracker: CostTracker | None = None,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key or settings.openai_api_key)
        self._model = model or settings.embedding_model
        self._dims = dims or settings.embedding_dims
        self._cost_tracker = cost_tracker
        # In-memory LRU cache: content_hash -> embedding vector
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_max_size = 10_000

    @property
    def dimensions(self) -> int:
        return self._dims

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts with batching and retry."""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            batch_embeddings = await self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def embed_texts_with_cache(self, texts: list[str], content_hashes: list[str]) -> list[list[float]]:
        """Embed texts, using cache for already-embedded content."""
        results: list[list[float] | None] = [None] * len(texts)
        texts_to_embed: list[tuple[int, str]] = []

        for i, (text, hash_) in enumerate(zip(texts, content_hashes, strict=True)):
            if hash_ in self._cache:
                self._cache.move_to_end(hash_)
                results[i] = self._cache[hash_]
            else:
                texts_to_embed.append((i, text))

        if texts_to_embed:
            indices, batch_texts = zip(*texts_to_embed, strict=True)
            embeddings = await self.embed_texts(list(batch_texts))
            for idx, embedding in zip(indices, embeddings, strict=True):
                results[idx] = embedding
                # Cache by content hash with LRU eviction
                self._cache[content_hashes[idx]] = embedding
                if len(self._cache) > self._cache_max_size:
                    self._cache.popitem(last=False)

        cache_hits = len(texts) - len(texts_to_embed)
        if cache_hits > 0:
            logger.info("embedding_cache", hits=cache_hits, misses=len(texts_to_embed))

        return results  # type: ignore[return-value]

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=30))
    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        start = time.perf_counter()
        response = await self._client.embeddings.create(
            model=self._model,
            input=texts,
            dimensions=self._dims,
        )
        latency_ms = (time.perf_counter() - start) * 1000

        embeddings = [item.embedding for item in response.data]
        total_tokens = response.usage.total_tokens if response.usage else 0

        if self._cost_tracker:
            self._cost_tracker.log_embedding_call(self._model, total_tokens, latency_ms)

        logger.info(
            "embed_batch",
            model=self._model,
            count=len(texts),
            tokens=total_tokens,
            latency_ms=round(latency_ms, 1),
        )

        return embeddings
