"""Abstract base class for embedding models."""

from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of texts into vectors."""
        ...

    async def embed_texts_with_cache(self, texts: list[str], content_hashes: list[str]) -> list[list[float]]:
        """Embed texts, using cache for already-embedded content. Override for caching support."""
        return await self.embed_texts(texts)

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """The dimensionality of the embedding vectors."""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """The name/ID of the embedding model."""
        ...
