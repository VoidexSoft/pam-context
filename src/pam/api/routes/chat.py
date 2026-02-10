"""Chat endpoint — conversational Q&A with the knowledge base."""

from pydantic import BaseModel
from fastapi import APIRouter, Depends

from pam.agent.agent import AgentResponse, RetrievalAgent
from pam.api.deps import get_agent

router = APIRouter()


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None


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
    result: AgentResponse = await agent.answer(request.message)

    return ChatResponse(
        response=result.answer,
        citations=[
            {
                "document_title": c.document_title,
                "section_path": c.section_path,
                "source_url": c.source_url,
            }
            for c in result.citations
        ],
        conversation_id=request.conversation_id,
        token_usage=result.token_usage,
        latency_ms=result.latency_ms,
    )
