"""Ollama embedding implementation using the /api/embed endpoint."""

from __future__ import annotations

import httpx
import structlog

from pam.common.config import settings
from pam.ingestion.embedders.base import BaseEmbedder

logger = structlog.get_logger()

BATCH_SIZE = 50  # Ollama handles smaller batches better


class OllamaEmbedder(BaseEmbedder):
    """Embedder using Ollama's local embedding API."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        dims: int | None = None,
    ) -> None:
        self._base_url = (base_url or settings.ollama_base_url).rstrip("/")
        self._model = model or settings.ollama_embedding_model
        self._dims = dims or settings.ollama_embedding_dims

    @property
    def dimensions(self) -> int:
        return self._dims

    @property
    def model_name(self) -> str:
        return self._model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using Ollama's /api/embed endpoint."""
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), BATCH_SIZE):
            batch = texts[i : i + BATCH_SIZE]
            batch_embeddings = await self._embed_batch(batch)
            all_embeddings.extend(batch_embeddings)

        return all_embeddings

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self._model,
            "input": texts,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self._base_url}/api/embed", json=payload)
            resp.raise_for_status()
            data = resp.json()

        embeddings = data.get("embeddings", [])

        logger.info(
            "ollama_embed_batch",
            model=self._model,
            count=len(texts),
            embeddings_returned=len(embeddings),
        )

        return embeddings
