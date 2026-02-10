"""Types for retrieval queries and results."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SearchQuery(BaseModel):
    query: str
    source_type: str | None = None
    project: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    top_k: int = Field(default=10, ge=1, le=50)


class SearchResult(BaseModel):
    segment_id: uuid.UUID
    content: str
    score: float
    source_url: str | None = None
    source_id: str | None = None
    section_path: str | None = None
    document_title: str | None = None
    segment_type: str = "text"
