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

    try:
        result: AgentResponse = await agent.answer(body.message, **kwargs)
    except Exception as e:
        logger.exception("chat_debug_error", message=body.message[:100])
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

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

    try:
        result: AgentResponse = await agent.answer(body.message, **kwargs)
    except Exception as e:
        logger.exception("chat_error", message=body.message[:100])
        raise HTTPException(status_code=500, detail="An internal error occurred") from e

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

    history = None
    if body.conversation_history:
        history = [{"role": m.role, "content": m.content} for m in body.conversation_history]

    async def event_generator():
        async for chunk in agent.answer_streaming(
            body.message,
            conversation_history=history,
            source_type=body.source_type,
        ):
            if chunk.get("type") == "done":
                chunk["conversation_id"] = conversation_id
            yield f"data: {json.dumps(chunk)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
