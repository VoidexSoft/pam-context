"""Abstract base class for document connectors."""

from abc import ABC, abstractmethod

from pam.common.models import DocumentInfo, RawDocument


class BaseConnector(ABC):
    @abstractmethod
    async def list_documents(self) -> list[DocumentInfo]:
        """List all available documents from this source."""
        ...

    @abstractmethod
    async def fetch_document(self, source_id: str) -> RawDocument:
        """Fetch raw document content by source ID."""
        ...

    @abstractmethod
    async def get_content_hash(self, source_id: str) -> str:
        """Get content hash for change detection without downloading full content."""
        ...
