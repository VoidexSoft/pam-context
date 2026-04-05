"""Chat endpoint — conversational Q&A with the knowledge base."""

import json
import uuid
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from pam.agent.agent import AgentResponse, RetrievalAgent
from pam.api.auth import get_current_user
from pam.api.deps import get_agent
from pam.api.rate_limit import limiter
from pam.common.config import settings
from pam.common.models import User

logger = structlog.get_logger()

router = APIRouter()


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    """Return a UUID if value is a valid UUID string, otherwise None."""
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


async def _persist_exchange(
    request: Request,
    conversation_id: str,
    user_message: str,
    assistant_response: str,
    user_id: uuid.UUID | None = None,
) -> None:
    """Persist conversation exchange and trigger fact extraction.

    Called inline (awaited) before returning the response, so no
    fire-and-forget / orphaned-task issues.  Extraction and summarization
    only run when persistence succeeds to avoid orphaned memories.
    """
    conv_service = getattr(request.app.state, "conversation_service", None)
    if conv_service is None:
        return

    conv_id = _parse_uuid(conversation_id)
    if conv_id is None:
        logger.warning("chat_persist_invalid_uuid", conversation_id=conversation_id)
        return

    # Track the conversation detail so we can extract project_id later.
    persisted_detail = None
    try:
        # Create conversation if it doesn't exist yet (first turn).
        # Use try/except to handle race conditions from concurrent requests.
        existing = await conv_service.get(conv_id)
        if existing is None:
            try:
                await conv_service.create_with_id(
                    conversation_id=conv_id,
                    user_id=user_id,
                    title=user_message[:100],
                )
            except Exception:
                # Race: another request already created it — re-fetch to confirm
                existing = await conv_service.get(conv_id)
                if existing is None:
                    raise

        await conv_service.add_message(conv_id, role="user", content=user_message)
        await conv_service.add_message(conv_id, role="assistant", content=assistant_response)
        # Always re-fetch to get the latest detail (fresh message_count +
        # project_id). Relying on the pre-add `existing` snapshot left
        # message_count stale, so the summarizer's should_summarize() could
        # miss the threshold on the exact turn it was crossed.
        persisted_detail = await conv_service.get(conv_id)

    except Exception:
        logger.warning("chat_persist_error", conversation_id=conversation_id, exc_info=True)
        return  # Skip extraction/summarization when persistence fails

    project_id = getattr(persisted_detail, "project_id", None) if persisted_detail else None

    # Trigger fact extraction
    extraction = getattr(request.app.state, "extraction_pipeline", None)
    if extraction is not None:
        try:
            await extraction.extract_from_exchange(
                user_message=user_message,
                assistant_response=assistant_response,
                user_id=user_id,
                project_id=project_id,
            )
        except Exception:
            logger.warning("chat_extraction_error", exc_info=True)

    # Trigger summarization check
    summarizer = getattr(request.app.state, "conversation_summarizer", None)
    if summarizer is not None:
        try:
            conv_detail = await summarizer.should_summarize(conv_id)
            if conv_detail is not None:
                await summarizer.summarize(conv_id, detail=conv_detail)
        except Exception:
            logger.warning("chat_summarization_error", exc_info=True)


class ConversationMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    conversation_history: list[ConversationMessage] | None = None
    source_type: str | None = None


class ChatResponse(BaseModel):
    response: str
    citations: list[dict]
    conversation_id: str | None
    token_usage: dict
    latency_ms: float
    retrieval_mode: str | None = None
    mode_confidence: float | None = None


class ChatDebugResponse(BaseModel):
    response: str
    citations: list[dict]
    conversation_id: str | None
    token_usage: dict
    latency_ms: float
    retrieval_mode: str | None = None
    mode_confidence: float | None = None
    retrieved_context: list[str] = []


@router.post("/chat/debug", response_model=ChatDebugResponse)
@limiter.limit(settings.rate_limit_chat)
async def chat_debug(
    request: Request,
    body: ChatRequest,
    agent: RetrievalAgent = Depends(get_agent),
    _user: User | None = Depends(get_current_user),
):
    """Chat endpoint that also returns retrieved context for evaluation."""
    conversation_id = body.conversation_id or str(uuid.uuid4())

    kwargs: dict = {}
    if body.conversation_history:
        kwargs["conversation_history"] = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    if body.source_type:
        kwargs["source_type"] = body.source_type

    # Set per-request context for memory + conversation injection
    agent._memory_service = getattr(request.app.state, "memory_service", None)
    agent._conversation_service = getattr(request.app.state, "conversation_service", None)
    agent._current_user_id = _user.id if _user else None
    agent._current_conversation_id = _parse_uuid(conversation_id)

    try:
        result: AgentResponse = await agent.answer(body.message, **kwargs)
    except Exception as e:
        logger.exception("chat_debug_error", message=body.message[:100])
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

    # Persist exchange inline (same as chat/chat_stream)
    await _persist_exchange(
        request,
        conversation_id,
        body.message,
        result.answer,
        user_id=_user.id if _user else None,
    )

    return ChatDebugResponse(
        response=result.answer,
        citations=[
            {
                "document_title": c.document_title,
                "section_path": c.section_path,
                "source_url": c.source_url,
                "segment_id": c.segment_id,
            }
            for c in result.citations
        ],
        conversation_id=conversation_id,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
        retrieval_mode=result.retrieval_mode,
        mode_confidence=result.mode_confidence,
        retrieved_context=result.retrieved_context,
    )


@router.post("/chat", response_model=ChatResponse)
@limiter.limit(settings.rate_limit_chat)
async def chat(
    request: Request,
    body: ChatRequest,
    agent: RetrievalAgent = Depends(get_agent),
    _user: User | None = Depends(get_current_user),
):
    """Send a message and get an AI-powered answer with citations."""
    conversation_id = body.conversation_id or str(uuid.uuid4())

    kwargs: dict = {}
    if body.conversation_history:
        kwargs["conversation_history"] = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    if body.source_type:
        kwargs["source_type"] = body.source_type

    # Set per-request context for memory + conversation injection
    agent._memory_service = getattr(request.app.state, "memory_service", None)
    agent._conversation_service = getattr(request.app.state, "conversation_service", None)
    agent._current_user_id = _user.id if _user else None
    agent._current_conversation_id = _parse_uuid(conversation_id)

    try:
        result: AgentResponse = await agent.answer(body.message, **kwargs)
    except Exception as e:
        logger.exception("chat_error", message=body.message[:100])
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

    # Persist exchange inline
    await _persist_exchange(
        request,
        conversation_id,
        body.message,
        result.answer,
        user_id=_user.id if _user else None,
    )

    return ChatResponse(
        response=result.answer,
        citations=[
            {
                "document_title": c.document_title,
                "section_path": c.section_path,
                "source_url": c.source_url,
                "segment_id": c.segment_id,
            }
            for c in result.citations
        ],
        conversation_id=conversation_id,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
        retrieval_mode=result.retrieval_mode,
        mode_confidence=result.mode_confidence,
    )


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

    # Set per-request context for memory + conversation injection
    agent._memory_service = getattr(request.app.state, "memory_service", None)
    agent._conversation_service = getattr(request.app.state, "conversation_service", None)
    agent._current_user_id = _user.id if _user else None
    agent._current_conversation_id = _parse_uuid(conversation_id)

    history = None
    if body.conversation_history:
        history = [{"role": m.role, "content": m.content} for m in body.conversation_history]

    async def event_generator():
        full_response = ""
        try:
            async for chunk in agent.answer_streaming(
                body.message,
                conversation_history=history,
                source_type=body.source_type,
            ):
                if chunk.get("type") == "token":
                    full_response += chunk.get("content", "")
                if chunk.get("type") == "done":
                    chunk["conversation_id"] = conversation_id
                yield f"data: {json.dumps(chunk)}\n\n"
        finally:
            # Persist after streaming completes (or on client disconnect)
            if full_response:
                await _persist_exchange(
                    request,
                    conversation_id,
                    body.message,
                    full_response,
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
