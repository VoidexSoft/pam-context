"""Search endpoint — direct knowledge search without agent."""

from fastapi import APIRouter, Depends

from pam.api.auth import get_current_user
from pam.api.deps import get_embedder, get_search_service
from pam.common.models import User
from pam.ingestion.embedders.openai_embedder import OpenAIEmbedder
from pam.retrieval.search_protocol import SearchService
from pam.retrieval.types import SearchQuery, SearchResult

router = APIRouter()


@router.post("/search", response_model=list[SearchResult])
async def search_knowledge(
    query: SearchQuery,
    search_service: SearchService = Depends(get_search_service),
    embedder: OpenAIEmbedder = Depends(get_embedder),
    _user: User | None = Depends(get_current_user),
):
    """Search the knowledge base directly (no agent reasoning)."""
    query_embeddings = await embedder.embed_texts([query.query])
    return await search_service.search_from_query(query, query_embeddings[0])
