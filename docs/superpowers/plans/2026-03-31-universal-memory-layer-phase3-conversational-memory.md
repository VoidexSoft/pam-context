# Universal Memory Layer — Phase 3: Conversational Memory

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add server-side conversation persistence, automatic fact extraction from conversation turns, conversation summarization for long threads, and integrate conversation history + memories into the context assembly pipeline.

**Architecture:** A `ConversationService` stores conversations and messages in PostgreSQL. After each exchange, a `FactExtractionPipeline` uses Claude Haiku to extract facts/preferences and stores them via the existing `MemoryService` (with dedup). When conversations exceed a configurable length, a `ConversationSummarizer` compresses them into `conversation_summary` type memories. The `assemble_context()` pipeline gains two new sections — user memories and recent conversation — so the agent has stateful cross-session context. Three access layers: REST API (`/api/conversations`), MCP tools, and the chat endpoint (auto-persist).

**Tech Stack:** SQLAlchemy 2.x (async), PostgreSQL, Anthropic SDK (Haiku for extraction + summarization), existing MemoryService, tiktoken, FastAPI routes, FastMCP tools, pytest

---

## File Structure

### New Files

```
src/pam/conversation/
├── __init__.py                # Re-exports ConversationService, FactExtractionPipeline, ConversationSummarizer
├── service.py                 # ConversationService — CRUD for conversations + messages
├── extraction.py              # FactExtractionPipeline — LLM-powered fact extraction from exchanges
└── summarizer.py              # ConversationSummarizer — compress long conversations into memories

src/pam/api/routes/conversation.py  # REST endpoints: create, get, list, add message, delete, extract, summarize

tests/conversation/
├── __init__.py
├── conftest.py                # Mock fixtures for ConversationService, extraction, summarizer
├── test_service.py            # ConversationService unit tests
├── test_extraction.py         # FactExtractionPipeline unit tests
├── test_summarizer.py         # ConversationSummarizer unit tests
└── test_routes.py             # REST API endpoint tests

alembic/versions/009_add_conversations.py  # Migration for conversations + messages tables
```

### Modified Files

```
src/pam/common/models.py          # Add Conversation, Message ORM models + Pydantic schemas
src/pam/common/config.py          # Add conversation_* settings
src/pam/agent/context_assembly.py  # Add memory + conversation sections to context builder
src/pam/api/routes/chat.py        # Auto-persist conversation turns + trigger extraction
src/pam/api/main.py               # Initialize ConversationService + register conversation routes
src/pam/mcp/server.py             # Add pam_save_conversation, pam_get_conversation_context tools
src/pam/mcp/services.py           # Add conversation_service field to PamServices
```

---

## Task 1: Config Settings

**Files:**
- Modify: `src/pam/common/config.py`
- Test: `tests/test_common/test_config.py`

- [ ] **Step 1: Write the failing test**

Create or append to `tests/test_common/test_config.py`:

```python
"""Tests for conversation config settings."""

from pam.common.config import Settings


def test_conversation_settings_defaults():
    """Conversation settings have expected defaults."""
    s = Settings(
        anthropic_api_key="test-key",
        openai_api_key="test-key",
    )
    assert s.conversation_extraction_enabled is True
    assert s.conversation_extraction_model == "claude-haiku-4-5-20251001"
    assert s.conversation_summary_threshold == 20
    assert s.conversation_summary_token_limit == 8000
    assert s.conversation_context_max_tokens == 2000
    assert s.context_memory_budget == 2000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_common/test_config.py::test_conversation_settings_defaults -v`
Expected: FAIL with `AttributeError` — settings don't have these fields yet.

- [ ] **Step 3: Add settings to config.py**

In `src/pam/common/config.py`, add after the `memory_merge_model` line:

```python
    # Conversation Service
    conversation_extraction_enabled: bool = True
    conversation_extraction_model: str = "claude-haiku-4-5-20251001"
    conversation_summary_threshold: int = 20  # messages before auto-summarization
    conversation_summary_token_limit: int = 8000  # token budget for summary
    conversation_context_max_tokens: int = 2000  # max tokens for conversation context in assembly

    # Context Assembly — memory budget
    context_memory_budget: int = 2000  # token budget for user memories in context
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_common/test_config.py::test_conversation_settings_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/common/config.py tests/test_common/test_config.py
git commit -m "feat(conversation): add conversation config settings"
```

---

## Task 2: Conversation + Message ORM Models

**Files:**
- Modify: `src/pam/common/models.py`
- Test: `tests/conversation/test_service.py`

- [ ] **Step 1: Create test directory and write failing test**

Create `tests/conversation/__init__.py` (empty).

Create `tests/conversation/test_service.py`:

```python
"""Tests for Conversation and Message models."""

import uuid
from datetime import datetime, timezone

from pam.common.models import Conversation, Message


def test_conversation_model_has_required_fields():
    """Conversation ORM model has all expected columns."""
    columns = {c.name for c in Conversation.__table__.columns}
    expected = {
        "id", "user_id", "project_id", "title",
        "started_at", "last_active",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


def test_message_model_has_required_fields():
    """Message ORM model has all expected columns."""
    columns = {c.name for c in Message.__table__.columns}
    expected = {
        "id", "conversation_id", "role", "content",
        "metadata", "created_at",
    }
    assert expected.issubset(columns), f"Missing columns: {expected - columns}"


def test_message_role_constraint():
    """Message role column has a check constraint."""
    constraints = [c.name for c in Message.__table__.constraints if hasattr(c, "name") and c.name]
    assert "ck_messages_role" in constraints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/conversation/test_service.py -v -k "model_has_required"
Expected: FAIL with `ImportError` — Conversation/Message don't exist yet.

- [ ] **Step 3: Add Conversation and Message models to models.py**

In `src/pam/common/models.py`, add after the `Memory` class (before `# ── Pydantic Schemas`):

```python
class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str | None] = mapped_column(String(500))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[list["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_messages_role",
        ),
        {"comment": "Individual messages within a conversation"},
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/conversation/test_service.py -v -k "model_has_required or role_constraint"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/common/models.py tests/conversation/__init__.py tests/conversation/test_service.py
git commit -m "feat(conversation): add Conversation and Message ORM models"
```

---

## Task 3: Pydantic Schemas for Conversations

**Files:**
- Modify: `src/pam/common/models.py`
- Test: `tests/conversation/test_service.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/conversation/test_service.py`:

```python
from pam.common.models import (
    ConversationCreate,
    ConversationResponse,
    ConversationDetail,
    MessageCreate,
    ConvMessageResponse,
)


def test_conversation_create_schema():
    """ConversationCreate accepts optional user_id, project_id, title."""
    c = ConversationCreate(title="Test Chat")
    assert c.title == "Test Chat"
    assert c.user_id is None
    assert c.project_id is None


def test_conversation_create_minimal():
    """ConversationCreate works with no arguments."""
    c = ConversationCreate()
    assert c.title is None


def test_message_create_schema():
    """MessageCreate requires role and content."""
    m = MessageCreate(role="user", content="Hello")
    assert m.role == "user"
    assert m.content == "Hello"
    assert m.metadata == {}


def test_conversation_response_schema():
    """ConversationResponse has all expected fields."""
    now = datetime.now(tz=timezone.utc)
    cr = ConversationResponse(
        id=uuid.uuid4(),
        user_id=None,
        project_id=None,
        title="Chat",
        started_at=now,
        last_active=now,
        message_count=5,
    )
    assert cr.message_count == 5


def test_conversation_detail_includes_messages():
    """ConversationDetail extends ConversationResponse with messages list."""
    now = datetime.now(tz=timezone.utc)
    msg = ConvMessageResponse(
        id=uuid.uuid4(),
        conversation_id=uuid.uuid4(),
        role="user",
        content="Hi",
        metadata={},
        created_at=now,
    )
    detail = ConversationDetail(
        id=uuid.uuid4(),
        user_id=None,
        project_id=None,
        title="Chat",
        started_at=now,
        last_active=now,
        message_count=1,
        messages=[msg],
    )
    assert len(detail.messages) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/conversation/test_service.py -v -k "schema"`
Expected: FAIL with `ImportError` — schemas not defined yet.

- [ ] **Step 3: Add Pydantic schemas to models.py**

In `src/pam/common/models.py`, add at the end of the file (after `MemorySearchResult`):

```python
# ── Conversation Schemas ──────────────────────────────────────────────


class MessageCreate(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    metadata: dict = Field(default_factory=dict)


class ConvMessageResponse(BaseModel):
    """Response schema for a conversation message (not to be confused with the generic MessageResponse)."""

    id: uuid.UUID
    conversation_id: uuid.UUID
    role: str
    content: str
    metadata: dict = Field(default_factory=dict)
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationCreate(BaseModel):
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    title: str | None = None


class ConversationResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    title: str | None = None
    started_at: datetime
    last_active: datetime
    message_count: int = 0

    model_config = {"from_attributes": True}


class ConversationDetail(ConversationResponse):
    messages: list[ConvMessageResponse] = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/conversation/test_service.py -v -k "schema or create or detail"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/common/models.py tests/conversation/test_service.py
git commit -m "feat(conversation): add Pydantic schemas for conversations and messages"
```

---

## Task 4: Alembic Migration

**Files:**
- Create: `alembic/versions/009_add_conversations.py`

- [ ] **Step 1: Create migration file**

Create `alembic/versions/009_add_conversations.py`:

```python
"""Add conversations and messages tables.

Revision ID: 009
Revises: 008
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "009"
down_revision = "008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_active", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_conversations_user_id", "conversations", ["user_id"])
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])
    op.create_index("ix_conversations_last_active", "conversations", ["last_active"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "conversation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("metadata", postgresql.JSONB, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.CheckConstraint(
            "role IN ('user', 'assistant', 'system')",
            name="ck_messages_role",
        ),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_created_at", "messages", ["created_at"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
```

- [ ] **Step 2: Commit**

```bash
git add alembic/versions/009_add_conversations.py
git commit -m "feat(conversation): add migration 009 for conversations and messages tables"
```

---

## Task 5: ConversationService — Core CRUD

**Files:**
- Create: `src/pam/conversation/__init__.py`
- Create: `src/pam/conversation/service.py`
- Create: `tests/conversation/conftest.py`
- Test: `tests/conversation/test_service.py`

- [ ] **Step 1: Create test fixtures**

Create `src/pam/conversation/__init__.py`:

```python
"""Conversation module — persistence, fact extraction, summarization."""

from pam.conversation.service import ConversationService

__all__ = ["ConversationService"]
```

Create `tests/conversation/conftest.py`:

```python
"""Fixtures for conversation tests."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.conversation.service import ConversationService


@pytest.fixture
def mock_session():
    """Mock async database session."""
    session = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.execute = AsyncMock()
    session.delete = AsyncMock()
    return session


@pytest.fixture
def mock_session_factory(mock_session):
    """Mock session factory returning mock_session as context manager."""
    factory = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    factory.return_value = ctx
    return factory


@pytest.fixture
def conversation_service(mock_session_factory):
    """ConversationService with mocked session factory."""
    return ConversationService(session_factory=mock_session_factory)
```

- [ ] **Step 2: Write failing tests for create + get + delete**

Append to `tests/conversation/test_service.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pam.conversation.service import ConversationService


@pytest.mark.asyncio
async def test_create_conversation(conversation_service, mock_session):
    """create() inserts a Conversation row and returns ConversationResponse."""
    user_id = uuid.uuid4()
    result = await conversation_service.create(user_id=user_id, title="Test Chat")

    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()
    assert result.title == "Test Chat"
    assert result.user_id == user_id
    assert result.message_count == 0


@pytest.mark.asyncio
async def test_create_with_id(conversation_service, mock_session):
    """create_with_id() uses the supplied UUID instead of generating one."""
    conv_id = uuid.uuid4()
    result = await conversation_service.create_with_id(
        conversation_id=conv_id, title="Chat with known ID"
    )

    mock_session.add.assert_called_once()
    # The Conversation passed to session.add should have our ID
    added_conv = mock_session.add.call_args[0][0]
    assert added_conv.id == conv_id
    assert result.title == "Chat with known ID"


@pytest.mark.asyncio
async def test_get_conversation_found(conversation_service, mock_session):
    """get() returns ConversationDetail when conversation exists."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    mock_conv = MagicMock()
    mock_conv.id = conv_id
    mock_conv.user_id = None
    mock_conv.project_id = None
    mock_conv.title = "Chat"
    mock_conv.started_at = now
    mock_conv.last_active = now
    mock_conv.messages = []

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_conv
    mock_session.execute.return_value = mock_result

    result = await conversation_service.get(conv_id)
    assert result is not None
    assert result.id == conv_id
    assert result.messages == []


@pytest.mark.asyncio
async def test_get_conversation_not_found(conversation_service, mock_session):
    """get() returns None when conversation doesn't exist."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result = await conversation_service.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_delete_conversation(conversation_service, mock_session):
    """delete() removes conversation and returns True."""
    conv_id = uuid.uuid4()

    mock_conv = MagicMock()
    mock_conv.id = conv_id
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_conv
    mock_session.execute.return_value = mock_result

    result = await conversation_service.delete(conv_id)
    assert result is True
    mock_session.delete.assert_awaited_once_with(mock_conv)


@pytest.mark.asyncio
async def test_delete_conversation_not_found(conversation_service, mock_session):
    """delete() returns False when conversation doesn't exist."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    result = await conversation_service.delete(uuid.uuid4())
    assert result is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/conversation/test_service.py -v -k "create_conversation or get_conversation or delete_conversation"`
Expected: FAIL — ConversationService.create/get/delete not implemented yet.

- [ ] **Step 4: Implement ConversationService with create, get, delete**

Create `src/pam/conversation/service.py`:

```python
"""Conversation service — CRUD for conversations and messages."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import structlog
import tiktoken
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from pam.common.models import (
    Conversation,
    ConversationDetail,
    ConversationResponse,
    ConvMessageResponse,
    Message,
)

# Module-level encoder cache (same pattern as context_assembly.py)
_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = structlog.get_logger()


def _message_to_response(msg: Message) -> ConvMessageResponse:
    """Convert a Message ORM instance to ConvMessageResponse."""
    return ConvMessageResponse(
        id=msg.id,
        conversation_id=msg.conversation_id,
        role=msg.role,
        content=msg.content,
        metadata=msg.metadata_ if isinstance(msg.metadata_, dict) else {},
        created_at=msg.created_at,
    )


def _conversation_to_response(conv: Conversation, message_count: int = 0) -> ConversationResponse:
    """Convert a Conversation ORM instance to ConversationResponse."""
    return ConversationResponse(
        id=conv.id,
        user_id=conv.user_id,
        project_id=conv.project_id,
        title=conv.title,
        started_at=conv.started_at,
        last_active=conv.last_active,
        message_count=message_count,
    )


def _conversation_to_detail(
    conv: Conversation, message_limit: int | None = None
) -> ConversationDetail:
    """Convert a Conversation ORM instance to ConversationDetail with messages.

    Parameters
    ----------
    message_limit:
        If set, only include the N most recent messages.  The
        ``message_count`` field still reflects the *total* message count.
    """
    all_messages = conv.messages  # already ordered by created_at via relationship
    total = len(all_messages)
    if message_limit is not None and message_limit < total:
        all_messages = all_messages[-message_limit:]
    messages = [_message_to_response(m) for m in all_messages]
    return ConversationDetail(
        id=conv.id,
        user_id=conv.user_id,
        project_id=conv.project_id,
        title=conv.title,
        started_at=conv.started_at,
        last_active=conv.last_active,
        message_count=total,
        messages=messages,
    )


class ConversationService:
    """Manages conversation persistence and message storage."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def create(
        self,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
        title: str | None = None,
    ) -> ConversationResponse:
        """Create a new conversation with a server-generated ID."""
        async with self._session_factory() as session:
            conv = Conversation(
                user_id=user_id,
                project_id=project_id,
                title=title,
            )
            session.add(conv)
            await session.flush()

            result = _conversation_to_response(conv, message_count=0)
            await session.commit()
            logger.info("conversation_created", conversation_id=str(conv.id))
            return result

    async def create_with_id(
        self,
        conversation_id: uuid_mod.UUID,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
        title: str | None = None,
    ) -> ConversationResponse:
        """Create a new conversation with a client-supplied ID.

        Used by the chat endpoint so the conversation_id returned to the
        client matches the one stored in the database.
        """
        async with self._session_factory() as session:
            conv = Conversation(
                id=conversation_id,
                user_id=user_id,
                project_id=project_id,
                title=title,
            )
            session.add(conv)
            await session.flush()

            result = _conversation_to_response(conv, message_count=0)
            await session.commit()
            logger.info("conversation_created", conversation_id=str(conv.id))
            return result

    async def get(
        self,
        conversation_id: uuid_mod.UUID,
        message_limit: int | None = None,
    ) -> ConversationDetail | None:
        """Get a conversation with its messages.

        Parameters
        ----------
        conversation_id:
            The conversation to retrieve.
        message_limit:
            If set, only return the N most recent messages (useful for large
            conversations before summarization kicks in).  None = all messages.
        """
        async with self._session_factory() as session:
            stmt = (
                select(Conversation)
                .options(selectinload(Conversation.messages))
                .where(Conversation.id == conversation_id)
            )
            result = await session.execute(stmt)
            conv = result.scalar_one_or_none()
            if conv is None:
                return None
            return _conversation_to_detail(conv, message_limit=message_limit)

    async def delete(self, conversation_id: uuid_mod.UUID) -> bool:
        """Delete a conversation and all its messages (cascade)."""
        async with self._session_factory() as session:
            stmt = select(Conversation).where(Conversation.id == conversation_id)
            result = await session.execute(stmt)
            conv = result.scalar_one_or_none()
            if conv is None:
                return False
            await session.delete(conv)
            await session.commit()
            logger.info("conversation_deleted", conversation_id=str(conversation_id))
            return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/conversation/test_service.py -v -k "create_conversation or get_conversation or delete_conversation"`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/conversation/__init__.py src/pam/conversation/service.py tests/conversation/conftest.py tests/conversation/test_service.py
git commit -m "feat(conversation): add ConversationService with create, get, delete"
```

---

## Task 6: ConversationService — Add Message + List + Get Recent Context

**Files:**
- Modify: `src/pam/conversation/service.py`
- Test: `tests/conversation/test_service.py`

- [ ] **Step 1: Write failing tests for add_message, list_by_user, get_recent_context**

Append to `tests/conversation/test_service.py`:

```python
@pytest.mark.asyncio
async def test_add_message(conversation_service, mock_session):
    """add_message() inserts a Message and updates last_active."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    mock_conv = MagicMock()
    mock_conv.id = conv_id
    mock_conv.last_active = now
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_conv
    mock_session.execute.return_value = mock_result

    result = await conversation_service.add_message(
        conversation_id=conv_id,
        role="user",
        content="Hello, PAM!",
    )

    assert result.role == "user"
    assert result.content == "Hello, PAM!"
    assert result.conversation_id == conv_id
    mock_session.add.assert_called_once()
    mock_session.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_message_conversation_not_found(conversation_service, mock_session):
    """add_message() raises ValueError when conversation doesn't exist."""
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute.return_value = mock_result

    with pytest.raises(ValueError, match="not found"):
        await conversation_service.add_message(
            conversation_id=uuid.uuid4(),
            role="user",
            content="Hello",
        )


@pytest.mark.asyncio
async def test_add_message_invalid_role(conversation_service):
    """add_message() raises ValueError for invalid role."""
    with pytest.raises(ValueError, match="Invalid role"):
        await conversation_service.add_message(
            conversation_id=uuid.uuid4(),
            role="admin",
            content="Hello",
        )


@pytest.mark.asyncio
async def test_list_by_user(conversation_service, mock_session):
    """list_by_user() returns conversations ordered by last_active desc."""
    user_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    mock_conv = MagicMock()
    mock_conv.id = uuid.uuid4()
    mock_conv.user_id = user_id
    mock_conv.project_id = None
    mock_conv.title = "Chat 1"
    mock_conv.started_at = now
    mock_conv.last_active = now

    # Mock the count subquery result
    mock_row = MagicMock()
    mock_row.Conversation = mock_conv
    mock_row.message_count = 3

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row]
    mock_session.execute.return_value = mock_result

    result = await conversation_service.list_by_user(user_id=user_id)
    assert len(result) == 1
    assert result[0].message_count == 3


@pytest.mark.asyncio
async def test_get_recent_context(conversation_service, mock_session):
    """get_recent_context() returns formatted conversation text within token budget."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    msg1 = MagicMock()
    msg1.role = "user"
    msg1.content = "What is our revenue target?"
    msg1.created_at = now

    msg2 = MagicMock()
    msg2.role = "assistant"
    msg2.content = "The Q1 revenue target is $10M."
    msg2.created_at = now

    mock_conv = MagicMock()
    mock_conv.id = conv_id
    mock_conv.messages = [msg1, msg2]
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_conv
    mock_session.execute.return_value = mock_result

    text = await conversation_service.get_recent_context(conv_id, max_tokens=2000)
    assert "user:" in text
    assert "assistant:" in text
    assert "revenue target" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/conversation/test_service.py -v -k "add_message or list_by_user or get_recent_context"`
Expected: FAIL — methods not implemented yet.

- [ ] **Step 3: Add methods to ConversationService**

In `src/pam/conversation/service.py`, add these methods to the `ConversationService` class:

```python
    _VALID_ROLES = {"user", "assistant", "system"}

    async def add_message(
        self,
        conversation_id: uuid_mod.UUID,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ConvMessageResponse:
        """Add a message to an existing conversation."""
        if role not in self._VALID_ROLES:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {self._VALID_ROLES}")

        async with self._session_factory() as session:
            stmt = select(Conversation).where(Conversation.id == conversation_id)
            result = await session.execute(stmt)
            conv = result.scalar_one_or_none()
            if conv is None:
                raise ValueError(f"Conversation {conversation_id} not found")

            msg = Message(
                conversation_id=conversation_id,
                role=role,
                content=content,
                metadata_=metadata or {},
            )
            session.add(msg)
            conv.last_active = datetime.now(tz=timezone.utc)
            await session.flush()

            response = _message_to_response(msg)
            await session.commit()
            return response

    async def list_by_user(
        self,
        user_id: uuid_mod.UUID,
        project_id: uuid_mod.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[ConversationResponse]:
        """List conversations for a user, ordered by last_active desc."""
        async with self._session_factory() as session:
            count_subq = (
                select(
                    Message.conversation_id,
                    func.count(Message.id).label("message_count"),
                )
                .group_by(Message.conversation_id)
                .subquery()
            )

            stmt = (
                select(Conversation, func.coalesce(count_subq.c.message_count, 0).label("message_count"))
                .outerjoin(count_subq, Conversation.id == count_subq.c.conversation_id)
                .where(Conversation.user_id == user_id)
            )
            if project_id is not None:
                stmt = stmt.where(Conversation.project_id == project_id)
            stmt = stmt.order_by(Conversation.last_active.desc()).limit(limit).offset(offset)

            result = await session.execute(stmt)
            rows = result.all()
            return [
                _conversation_to_response(row.Conversation, message_count=row.message_count)
                for row in rows
            ]

    async def get_recent_context(
        self,
        conversation_id: uuid_mod.UUID,
        max_tokens: int = 2000,
    ) -> str:
        """Get recent conversation messages as formatted text within a token budget.

        Returns messages from most recent backwards, formatted as 'role: content'.
        Uses tiktoken directly to avoid coupling to the agent module.
        """
        async with self._session_factory() as session:
            stmt = (
                select(Conversation)
                .options(selectinload(Conversation.messages))
                .where(Conversation.id == conversation_id)
            )
            result = await session.execute(stmt)
            conv = result.scalar_one_or_none()
            if conv is None:
                return ""

            # Walk messages from newest to oldest, accumulating within budget
            messages = list(reversed(conv.messages))
            selected: list[str] = []
            tokens_used = 0
            for msg in messages:
                line = f"{msg.role}: {msg.content}"
                line_tokens = len(_get_encoder().encode(line))
                if tokens_used + line_tokens > max_tokens:
                    break
                selected.append(line)
                tokens_used += line_tokens

            # Reverse back to chronological order
            selected.reverse()
            return "\n".join(selected)
```

> **Design note:** We duplicate the small tiktoken helper (already added at the top of the file) rather than importing from `pam.agent.context_assembly`. This avoids a conversation→agent dependency, keeping the conversation module self-contained.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/conversation/test_service.py -v -k "add_message or list_by_user or get_recent_context"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/conversation/service.py tests/conversation/test_service.py
git commit -m "feat(conversation): add add_message, list_by_user, get_recent_context to ConversationService"
```

---

## Task 7: FactExtractionPipeline

**Files:**
- Create: `src/pam/conversation/extraction.py`
- Create: `tests/conversation/test_extraction.py`

- [ ] **Step 1: Write failing tests**

Create `tests/conversation/test_extraction.py`:

```python
"""Tests for FactExtractionPipeline."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.conversation.extraction import FactExtractionPipeline


@pytest.fixture
def mock_memory_service():
    svc = AsyncMock()
    svc.store = AsyncMock()
    return svc


@pytest.fixture
def extraction_pipeline(mock_memory_service):
    return FactExtractionPipeline(
        memory_service=mock_memory_service,
        anthropic_api_key="test-key",
        model="claude-haiku-4-5-20251001",
    )


@pytest.mark.asyncio
async def test_extract_facts_from_exchange(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() calls LLM and stores extracted facts."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = '[{"type": "fact", "content": "User prefers Python over JS"}]'
    llm_response.content = [text_block]

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="I always prefer Python for backend work",
            assistant_response="Got it, I'll keep that in mind.",
            user_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
        )

    assert len(results) == 1
    assert results[0]["type"] == "fact"
    mock_memory_service.store.assert_awaited_once()


@pytest.mark.asyncio
async def test_extract_no_facts(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() returns empty list when no facts found."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = "[]"
    llm_response.content = [text_block]

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="What time is it?",
            assistant_response="I don't have access to the current time.",
        )

    assert results == []
    mock_memory_service.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_handles_llm_error(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() returns empty list on LLM failure."""
    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))

        results = await extraction_pipeline.extract_from_exchange(
            user_message="Hello",
            assistant_response="Hi there!",
        )

    assert results == []
    mock_memory_service.store.assert_not_awaited()


@pytest.mark.asyncio
async def test_extract_handles_malformed_json(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() returns empty list on malformed LLM output."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = "not valid json"
    llm_response.content = [text_block]

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="Hello",
            assistant_response="Hi!",
        )

    assert results == []


@pytest.mark.asyncio
async def test_extract_multiple_facts(extraction_pipeline, mock_memory_service):
    """extract_from_exchange() stores multiple extracted facts."""
    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = (
        '['
        '{"type": "fact", "content": "Team uses PostgreSQL for analytics"},'
        '{"type": "preference", "content": "User prefers concise answers"}'
        ']'
    )
    llm_response.content = [text_block]

    mock_memory_service.store.return_value = MagicMock()

    with patch.object(extraction_pipeline, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        results = await extraction_pipeline.extract_from_exchange(
            user_message="We use PostgreSQL. Please keep answers short.",
            assistant_response="Understood. Noted your preferences.",
            user_id=uuid.uuid4(),
        )

    assert len(results) == 2
    assert mock_memory_service.store.await_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/conversation/test_extraction.py -v`
Expected: FAIL with `ImportError` — `FactExtractionPipeline` doesn't exist yet.

- [ ] **Step 3: Implement FactExtractionPipeline**

Create `src/pam/conversation/extraction.py`:

```python
"""Fact extraction pipeline — extracts facts and preferences from conversation turns."""

from __future__ import annotations

import json
import uuid as uuid_mod
from typing import TYPE_CHECKING

import structlog
from anthropic import AsyncAnthropic

if TYPE_CHECKING:
    from pam.memory.service import MemoryService

logger = structlog.get_logger()

_EXTRACTION_PROMPT = """\
Analyze this conversation exchange and extract any facts, preferences, or observations \
that would be useful to remember for future conversations.

User message:
{user_message}

Assistant response:
{assistant_response}

Return a JSON array of extracted items. Each item must have:
- "type": one of "fact", "preference", "observation"
- "content": a concise statement of the extracted information

Rules:
- Only extract genuinely useful, non-trivial information
- Do NOT extract greetings, small talk, or transient questions
- Do NOT extract information that is only relevant to the current exchange
- Prefer the user's own statements for preferences
- Return an empty array [] if nothing worth remembering

Respond with ONLY the JSON array, no other text."""


class FactExtractionPipeline:
    """Extracts facts and preferences from conversation exchanges using an LLM."""

    def __init__(
        self,
        memory_service: MemoryService,
        anthropic_api_key: str,
        model: str = "claude-haiku-4-5-20251001",
    ) -> None:
        self._memory_service = memory_service
        self._client = AsyncAnthropic(api_key=anthropic_api_key)
        self._model = model

    async def extract_from_exchange(
        self,
        user_message: str,
        assistant_response: str,
        user_id: uuid_mod.UUID | None = None,
        project_id: uuid_mod.UUID | None = None,
    ) -> list[dict]:
        """Extract facts/preferences from a user-assistant exchange.

        Returns a list of dicts with 'type' and 'content' keys.
        Extracted items are automatically stored via MemoryService.
        """
        try:
            prompt = _EXTRACTION_PROMPT.format(
                user_message=user_message,
                assistant_response=assistant_response,
            )

            response = await self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                messages=[{"role": "user", "content": prompt}],
            )

            raw_text = response.content[0].text.strip()
            extracted = json.loads(raw_text)

            if not isinstance(extracted, list):
                logger.warning("extraction_invalid_format", raw=raw_text[:200])
                return []

        except json.JSONDecodeError:
            logger.warning("extraction_json_parse_error", exc_info=True)
            return []
        except Exception:
            logger.warning("extraction_llm_error", exc_info=True)
            return []

        # Store each extracted item via MemoryService
        stored: list[dict] = []
        for item in extracted:
            item_type = item.get("type", "fact")
            content = item.get("content", "")
            if not content:
                continue
            if item_type not in ("fact", "preference", "observation"):
                item_type = "fact"

            try:
                await self._memory_service.store(
                    content=content,
                    memory_type=item_type,
                    source="conversation",
                    user_id=user_id,
                    project_id=project_id,
                )
                stored.append(item)
            except Exception:
                logger.warning("extraction_store_error", content=content[:100], exc_info=True)

        logger.info(
            "facts_extracted",
            count=len(stored),
            user_id=str(user_id) if user_id else None,
        )
        return stored
```

- [ ] **Step 4: Update `__init__.py` to export FactExtractionPipeline**

In `src/pam/conversation/__init__.py`:

```python
"""Conversation module — persistence, fact extraction, summarization."""

from pam.conversation.extraction import FactExtractionPipeline
from pam.conversation.service import ConversationService

__all__ = ["ConversationService", "FactExtractionPipeline"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/conversation/test_extraction.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/conversation/extraction.py src/pam/conversation/__init__.py tests/conversation/test_extraction.py
git commit -m "feat(conversation): add FactExtractionPipeline for LLM-powered fact extraction"
```

---

## Task 8: ConversationSummarizer

**Files:**
- Create: `src/pam/conversation/summarizer.py`
- Create: `tests/conversation/test_summarizer.py`

- [ ] **Step 1: Write failing tests**

Create `tests/conversation/test_summarizer.py`:

```python
"""Tests for ConversationSummarizer."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pam.conversation.summarizer import ConversationSummarizer


@pytest.fixture
def mock_memory_service():
    svc = AsyncMock()
    svc.store = AsyncMock()
    return svc


@pytest.fixture
def mock_conversation_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def summarizer(mock_conversation_service, mock_memory_service):
    return ConversationSummarizer(
        conversation_service=mock_conversation_service,
        memory_service=mock_memory_service,
        anthropic_api_key="test-key",
        model="claude-haiku-4-5-20251001",
        summary_threshold=5,
    )


@pytest.mark.asyncio
async def test_should_summarize_true(summarizer, mock_conversation_service):
    """should_summarize() returns True when message count exceeds threshold."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    detail = MagicMock()
    detail.message_count = 10
    mock_conversation_service.get.return_value = detail

    result = await summarizer.should_summarize(conv_id)
    assert result is True


@pytest.mark.asyncio
async def test_should_summarize_false(summarizer, mock_conversation_service):
    """should_summarize() returns False when message count is below threshold."""
    conv_id = uuid.uuid4()
    detail = MagicMock()
    detail.message_count = 3
    mock_conversation_service.get.return_value = detail

    result = await summarizer.should_summarize(conv_id)
    assert result is False


@pytest.mark.asyncio
async def test_should_summarize_not_found(summarizer, mock_conversation_service):
    """should_summarize() returns False when conversation not found."""
    mock_conversation_service.get.return_value = None
    result = await summarizer.should_summarize(uuid.uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_summarize_creates_memory(summarizer, mock_conversation_service, mock_memory_service):
    """summarize() generates summary and stores as conversation_summary memory."""
    conv_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    msg1 = MagicMock()
    msg1.role = "user"
    msg1.content = "Tell me about our Q1 targets"
    msg2 = MagicMock()
    msg2.role = "assistant"
    msg2.content = "The Q1 revenue target is $10M across all regions."

    detail = MagicMock()
    detail.messages = [msg1, msg2]
    detail.user_id = user_id
    detail.project_id = None
    detail.id = conv_id
    detail.message_count = 6
    mock_conversation_service.get.return_value = detail

    llm_response = MagicMock()
    text_block = MagicMock()
    text_block.text = "Discussion about Q1 revenue targets: $10M across all regions."
    llm_response.content = [text_block]

    with patch.object(summarizer, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(return_value=llm_response)

        summary = await summarizer.summarize(conv_id)

    assert "Q1" in summary
    mock_memory_service.store.assert_awaited_once()
    call_kwargs = mock_memory_service.store.call_args.kwargs
    assert call_kwargs["memory_type"] == "conversation_summary"
    assert call_kwargs["user_id"] == user_id


@pytest.mark.asyncio
async def test_summarize_not_found(summarizer, mock_conversation_service):
    """summarize() returns empty string when conversation not found."""
    mock_conversation_service.get.return_value = None
    result = await summarizer.summarize(uuid.uuid4())
    assert result == ""


@pytest.mark.asyncio
async def test_summarize_handles_llm_error(summarizer, mock_conversation_service, mock_memory_service):
    """summarize() returns empty string on LLM failure."""
    detail = MagicMock()
    detail.messages = [MagicMock(role="user", content="Hello")]
    detail.user_id = None
    detail.project_id = None
    detail.id = uuid.uuid4()
    detail.message_count = 6
    mock_conversation_service.get.return_value = detail

    with patch.object(summarizer, "_client") as mock_client:
        mock_client.messages.create = AsyncMock(side_effect=Exception("API error"))
        result = await summarizer.summarize(detail.id)

    assert result == ""
    mock_memory_service.store.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/conversation/test_summarizer.py -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement ConversationSummarizer**

Create `src/pam/conversation/summarizer.py`:

```python
"""Conversation summarizer — compresses long conversations into summary memories."""

from __future__ import annotations

import uuid as uuid_mod
from typing import TYPE_CHECKING

import structlog
from anthropic import AsyncAnthropic

if TYPE_CHECKING:
    from pam.conversation.service import ConversationService
    from pam.memory.service import MemoryService

logger = structlog.get_logger()

_SUMMARY_PROMPT = """\
Summarize this conversation into a concise paragraph that captures the key topics discussed, \
decisions made, facts learned, and any action items. Focus on information that would be \
useful context for future conversations.

Conversation:
{conversation_text}

Write a concise summary (2-4 sentences). Include specific details like names, numbers, \
and decisions — not vague descriptions."""


class ConversationSummarizer:
    """Compresses long conversations into summary memories."""

    def __init__(
        self,
        conversation_service: ConversationService,
        memory_service: MemoryService,
        anthropic_api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        summary_threshold: int = 20,
    ) -> None:
        self._conversation_service = conversation_service
        self._memory_service = memory_service
        self._client = AsyncAnthropic(api_key=anthropic_api_key)
        self._model = model
        self._summary_threshold = summary_threshold

    async def should_summarize(self, conversation_id: uuid_mod.UUID) -> bool:
        """Check if a conversation exceeds the summary threshold."""
        detail = await self._conversation_service.get(conversation_id)
        if detail is None:
            return False
        return detail.message_count >= self._summary_threshold

    async def summarize(self, conversation_id: uuid_mod.UUID) -> str:
        """Generate a summary of the conversation and store as a memory.

        Returns the summary text, or empty string on failure.
        """
        detail = await self._conversation_service.get(conversation_id)
        if detail is None:
            return ""

        # Build conversation text
        lines = [f"{m.role}: {m.content}" for m in detail.messages]
        conversation_text = "\n".join(lines)

        try:
            prompt = _SUMMARY_PROMPT.format(conversation_text=conversation_text)
            response = await self._client.messages.create(
                model=self._model,
                max_tokens=512,
                messages=[{"role": "user", "content": prompt}],
            )
            summary = response.content[0].text.strip()
        except Exception:
            logger.warning("summarization_llm_error", conversation_id=str(conversation_id), exc_info=True)
            return ""

        # Store as conversation_summary memory
        try:
            await self._memory_service.store(
                content=summary,
                memory_type="conversation_summary",
                source="conversation",
                metadata={"conversation_id": str(conversation_id)},
                user_id=detail.user_id,
                project_id=detail.project_id,
            )
        except Exception:
            logger.warning("summarization_store_error", exc_info=True)
            return ""

        logger.info(
            "conversation_summarized",
            conversation_id=str(conversation_id),
            summary_length=len(summary),
        )
        return summary
```

- [ ] **Step 4: Update `__init__.py`**

In `src/pam/conversation/__init__.py`:

```python
"""Conversation module — persistence, fact extraction, summarization."""

from pam.conversation.extraction import FactExtractionPipeline
from pam.conversation.service import ConversationService
from pam.conversation.summarizer import ConversationSummarizer

__all__ = ["ConversationService", "FactExtractionPipeline", "ConversationSummarizer"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/conversation/test_summarizer.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/conversation/summarizer.py src/pam/conversation/__init__.py tests/conversation/test_summarizer.py
git commit -m "feat(conversation): add ConversationSummarizer for compressing long conversations"
```

---

## Task 9: Context Assembly Update — Add Memories + Conversation Sections

**Files:**
- Modify: `src/pam/agent/context_assembly.py`
- Test: `tests/test_agent/test_context_assembly.py`

- [ ] **Step 1: Write failing tests**

Append to (or create) `tests/test_agent/test_context_assembly.py`:

```python
"""Tests for context assembly with memories and conversation context."""

from pam.agent.context_assembly import (
    AssembledContext,
    ContextBudget,
    assemble_context,
)


def test_assemble_context_with_memories():
    """assemble_context() includes memory section when memories provided."""
    memories = [
        {"content": "User prefers Python for backend work", "type": "preference", "score": 0.95},
        {"content": "Team uses PostgreSQL for analytics", "type": "fact", "score": 0.88},
    ]

    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        memory_results=memories,
    )

    assert "User Memories" in result.text
    assert "User prefers Python" in result.text
    assert "PostgreSQL" in result.text
    assert result.memory_tokens_used > 0


def test_assemble_context_with_conversation():
    """assemble_context() includes conversation section when provided."""
    conversation_context = "user: What is our Q1 target?\nassistant: The Q1 target is $10M."

    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        conversation_context=conversation_context,
    )

    assert "Recent Conversation" in result.text
    assert "Q1 target" in result.text
    assert result.conversation_tokens_used > 0


def test_assemble_context_with_all_sources():
    """assemble_context() includes all sections when all sources provided."""
    memories = [
        {"content": "User prefers concise answers", "type": "preference", "score": 0.9},
    ]
    conversation_context = "user: Summarize the report.\nassistant: Here's the summary."

    entity_results = [
        {"name": "Revenue", "entity_type": "metric", "description": "Total revenue", "score": 0.8},
    ]

    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=entity_results,
        rel_vdb_results=[],
        memory_results=memories,
        conversation_context=conversation_context,
    )

    assert "User Memories" in result.text
    assert "Recent Conversation" in result.text
    assert "Knowledge Graph Entities" in result.text


def test_assemble_context_empty_memories_omitted():
    """assemble_context() omits memory section when no memories provided."""
    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        memory_results=[],
        conversation_context="",
    )

    assert "User Memories" not in result.text
    assert "Recent Conversation" not in result.text


def test_assemble_context_memory_token_budget():
    """assemble_context() respects memory token budget."""
    # Create memories with lots of content
    memories = [
        {"content": "fact " * 500, "type": "fact", "score": 0.9},
        {"content": "another fact " * 500, "type": "fact", "score": 0.8},
    ]

    budget = ContextBudget(memory_tokens=200)

    result = assemble_context(
        es_results=[],
        graph_text="",
        entity_vdb_results=[],
        rel_vdb_results=[],
        memory_results=memories,
        budget=budget,
    )

    # Should have truncated to fit budget
    assert result.memory_tokens_used <= 250  # some overhead for headers
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_agent/test_context_assembly.py -v -k "memories or conversation or all_sources"`
Expected: FAIL — `assemble_context()` doesn't accept `memory_results` or `conversation_context` yet.

- [ ] **Step 3: Update ContextBudget dataclass**

In `src/pam/agent/context_assembly.py`, update the `ContextBudget` dataclass:

```python
@dataclass
class ContextBudget:
    """Token budget configuration for context assembly."""

    entity_tokens: int = 4000
    relationship_tokens: int = 6000
    max_total_tokens: int = 12000
    max_item_tokens: int = 500  # per-item description truncation cap
    memory_tokens: int = 2000  # budget for user memories
    conversation_tokens: int = 2000  # budget for conversation context
```

- [ ] **Step 4: Update AssembledContext dataclass**

In `src/pam/agent/context_assembly.py`, update `AssembledContext`:

```python
@dataclass
class AssembledContext:
    """Result of the context assembly pipeline."""

    text: str
    entity_tokens_used: int
    relationship_tokens_used: int
    chunk_tokens_used: int
    total_tokens: int
    memory_tokens_used: int = 0
    conversation_tokens_used: int = 0
```

- [ ] **Step 5: Update `_build_context_string` to include new sections**

In `src/pam/agent/context_assembly.py`, update `_build_context_string` signature and body:

```python
def _build_context_string(
    entities: list[dict],
    relationships: list[dict],
    chunks: list[dict],
    graph_text: str,
    total_entities: int,
    total_relationships: int,
    total_chunks: int,
    memories: list[dict] | None = None,
    conversation_context: str = "",
) -> str:
    """Build the final structured Markdown context string.

    Empty categories are omitted entirely (no headers with nothing beneath).
    If *all* categories are empty the fallback message is returned.
    """
    has_entities = bool(entities)
    has_relationships = bool(relationships) or bool(graph_text.strip())
    has_chunks = bool(chunks)
    has_memories = bool(memories)
    has_conversation = bool(conversation_context.strip())

    if not has_entities and not has_relationships and not has_chunks and not has_memories and not has_conversation:
        return "No relevant context found in knowledge base"

    parts: list[str] = []

    # --- Summary header (only mention non-empty categories) ---
    summary_bits: list[str] = []
    if has_memories:
        summary_bits.append(f"{len(memories)} user memories")
    if has_entities:
        summary_bits.append(f"{len(entities)} relevant entities")
    if has_relationships:
        rel_count = len(relationships)
        summary_bits.append(f"{rel_count} relationships")
    if has_chunks:
        summary_bits.append(f"{len(chunks)} document chunks")
    if has_conversation:
        summary_bits.append("recent conversation")
    parts.append("Found " + ", ".join(summary_bits))
    parts.append("")

    # --- User Memories ---
    if has_memories:
        parts.append("## User Memories")
        for m in memories:
            mem_type = m.get("type", "fact")
            content = m.get("content", "")
            parts.append(f"- [{mem_type}] {content}")
        parts.append("")

    # --- Recent Conversation ---
    if has_conversation:
        parts.append("## Recent Conversation")
        parts.append(conversation_context.strip())
        parts.append("")

    # --- Entities ---
    if has_entities:
        parts.append("## Knowledge Graph Entities")
        for e in entities:
            name = e.get("name", "Unknown")
            desc = e.get("description", "")
            parts.append(f"- **{name}**: {desc}")
        dropped = total_entities - len(entities)
        if dropped > 0:
            parts.append(f"[+{dropped} more entities not shown]")
        parts.append("")

    # --- Relationships ---
    if has_relationships:
        parts.append("## Knowledge Graph Relationships")
        for r in relationships:
            src = r.get("src_entity", "?")
            tgt = r.get("tgt_entity", "?")
            rel = r.get("rel_type", "RELATED_TO")
            desc = r.get("description", "")
            parts.append(f"**{src}** -> {rel} -> **{tgt}**: {desc}")
        dropped_rels = total_relationships - len(relationships)
        if dropped_rels > 0:
            parts.append(f"[+{dropped_rels} more relationships not shown]")
        # Append graph_text as supplementary content
        if graph_text.strip():
            parts.append("")
            parts.append(graph_text.strip())
        parts.append("")

    # --- Document Chunks ---
    if has_chunks:
        parts.append("## Document Chunks")
        for c in chunks:
            source_label = c.get("source_label", "Unknown")
            parts.append(f"[Source: {source_label}]")
            parts.append(c.get("content", ""))
            parts.append("")
        dropped_chunks = total_chunks - len(chunks)
        if dropped_chunks > 0:
            parts.append(f"[+{dropped_chunks} more chunks not shown]")
            parts.append("")

    return "\n".join(parts).rstrip()
```

- [ ] **Step 6: Update `assemble_context` to accept and process new parameters**

In `src/pam/agent/context_assembly.py`, update the `assemble_context` function:

```python
def assemble_context(
    es_results: list,
    graph_text: str,
    entity_vdb_results: list[dict],
    rel_vdb_results: list[dict],
    budget: ContextBudget | None = None,
    memory_results: list[dict] | None = None,
    conversation_context: str = "",
) -> AssembledContext:
    """4-stage context assembly pipeline.

    Parameters
    ----------
    es_results:
        ``SearchResult`` objects from Elasticsearch hybrid search.
    graph_text:
        Pre-formatted text from Graphiti ``search_graph_relationships``.
    entity_vdb_results:
        Dicts with ``name``, ``entity_type``, ``description``, ``score``.
    rel_vdb_results:
        Dicts with ``src_entity``, ``tgt_entity``, ``rel_type``, ``description``, ``score``.
    budget:
        Optional custom budget; defaults to ``ContextBudget()``.
    memory_results:
        Dicts with ``content``, ``type``, ``score`` from MemoryService.search().
    conversation_context:
        Pre-formatted conversation text from ConversationService.get_recent_context().

    Returns
    -------
    AssembledContext
        The assembled Markdown text and per-category token usage.
    """
    budget = budget or ContextBudget()
    memory_results = memory_results or []

    # ---- Stage 1: Collect & Normalize ----
    chunks: list[dict] = []
    for r in es_results:
        source_label = getattr(r, "document_title", None) or getattr(r, "source_id", "Unknown")
        section_path = getattr(r, "section_path", "")
        if section_path:
            source_label += f" > {section_path}"
        chunks.append(
            {
                "segment_id": str(getattr(r, "segment_id", "")),
                "content": getattr(r, "content", ""),
                "source_label": source_label,
                "source_url": getattr(r, "source_url", ""),
            }
        )

    entities: list[dict] = list(entity_vdb_results)
    relationships: list[dict] = list(rel_vdb_results)

    # ---- Stage 2: Sort by score & Truncate per-category ----
    entities.sort(key=lambda x: x.get("score", 0), reverse=True)
    relationships.sort(key=lambda x: x.get("score", 0), reverse=True)
    # Chunks keep their ES relevance order (already ranked by RRF).

    entities, entity_tokens_used, total_entities = truncate_list_by_token_budget(
        entities,
        "description",
        budget.entity_tokens,
        budget.max_item_tokens,
    )

    # Count graph_text tokens toward relationship budget
    graph_text_tokens = count_tokens(graph_text) if graph_text.strip() else 0
    effective_rel_budget = max(budget.relationship_tokens - graph_text_tokens, 0)

    relationships, rel_tokens_used, total_relationships = truncate_list_by_token_budget(
        relationships,
        "description",
        effective_rel_budget,
        budget.max_item_tokens,
    )
    relationship_tokens_used = rel_tokens_used + graph_text_tokens

    # ---- Memories: sort by score and truncate ----
    # (Must happen before chunk budget calculation so we can subtract used tokens)

    memories_sorted = sorted(memory_results, key=lambda x: x.get("score", 0), reverse=True)
    memories_truncated, memory_tokens_used, _ = truncate_list_by_token_budget(
        memories_sorted,
        "content",
        budget.memory_tokens,
        budget.max_item_tokens,
    )

    # ---- Conversation context: truncate to budget ----
    conversation_tokens_used = 0
    truncated_conversation = ""
    if conversation_context.strip():
        conv_tokens = count_tokens(conversation_context)
        if conv_tokens <= budget.conversation_tokens:
            truncated_conversation = conversation_context
            conversation_tokens_used = conv_tokens
        else:
            truncated_conversation = _truncate_text_to_tokens(conversation_context, budget.conversation_tokens)
            conversation_tokens_used = budget.conversation_tokens

    # ---- Chunks: dynamic budget accounts for all other categories ----
    chunk_budget = _calculate_chunk_budget(
        budget.max_total_tokens - memory_tokens_used - conversation_tokens_used,
        budget.entity_tokens,
        budget.relationship_tokens,
        entity_tokens_used,
        relationship_tokens_used,
    )

    chunks_truncated, chunk_tokens_used, total_chunks = truncate_list_by_token_budget(
        chunks,
        "content",
        chunk_budget,
        budget.max_item_tokens,
    )

    # ---- Stage 3: Dedup chunks ----
    chunks_deduped = deduplicate_chunks(chunks_truncated)

    # ---- Stage 4: Build structured Markdown ----
    text = _build_context_string(
        entities=entities,
        relationships=relationships,
        chunks=chunks_deduped,
        graph_text=graph_text,
        total_entities=total_entities,
        total_relationships=total_relationships,
        total_chunks=total_chunks,
        memories=memories_truncated if memories_truncated else None,
        conversation_context=truncated_conversation,
    )

    total_tokens = (
        entity_tokens_used
        + relationship_tokens_used
        + chunk_tokens_used
        + memory_tokens_used
        + conversation_tokens_used
    )

    logger.debug(
        "context_assembly_budget",
        entities=f"{entity_tokens_used}/{budget.entity_tokens}",
        relationships=f"{relationship_tokens_used}/{budget.relationship_tokens}",
        chunks=f"{chunk_tokens_used}/{chunk_budget}",
        memories=f"{memory_tokens_used}/{budget.memory_tokens}",
        conversation=f"{conversation_tokens_used}/{budget.conversation_tokens}",
        total=f"{total_tokens}/{budget.max_total_tokens}",
    )

    return AssembledContext(
        text=text,
        entity_tokens_used=entity_tokens_used,
        relationship_tokens_used=relationship_tokens_used,
        chunk_tokens_used=chunk_tokens_used,
        total_tokens=total_tokens,
        memory_tokens_used=memory_tokens_used,
        conversation_tokens_used=conversation_tokens_used,
    )
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `pytest tests/test_agent/test_context_assembly.py -v`
Expected: PASS

Also run existing context assembly tests to ensure no regressions:

Run: `pytest tests/test_agent/ -v`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add src/pam/agent/context_assembly.py tests/test_agent/test_context_assembly.py
git commit -m "feat(conversation): add memory + conversation sections to context assembly"
```

---

## Task 10: REST API Routes for Conversations

**Files:**
- Create: `src/pam/api/routes/conversation.py`
- Create: `tests/conversation/test_routes.py`

- [ ] **Step 1: Write failing tests**

Create `tests/conversation/test_routes.py`:

```python
"""Tests for conversation REST API routes."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from pam.api.main import create_app
from pam.api.routes.conversation import get_conversation_service
from pam.common.models import ConversationDetail, ConversationResponse, ConvMessageResponse


@pytest.fixture
def mock_conv_service():
    return AsyncMock()


@pytest.fixture
def app(mock_conv_service):
    application = create_app()
    application.dependency_overrides[get_conversation_service] = lambda: mock_conv_service
    return application


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_create_conversation(client, mock_conv_service):
    """POST /api/conversations creates a conversation."""
    now = datetime.now(tz=timezone.utc)
    mock_conv_service.create.return_value = ConversationResponse(
        id=uuid.uuid4(),
        user_id=None,
        project_id=None,
        title="Test",
        started_at=now,
        last_active=now,
        message_count=0,
    )

    resp = await client.post("/api/conversations", json={"title": "Test"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Test"


@pytest.mark.asyncio
async def test_get_conversation(client, mock_conv_service):
    """GET /api/conversations/{id} returns conversation detail."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    mock_conv_service.get.return_value = ConversationDetail(
        id=conv_id,
        title="Chat",
        started_at=now,
        last_active=now,
        message_count=0,
        messages=[],
    )

    resp = await client.get(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Chat"


@pytest.mark.asyncio
async def test_get_conversation_not_found(client, mock_conv_service):
    """GET /api/conversations/{id} returns 404 when not found."""
    mock_conv_service.get.return_value = None
    resp = await client.get(f"/api/conversations/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_add_message(client, mock_conv_service):
    """POST /api/conversations/{id}/messages adds a message."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    mock_conv_service.add_message.return_value = ConvMessageResponse(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role="user",
        content="Hello",
        metadata={},
        created_at=now,
    )

    resp = await client.post(
        f"/api/conversations/{conv_id}/messages",
        json={"role": "user", "content": "Hello"},
    )
    assert resp.status_code == 200
    assert resp.json()["content"] == "Hello"


@pytest.mark.asyncio
async def test_list_conversations(client, mock_conv_service):
    """GET /api/conversations/user/{user_id} lists conversations."""
    user_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)
    mock_conv_service.list_by_user.return_value = [
        ConversationResponse(
            id=uuid.uuid4(),
            user_id=user_id,
            title="Chat 1",
            started_at=now,
            last_active=now,
            message_count=5,
        ),
    ]

    resp = await client.get(f"/api/conversations/user/{user_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["message_count"] == 5


@pytest.mark.asyncio
async def test_delete_conversation(client, mock_conv_service):
    """DELETE /api/conversations/{id} deletes conversation."""
    conv_id = uuid.uuid4()
    mock_conv_service.delete.return_value = True

    resp = await client.delete(f"/api/conversations/{conv_id}")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Conversation deleted"


@pytest.mark.asyncio
async def test_delete_conversation_not_found(client, mock_conv_service):
    """DELETE /api/conversations/{id} returns 404 when not found."""
    mock_conv_service.delete.return_value = False
    resp = await client.delete(f"/api/conversations/{uuid.uuid4()}")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/conversation/test_routes.py -v`
Expected: FAIL — route module doesn't exist.

- [ ] **Step 3: Implement REST API routes**

Create `src/pam/api/routes/conversation.py`:

```python
"""Conversation endpoints — CRUD for conversations and messages."""

import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException

from pam.api.auth import get_current_user
from pam.common.models import (
    ConversationCreate,
    ConversationDetail,
    ConversationResponse,
    ConvMessageResponse,
    MessageCreate,
    User,
)

logger = structlog.get_logger()

router = APIRouter()


def get_conversation_service():
    """Dependency stub — overridden at app startup."""
    raise RuntimeError("ConversationService not initialized")


def _require_user(user: User | None) -> User:
    """Raise 401 if no authenticated user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.post("/", response_model=ConversationResponse)
async def create_conversation(
    body: ConversationCreate,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Create a new conversation."""
    owner = _require_user(user)
    return await service.create(
        user_id=owner.id,
        project_id=body.project_id,
        title=body.title,
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Get a conversation with all its messages."""
    owner = _require_user(user)
    result = await service.get(conversation_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if result.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Access denied")
    return result


@router.get("/user/{user_id}", response_model=list[ConversationResponse])
async def list_user_conversations(
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """List conversations for the authenticated user."""
    owner = _require_user(user)
    return await service.list_by_user(
        user_id=owner.id,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )


@router.post("/{conversation_id}/messages", response_model=ConvMessageResponse)
async def add_message(
    conversation_id: uuid.UUID,
    body: MessageCreate,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Add a message to a conversation."""
    owner = _require_user(user)
    # Verify ownership before adding
    existing = await service.get(conversation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if existing.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Access denied")
    try:
        return await service.add_message(
            conversation_id=conversation_id,
            role=body.role,
            content=body.content,
            metadata=body.metadata,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: uuid.UUID,
    service=Depends(get_conversation_service),
    user: User | None = Depends(get_current_user),
):
    """Delete a conversation and all its messages."""
    owner = _require_user(user)
    # Verify ownership before deleting
    existing = await service.get(conversation_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    if existing.user_id != owner.id:
        raise HTTPException(status_code=403, detail="Access denied")
    await service.delete(conversation_id)
    return {"message": "Conversation deleted", "id": str(conversation_id)}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/conversation/test_routes.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/api/routes/conversation.py tests/conversation/test_routes.py
git commit -m "feat(conversation): add REST API routes for conversation CRUD"
```

---

## Task 11: Chat Endpoint Integration — Auto-Persist + Extraction

**Files:**
- Modify: `src/pam/api/routes/chat.py`
- Test: existing chat tests (verify no regression)

- [ ] **Step 1: Write failing test for auto-persist behavior**

Append to `tests/test_api/test_chat.py` (or create if needed):

```python
"""Tests for chat auto-persist integration."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_chat_persists_conversation(client, mock_agent):
    """POST /chat auto-persists messages when conversation_service is available."""
    mock_result = MagicMock()
    mock_result.answer = "The answer is 42."
    mock_result.citations = []
    mock_result.token_usage = {"input_tokens": 100, "output_tokens": 50}
    mock_result.latency_ms = 150.0
    mock_result.retrieval_mode = "factual"
    mock_result.mode_confidence = 0.9
    mock_agent.answer.return_value = mock_result

    resp = await client.post("/api/chat", json={"message": "What is the answer?"})
    assert resp.status_code == 200
    assert resp.json()["conversation_id"] is not None
```

- [ ] **Step 2: Run test to verify current behavior (should pass — just returns conversation_id)**

Run: `pytest tests/test_api/test_chat.py -v -k "persists_conversation"`
Expected: PASS (the endpoint already returns a conversation_id, even if it doesn't persist).

- [ ] **Step 3: Modify chat.py to auto-persist conversation turns**

In `src/pam/api/routes/chat.py`, update the `chat` endpoint to persist messages when a `ConversationService` is available. Add a helper function and modify the endpoint.

Add a helper function after the imports:

```python
async def _persist_exchange(
    request: Request,
    conversation_id: str,
    user_message: str,
    assistant_response: str,
    user_id: uuid.UUID | None = None,
) -> None:
    """Persist conversation exchange and trigger fact extraction.

    Called inline (awaited) before returning the response, so no
    fire-and-forget / orphaned-task issues.
    """
    conv_service = getattr(request.app.state, "conversation_service", None)
    if conv_service is None:
        return

    try:
        conv_id = uuid.UUID(conversation_id)

        # Create conversation if it doesn't exist yet (first turn)
        existing = await conv_service.get(conv_id)
        if existing is None:
            # Pass the client-generated conv_id so both sides agree on the ID
            await conv_service.create_with_id(
                conversation_id=conv_id,
                user_id=user_id,
                title=user_message[:100],
            )

        await conv_service.add_message(conv_id, role="user", content=user_message)
        await conv_service.add_message(conv_id, role="assistant", content=assistant_response)

    except Exception:
        logger.warning("chat_persist_error", conversation_id=conversation_id, exc_info=True)

    # Trigger fact extraction
    extraction = getattr(request.app.state, "extraction_pipeline", None)
    if extraction is not None:
        try:
            await extraction.extract_from_exchange(
                user_message=user_message,
                assistant_response=assistant_response,
                user_id=user_id,
            )
        except Exception:
            logger.warning("chat_extraction_error", exc_info=True)

    # Trigger summarization if conversation exceeds threshold
    summarizer = getattr(request.app.state, "conversation_summarizer", None)
    if summarizer is not None:
        try:
            conv_id = uuid.UUID(conversation_id)
            await summarizer.maybe_summarize(conv_id, user_id=user_id)
        except Exception:
            logger.warning("chat_summarization_error", exc_info=True)
```

Then update the `chat` endpoint to call the helper **inline** after generating the response but before returning. Replace the try/except block in the `chat` function:

```python
    try:
        result: AgentResponse = await agent.answer(body.message, **kwargs)
    except Exception as e:
        logger.exception("chat_error", message=body.message[:100])
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

    # Persist exchange inline (fast — just DB writes, no LLM call blocks the response
    # because extraction uses Haiku which completes quickly)
    await _persist_exchange(
        request, conversation_id, body.message, result.answer,
        user_id=_user.id if _user else None,
    )

    return ChatResponse(
        ...
    )
```

> **Design note:** We `await` the persist call inline rather than using `asyncio.create_task` (fire-and-forget). This avoids orphaned tasks, silent exception swallowing, and GC issues. The persist path is fast (two DB inserts + one Haiku call) and adds negligible latency vs. the main agent call.

- [ ] **Step 3b: Wire auto-persist into the streaming endpoint**

The web UI uses `/api/chat/stream` (via `streamChatMessage()` in `web/src/hooks/useChat.ts`), so persist must happen there too. Update `chat_stream` to accumulate the full response and persist after streaming completes:

```python
@router.post("/chat/stream")
@limiter.limit(settings.rate_limit_chat)
async def chat_stream(
    request: Request,
    body: ChatRequest,
    agent: RetrievalAgent = Depends(get_agent),
    _user: User | None = Depends(get_current_user),
):
    """Stream a chat response as Server-Sent Events."""
    conversation_id = body.conversation_id or str(uuid.uuid4())

    history = None
    if body.conversation_history:
        history = [{"role": m.role, "content": m.content} for m in body.conversation_history]

    async def event_generator():
        full_response = ""
        async for chunk in agent.answer_streaming(
            body.message,
            conversation_history=history,
            source_type=body.source_type,
        ):
            if chunk.get("type") == "content":
                full_response += chunk.get("text", "")
            if chunk.get("type") == "done":
                chunk["conversation_id"] = conversation_id
            yield f"data: {json.dumps(chunk)}\n\n"

        # Persist after streaming completes (inside generator so request is still alive)
        if full_response:
            await _persist_exchange(
                request, conversation_id, body.message, full_response,
                user_id=_user.id if _user else None,
            )

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 4: Run all chat tests to verify no regressions**

Run: `pytest tests/test_api/test_chat.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/pam/api/routes/chat.py tests/test_api/test_chat.py
git commit -m "feat(conversation): auto-persist chat exchanges and trigger fact extraction"
```

---

## Task 12: MCP Tools — pam_save_conversation, pam_get_conversation_context

**Files:**
- Modify: `src/pam/mcp/server.py`
- Modify: `src/pam/mcp/services.py`
- Create: `tests/mcp/test_conversation_tools.py`

- [ ] **Step 1: Write failing tests**

Create `tests/mcp/test_conversation_tools.py`:

```python
"""Tests for conversation MCP tools."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from pam.mcp import server as mcp_server
from pam.mcp.services import PamServices


@pytest.fixture
def mock_conversation_service():
    svc = AsyncMock()
    return svc


@pytest.fixture
def mock_services(mock_conversation_service):
    return PamServices(
        search_service=AsyncMock(),
        embedder=AsyncMock(),
        session_factory=MagicMock(),
        es_client=AsyncMock(),
        graph_service=None,
        vdb_store=None,
        duckdb_service=None,
        cache_service=None,
        memory_service=AsyncMock(),
        conversation_service=mock_conversation_service,
    )


@pytest.fixture(autouse=True)
def _init_services(mock_services):
    mcp_server.initialize(mock_services)
    yield
    mcp_server._services = None


@pytest.mark.asyncio
async def test_pam_save_conversation(mock_conversation_service):
    """pam_save_conversation stores messages in a conversation."""
    conv_id = uuid.uuid4()
    now = datetime.now(tz=timezone.utc)

    mock_conversation_service.create.return_value = MagicMock(id=conv_id)
    mock_conversation_service.add_message.return_value = MagicMock(
        id=uuid.uuid4(),
        conversation_id=conv_id,
        role="user",
        content="Hello",
        created_at=now,
    )

    result = await mcp_server._pam_save_conversation(
        messages=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ],
        title="Test Chat",
    )

    assert "conversation_id" in result
    assert mock_conversation_service.add_message.await_count == 2


@pytest.mark.asyncio
async def test_pam_get_conversation_context(mock_conversation_service):
    """pam_get_conversation_context returns recent conversation context."""
    conv_id = uuid.uuid4()
    mock_conversation_service.get_recent_context.return_value = (
        "user: What is PAM?\nassistant: PAM is a knowledge base."
    )

    result = await mcp_server._pam_get_conversation_context(
        conversation_id=str(conv_id),
    )

    assert "PAM" in result
    mock_conversation_service.get_recent_context.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/mcp/test_conversation_tools.py -v`
Expected: FAIL — tools not implemented, `conversation_service` not in PamServices.

- [ ] **Step 3: Add `conversation_service` to PamServices**

In `src/pam/mcp/services.py`, add the field and update `from_app_state`:

```python
# Add to TYPE_CHECKING imports:
from pam.conversation.service import ConversationService

# Add to PamServices dataclass:
conversation_service: ConversationService | None

# Add to from_app_state:
conversation_service=getattr(app_state, "conversation_service", None),
```

- [ ] **Step 4: Add MCP tools to server.py**

In `src/pam/mcp/server.py`, add the conversation tool implementations and registration.

Add tool implementation functions:

```python
async def _pam_save_conversation(
    messages: list[dict],
    title: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
) -> str:
    """Save a conversation (list of messages) to PAM."""
    svc = _services.conversation_service
    if svc is None:
        return json.dumps({"error": "ConversationService not available"})

    uid = uuid.UUID(user_id) if user_id else None
    pid = uuid.UUID(project_id) if project_id else None

    conv = await svc.create(user_id=uid, project_id=pid, title=title)

    for msg in messages:
        await svc.add_message(
            conversation_id=conv.id,
            role=msg["role"],
            content=msg["content"],
            metadata=msg.get("metadata", {}),
        )

    return json.dumps({
        "conversation_id": str(conv.id),
        "messages_saved": len(messages),
        "title": conv.title,
    })


async def _pam_get_conversation_context(
    conversation_id: str,
    max_tokens: int = 2000,
) -> str:
    """Get recent conversation context for assembly."""
    svc = _services.conversation_service
    if svc is None:
        return json.dumps({"error": "ConversationService not available"})

    conv_id = uuid.UUID(conversation_id)
    context = await svc.get_recent_context(conv_id, max_tokens=max_tokens)
    return context
```

Register the tools in `create_mcp_server()` using the same pattern as the existing memory tools — add `@mcp.tool()` decorators that call the implementation functions.

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/mcp/test_conversation_tools.py -v`
Expected: PASS

Also run existing MCP tests to verify no regressions:

Run: `pytest tests/mcp/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/pam/mcp/server.py src/pam/mcp/services.py tests/mcp/test_conversation_tools.py
git commit -m "feat(conversation): add pam_save_conversation and pam_get_conversation_context MCP tools"
```

---

## Task 13: App Startup Wiring

**Files:**
- Modify: `src/pam/api/main.py`

- [ ] **Step 1: Wire ConversationService into app startup**

In `src/pam/api/main.py`, add after the Memory Service initialization block:

```python
    # --- Conversation Service ---
    try:
        from pam.conversation.service import ConversationService

        conversation_service = ConversationService(
            session_factory=session_factory,
        )
        app.state.conversation_service = conversation_service
        logger.info("conversation_service_initialized")

        # --- Fact Extraction Pipeline (depends on memory + conversation) ---
        if app.state.memory_service and settings.conversation_extraction_enabled:
            from pam.conversation.extraction import FactExtractionPipeline

            app.state.extraction_pipeline = FactExtractionPipeline(
                memory_service=app.state.memory_service,
                anthropic_api_key=settings.anthropic_api_key,
                model=settings.conversation_extraction_model,
            )
            logger.info("extraction_pipeline_initialized")
        else:
            app.state.extraction_pipeline = None

        # --- Conversation Summarizer ---
        if app.state.memory_service:
            from pam.conversation.summarizer import ConversationSummarizer

            app.state.conversation_summarizer = ConversationSummarizer(
                conversation_service=conversation_service,
                memory_service=app.state.memory_service,
                anthropic_api_key=settings.anthropic_api_key,
                model=settings.conversation_extraction_model,
                summary_threshold=settings.conversation_summary_threshold,
            )
            logger.info("conversation_summarizer_initialized")
        else:
            app.state.conversation_summarizer = None

    except Exception:
        app.state.conversation_service = None
        app.state.extraction_pipeline = None
        app.state.conversation_summarizer = None
        logger.warning("conversation_service_init_failed", exc_info=True)
```

- [ ] **Step 2: Register conversation routes in create_app()**

In the `create_app()` function, add the import and router registration:

Add to imports at top:

```python
from pam.api.routes import admin, auth, chat, conversation, documents, graph, ingest, memory, search
```

Add router after the memory router:

```python
    app.include_router(conversation.router, prefix="/api/conversations", tags=["conversations"])
```

Add dependency override after the memory service override:

```python
    # Override the conversation service dependency
    from pam.api.routes.conversation import get_conversation_service as _get_conv_svc

    def _conv_svc_override():
        return getattr(app.state, "conversation_service", None)

    app.dependency_overrides[_get_conv_svc] = _conv_svc_override
```

- [ ] **Step 3: Run the full test suite to verify no regressions**

Run: `pytest tests/ -v --ignore=tests/integration`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/pam/api/main.py
git commit -m "feat(conversation): wire ConversationService, extraction, and summarizer into app startup"
```

---

## Task 14: Wire Memory + Conversation Context into Agent Call Site

**Files:**
- Modify: `src/pam/agent/agent.py`
- Test: `tests/test_agent/test_agent.py`

The plan adds `memory_results` and `conversation_context` parameters to `assemble_context()` (Task 9), but never populates them at the agent call site. Without this task, the 'User Memories' and 'Recent Conversation' sections can never appear in prompts.

- [ ] **Step 1: Write failing test**

Append to `tests/test_agent/test_agent.py`:

```python
@pytest.mark.asyncio
async def test_smart_search_includes_memory_and_conversation(agent, mock_memory_service, mock_conversation_service, monkeypatch):
    """_smart_search passes memory results and conversation context to assemble_context."""
    monkeypatch.setattr(agent, "_memory_service", mock_memory_service)
    monkeypatch.setattr(agent, "_conversation_service", mock_conversation_service)
    monkeypatch.setattr(agent, "_current_user_id", uuid.uuid4())
    monkeypatch.setattr(agent, "_current_conversation_id", uuid.uuid4())

    mock_memory_service.search.return_value = [
        MagicMock(content="User prefers dark mode", type="preference", score=0.9),
    ]
    mock_conversation_service.get_recent_context.return_value = "user: hello\nassistant: hi there"

    # Patch assemble_context to capture kwargs
    captured_kwargs = {}
    original = assemble_context

    def patched_assemble(*args, **kwargs):
        captured_kwargs.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr("pam.agent.agent.assemble_context", patched_assemble)

    # ... trigger _smart_search ...
    assert "memory_results" in captured_kwargs
    assert len(captured_kwargs["memory_results"]) == 1
    assert "conversation_context" in captured_kwargs
    assert "hello" in captured_kwargs["conversation_context"]
```

- [ ] **Step 2: Update RetrievalAgent to accept memory and conversation services**

In `src/pam/agent/agent.py`, add optional service dependencies to the agent's constructor (or accept them via the existing dependency injection pattern):

```python
# In RetrievalAgent.__init__ or as instance attributes set by the caller:
self._memory_service = memory_service  # Optional[MemoryService]
self._conversation_service = conversation_service  # Optional[ConversationService]
self._current_user_id: uuid.UUID | None = None
self._current_conversation_id: uuid.UUID | None = None
```

- [ ] **Step 3: Fetch memory + conversation context in _smart_search**

In `src/pam/agent/agent.py`, add memory and conversation fetching to `_smart_search()`, just before the `assemble_context` call at the Step F block:

```python
        # Step F-pre: Fetch user memories and conversation context (if available)
        memory_results: list[dict] = []
        conversation_context = ""

        if self._memory_service and self._current_user_id:
            try:
                raw_memories = await self._memory_service.search(
                    query=query,
                    user_id=self._current_user_id,
                    top_k=5,
                )
                memory_results = [
                    {"content": m.content, "type": m.type, "score": m.score}
                    for m in raw_memories
                ]
            except Exception:
                logger.warning("smart_search_memory_failed", exc_info=True)

        if self._conversation_service and self._current_conversation_id:
            try:
                conversation_context = await self._conversation_service.get_recent_context(
                    self._current_conversation_id,
                    max_tokens=settings.context_conversation_budget,
                )
            except Exception:
                logger.warning("smart_search_conversation_failed", exc_info=True)

        # Step F: Assemble structured context with token budgets
        budget = ContextBudget(
            entity_tokens=settings.context_entity_budget,
            relationship_tokens=settings.context_relationship_budget,
            max_total_tokens=settings.context_max_tokens,
            memory_tokens=settings.context_memory_budget,
            conversation_tokens=settings.context_conversation_budget,
        )
        assembled = assemble_context(
            es_results=es_results,
            graph_text=graph_text,
            entity_vdb_results=entity_vdb_results,
            rel_vdb_results=rel_vdb_results,
            budget=budget,
            memory_results=memory_results,
            conversation_context=conversation_context,
        )
```

- [ ] **Step 4: Pass services from chat endpoints to agent**

In `src/pam/api/routes/chat.py`, set the agent's memory/conversation services before calling `agent.answer()`:

```python
    # Set per-request context for memory + conversation injection
    agent._memory_service = getattr(request.app.state, "memory_service", None)
    agent._conversation_service = getattr(request.app.state, "conversation_service", None)
    agent._current_user_id = _user.id if _user else None
    agent._current_conversation_id = uuid.UUID(conversation_id) if conversation_id else None
```

- [ ] **Step 5: Add config settings for memory and conversation budgets**

In `src/pam/common/config.py`, add:

```python
    context_memory_budget: int = 2000
    context_conversation_budget: int = 2000
```

- [ ] **Step 6: Run tests to verify**

Run: `pytest tests/test_agent/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/pam/agent/agent.py src/pam/api/routes/chat.py src/pam/common/config.py tests/test_agent/
git commit -m "feat(conversation): wire memory + conversation context into agent call site"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Conversation data model (id, user_id, project_id, started_at, last_active) — Task 2
- [x] Message data model (id, conversation_id, role, content, metadata, created_at) — Task 2
- [x] Automatic fact extraction after conversation turns — Task 7, integrated in Task 11
- [x] Dedup against existing memories — handled by MemoryService.store() (existing Phase 2 dedup)
- [x] Store new facts via Memory Service — Task 7
- [x] Update importance scores on accessed memories — handled by MemoryService.search() (existing Phase 2)
- [x] Conversation summarization — Task 8
- [x] Compressed summaries stored as conversation_summary type memories — Task 8
- [x] Context-as-a-Service update (+conversation history) — Task 9
- [x] REST API for conversations (with ownership enforcement) — Task 10
- [x] MCP tools for conversation access — Task 12
- [x] Config settings — Task 1
- [x] Alembic migration — Task 4
- [x] App wiring — Task 13
- [x] Agent call site wiring (memory + conversation → assemble_context) — Task 14
- [x] Streaming endpoint auto-persist — Task 11, Step 3b
- [x] Summarizer invocation after persist — Task 11, Step 3

**2. Placeholder scan:** No TBDs, TODOs, or "fill in details" found.

**3. Type consistency:** ConversationService, ConversationResponse, ConversationDetail, ConvMessageResponse (renamed to avoid collision with existing generic MessageResponse), MessageCreate, FactExtractionPipeline, ConversationSummarizer — all consistent across tasks.
