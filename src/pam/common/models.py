"""SQLAlchemy ORM models and Pydantic schemas."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ── SQLAlchemy ORM ──────────────────────────────────────────────────────


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    documents: Mapped[list["Document"]] = relationship(back_populates="project")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(500), nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    owner: Mapped[str | None] = mapped_column(String(200))
    project_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("projects.id"))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="active")
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = ({"comment": "Source document registry"},)

    project: Mapped[Project | None] = relationship(back_populates="documents")
    segments: Mapped[list["Segment"]] = relationship(back_populates="document", cascade="all, delete-orphan")


class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    segment_type: Mapped[str] = mapped_column(String(50), nullable=False)
    section_path: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    document: Mapped[Document] = relationship(back_populates="segments")


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("documents.id"))
    action: Mapped[str] = mapped_column(String(50), nullable=False)
    segments_affected: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class IngestionTask(Base):
    __tablename__ = "ingestion_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    folder_path: Mapped[str] = mapped_column(Text, nullable=False)
    total_documents: Mapped[int] = mapped_column(Integer, default=0)
    processed_documents: Mapped[int] = mapped_column(Integer, default=0)
    succeeded: Mapped[int] = mapped_column(Integer, default=0)
    skipped: Mapped[int] = mapped_column(Integer, default=0)
    failed: Mapped[int] = mapped_column(Integer, default=0)
    results: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# ── Pydantic Schemas ────────────────────────────────────────────────────


class KnowledgeSegment(BaseModel):
    """Central data transfer object used throughout the ingestion pipeline."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    content: str
    content_hash: str
    embedding: list[float] | None = None

    # Provenance
    source_type: str
    source_id: str
    source_url: str | None = None
    section_path: str | None = None

    # Structure
    segment_type: str = "text"
    position: int = 0
    metadata: dict = Field(default_factory=dict)

    # Document info (populated during pipeline)
    document_title: str | None = None
    document_id: uuid.UUID | None = None


class DocumentResponse(BaseModel):
    id: uuid.UUID
    source_type: str
    source_id: str
    source_url: str | None
    title: str
    owner: str | None
    status: str
    content_hash: str | None
    last_synced_at: datetime | None
    created_at: datetime
    segment_count: int = 0

    model_config = {"from_attributes": True}


class DocumentInfo(BaseModel):
    """Lightweight document info returned by connectors."""

    source_id: str
    title: str
    owner: str | None = None
    source_url: str | None = None
    modified_at: datetime | None = None


class RawDocument(BaseModel):
    """Raw document content returned by connectors."""

    content: bytes
    content_type: str
    metadata: dict = Field(default_factory=dict)
    source_id: str
    title: str
    source_url: str | None = None
    owner: str | None = None


class IngestionTaskResponse(BaseModel):
    id: uuid.UUID
    status: str
    folder_path: str
    total_documents: int
    processed_documents: int
    succeeded: int
    skipped: int
    failed: int
    results: list[dict] = []
    error: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}


class TaskCreatedResponse(BaseModel):
    task_id: uuid.UUID
    status: str = "pending"
    message: str = "Ingestion task created"
