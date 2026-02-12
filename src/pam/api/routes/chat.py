"""Chat endpoint — conversational Q&A with the knowledge base."""

import json

from pydantic import BaseModel
from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from pam.agent.agent import AgentResponse, RetrievalAgent
from pam.api.deps import get_agent

router = APIRouter()


class ConversationMessage(BaseModel):
    role: str
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


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    agent: RetrievalAgent = Depends(get_agent),
):
    """Send a message and get an AI-powered answer with citations."""
    kwargs: dict = {}
    if request.conversation_history:
        kwargs["conversation_history"] = [
            {"role": m.role, "content": m.content} for m in request.conversation_history
        ]
    if request.source_type:
        kwargs["source_type"] = request.source_type

    result: AgentResponse = await agent.answer(request.message, **kwargs)

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
        conversation_id=request.conversation_id,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
    )


@router.post("/chat/stream")
async def chat_stream(
    request: ChatRequest,
    agent: RetrievalAgent = Depends(get_agent),
):
    """Stream a chat response as Server-Sent Events."""
    history = None
    if request.conversation_history:
        history = [{"role": m.role, "content": m.content} for m in request.conversation_history]

    async def event_generator():
        async for chunk in agent.answer_streaming(request.message, conversation_history=history, source_type=request.source_type):
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
