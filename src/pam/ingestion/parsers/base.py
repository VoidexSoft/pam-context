"""Base parser interface and parser-agnostic document format."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pam.common.models import RawDocument


@dataclass
class ParsedImage:
    """An image extracted during document parsing."""

    image_data: bytes | None = None
    caption: str | None = None
    page_number: int | None = None
    position: int = 0


@dataclass
class ParsedTable:
    """A table extracted during document parsing."""

    markdown: str
    caption: str | None = None
    page_number: int | None = None
    position: int = 0


@dataclass
class ParsedDocument:
    """Parser-agnostic intermediate document format.

    Both DoclingParser and MineruParser produce this format.
    The chunker and multimodal processor accept it.
    """

    markdown_content: str
    images: list[ParsedImage] = field(default_factory=list)
    tables: list[ParsedTable] = field(default_factory=list)
    _docling_doc: object | None = field(default=None, repr=False)


class BaseParser(ABC):
    """Abstract interface for document parsers."""

    @abstractmethod
    def parse(self, raw_document: RawDocument) -> ParsedDocument:
        """Parse a raw document into a ParsedDocument."""
        ...
