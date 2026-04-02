"""Conversation service — CRUD for conversations and messages."""

from __future__ import annotations

import uuid as uuid_mod
from datetime import UTC, datetime
from typing import TYPE_CHECKING, ClassVar

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

    _VALID_ROLES: ClassVar[set[str]] = {"user", "assistant", "system"}

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
            now = datetime.now(tz=UTC)
            conv = Conversation(
                id=uuid_mod.uuid4(),
                user_id=user_id,
                project_id=project_id,
                title=title,
                started_at=now,
                last_active=now,
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
            now = datetime.now(tz=UTC)
            conv = Conversation(
                id=conversation_id,
                user_id=user_id,
                project_id=project_id,
                title=title,
                started_at=now,
                last_active=now,
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

            now = datetime.now(tz=UTC)
            msg = Message(
                id=uuid_mod.uuid4(),
                conversation_id=conversation_id,
                role=role,
                content=content,
                metadata_=metadata or {},
                created_at=now,
            )
            session.add(msg)
            conv.last_active = now
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
