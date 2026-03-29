"""Retrieval agent using a simple tool-use loop with the Anthropic SDK."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

import structlog
from anthropic import AsyncAnthropic

from pam.agent.context_assembly import ContextBudget, assemble_context
from pam.agent.keyword_extractor import extract_query_keywords
from pam.agent.query_classifier import ClassificationResult, RetrievalMode, classify_query_mode
from pam.agent.tools import ALL_TOOLS
from pam.common.config import get_settings
from pam.common.logging import CostTracker
from pam.common.utils import escape_like
from pam.ingestion.embedders.base import BaseEmbedder
from pam.retrieval.search_protocol import SearchService
from pam.retrieval.types import SearchBackendError

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pam.agent.duckdb_service import DuckDBService
    from pam.graph.service import GraphitiService
    from pam.ingestion.stores.entity_relationship_store import (
        EntityRelationshipVDBStore,
    )

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are a business knowledge assistant. You answer questions using information \
retrieved from the business knowledge base via the available tools.

Available tools:
- smart_search: Search documents and the knowledge graph in one call using extracted keywords.
- search_knowledge: Search documents for relevant text segments.
- get_document_context: Fetch full document content for deep reading.
- get_change_history: See recent document changes and sync history.
- query_database: Run SQL queries on analytics data files (CSV/Parquet/JSON).
- search_entities: Search for structured business entities (metrics, events, KPIs).
- search_knowledge_graph: Search the knowledge graph for entity relationships and connections.
- get_entity_history: Get temporal change history of an entity in the knowledge graph.

Rules:
1. ALWAYS use tools to find information before answering.
2. Every factual claim MUST cite its source using this format: [Source: document_title > section](source_url)
3. If the source_url is not available, use: [Source: document_title > section]
4. If you cannot find relevant information, say so clearly — never make up facts.
5. For complex questions, you may search multiple times with different queries.
6. Synthesize information from multiple sources when relevant.
7. Be concise and direct in your answers.
8. Use search_knowledge_graph for questions about entity relationships, dependencies, and connections.
9. Use get_entity_history for questions about how entities changed over time or point-in-time queries.
10. You can combine document search and graph tools in one answer to give comprehensive results."""

MAX_TOOL_ITERATIONS = 5
MAX_DOC_CHARS = 50_000  # ~12,500 tokens — prevents blowing context window
MAX_HISTORY_CHARS = 400_000  # ~100K tokens — leaves room for system prompt + tool results


def _truncate_history(messages: list[dict], max_chars: int = MAX_HISTORY_CHARS) -> list[dict]:
    """Drop oldest message pairs if total character count exceeds budget.

    Always keeps the last message (the user's current question).
    Drops from the front in pairs (user+assistant) to maintain conversation coherence.
    """
    if not messages:
        return messages

    total = sum(len(m.get("content", "") if isinstance(m.get("content"), str) else "") for m in messages)
    if total <= max_chars:
        return messages

    # Keep dropping oldest pairs until under budget (or only 1 message left)
    trimmed = list(messages)
    while len(trimmed) > 1:
        total = sum(len(m.get("content", "") if isinstance(m.get("content"), str) else "") for m in trimmed)
        if total <= max_chars:
            break
        # Drop oldest message
        trimmed.pop(0)

    return trimmed


@dataclass
class Citation:
    document_title: str | None
    section_path: str | None
    source_url: str | None
    segment_id: str | None


@dataclass
class AgentResponse:
    answer: str
    citations: list[Citation] = field(default_factory=list)
    token_usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0
    tool_calls: int = 0
    retrieval_mode: str | None = None
    mode_confidence: float | None = None
    retrieved_context: list[str] = field(default_factory=list)


class RetrievalAgent:
    def __init__(
        self,
        search_service: SearchService,
        embedder: BaseEmbedder,
        api_key: str,
        model: str,
        cost_tracker: CostTracker | None = None,
        db_session: AsyncSession | None = None,
        duckdb_service: DuckDBService | None = None,
        graph_service: GraphitiService | None = None,
        vdb_store: EntityRelationshipVDBStore | None = None,
    ) -> None:
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model
        self.search = search_service
        self.embedder = embedder
        self.cost_tracker = cost_tracker or CostTracker()
        self.db_session = db_session
        self.duckdb_service = duckdb_service
        self.graph_service = graph_service
        self.vdb_store = vdb_store
        # NOTE: _default_source_type is instance state set per-call by answer()/answer_streaming().
        # This is safe because agents are instantiated per-request (see api/deps.py).
        # Do NOT share a single RetrievalAgent across concurrent requests.
        self._default_source_type: str | None = None
        self._last_classification: ClassificationResult | None = None

    async def answer(
        self,
        question: str,
        conversation_history: list | None = None,
        source_type: str | None = None,
    ) -> AgentResponse:
        """Answer a question using the knowledge base.

        Runs a tool-use loop: sends the question to Claude, executes any tool calls,
        appends results, and repeats until Claude provides a final answer.
        """
        self._default_source_type = source_type
        start = time.perf_counter()
        messages = list(conversation_history or [])
        messages = _truncate_history(messages)
        messages.append({"role": "user", "content": question})

        all_citations: list[Citation] = []
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0
        all_retrieved_context: list[str] = []

        for _ in range(MAX_TOOL_ITERATIONS):
            call_start = time.perf_counter()
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=cast(Any, ALL_TOOLS),
            )
            call_latency = (time.perf_counter() - call_start) * 1000

            # Track token usage
            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens
            self.cost_tracker.log_llm_call(
                self.model, response.usage.input_tokens, response.usage.output_tokens, call_latency
            )

            # Check if done (no more tool use)
            if response.stop_reason == "end_turn":
                answer_text = self._extract_text(response.content)
                total_latency = (time.perf_counter() - start) * 1000

                return AgentResponse(
                    answer=answer_text,
                    citations=all_citations,
                    token_usage={
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                    },
                    latency_ms=round(total_latency, 1),
                    tool_calls=tool_call_count,
                    retrieval_mode=self._last_classification.mode.value if self._last_classification else None,
                    mode_confidence=self._last_classification.confidence if self._last_classification else None,
                    retrieved_context=all_retrieved_context,
                )

            # Unexpected stop reason (e.g. max_tokens)
            if response.stop_reason != "tool_use":
                logger.warning(
                    "unexpected_stop_reason",
                    stop_reason=response.stop_reason,
                )
                answer_text = self._extract_text(response.content)
                total_latency = (time.perf_counter() - start) * 1000
                return AgentResponse(
                    answer=answer_text or "The response was cut short. Please try a more specific question.",
                    citations=all_citations,
                    token_usage={
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                    },
                    latency_ms=round(total_latency, 1),
                    tool_calls=tool_call_count,
                    retrieval_mode=self._last_classification.mode.value if self._last_classification else None,
                    mode_confidence=self._last_classification.confidence if self._last_classification else None,
                    retrieved_context=all_retrieved_context,
                )

            # Process tool calls
            if response.stop_reason == "tool_use":
                # Append assistant message with full content (text + tool_use blocks)
                messages.append({"role": "assistant", "content": response.content})

                # Execute each tool call
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        tool_call_count += 1
                        result, citations = await self._execute_tool(block.name, block.input)
                        if block.name in ("search_knowledge", "smart_search"):
                            if isinstance(result, str):
                                all_retrieved_context.append(result)
                        all_citations.extend(citations)
                        tool_results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            }
                        )
                        logger.info(
                            "agent_tool_call",
                            tool=block.name,
                            input=block.input,
                            result_length=len(result),
                        )

                messages.append({"role": "user", "content": tool_results})

        # If we hit max iterations, return what we have
        total_latency = (time.perf_counter() - start) * 1000
        return AgentResponse(
            answer="I was unable to fully answer your question within the allowed number of search steps. "
            "Please try rephrasing or asking a more specific question.",
            citations=all_citations,
            token_usage={
                "input_tokens": total_input_tokens,
                "output_tokens": total_output_tokens,
                "total_tokens": total_input_tokens + total_output_tokens,
            },
            latency_ms=round(total_latency, 1),
            tool_calls=tool_call_count,
            retrieval_mode=self._last_classification.mode.value if self._last_classification else None,
            mode_confidence=self._last_classification.confidence if self._last_classification else None,
            retrieved_context=all_retrieved_context,
        )

    async def answer_streaming(
        self,
        question: str,
        conversation_history: list | None = None,
        source_type: str | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream an answer as SSE events.

        Yields dicts with keys: type, content/data/message/metadata.
        Phase A: tool-use loop (non-streaming), yields status events.
        Phase B: final answer with token streaming.
        Phase C: citations and done event.
        """
        self._default_source_type = source_type
        start = time.perf_counter()
        messages = list(conversation_history or [])
        messages = _truncate_history(messages)
        messages.append({"role": "user", "content": question})

        all_citations: list[Citation] = []
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0
        answer_already_emitted = False

        try:
            # Phase A: Tool-use loop (non-streaming)
            for _ in range(MAX_TOOL_ITERATIONS):
                yield {"type": "status", "content": "Thinking..."}

                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=cast(Any, ALL_TOOLS),
                )
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                if response.stop_reason == "end_turn":
                    # No tool calls needed — stream the text we already have
                    answer_text = self._extract_text(response.content)
                    for token in self._chunk_text(answer_text, 4):
                        yield {"type": "token", "content": token}
                    answer_already_emitted = True
                    break

                if response.stop_reason not in ("end_turn", "tool_use"):
                    logger.warning(
                        "unexpected_stop_reason",
                        stop_reason=response.stop_reason,
                    )
                    answer_text = self._extract_text(response.content)
                    if answer_text:
                        for token in self._chunk_text(answer_text, 4):
                            yield {"type": "token", "content": token}
                    else:
                        msg = "The response was cut short. Please try a more specific question."
                        yield {"type": "token", "content": msg}
                    answer_already_emitted = True
                    break

                if response.stop_reason == "tool_use":
                    messages.append({"role": "assistant", "content": response.content})
                    tool_results = []
                    for block in response.content:
                        if block.type == "tool_use":
                            tool_call_count += 1
                            tool_name = block.name.replace("_", " ").title()
                            yield {"type": "status", "content": f"Using {tool_name}..."}
                            result, citations = await self._execute_tool(block.name, block.input)
                            all_citations.extend(citations)
                            tool_results.append(
                                {
                                    "type": "tool_result",
                                    "tool_use_id": block.id,
                                    "content": result,
                                }
                            )
                    messages.append({"role": "user", "content": tool_results})
                    continue

            else:
                # Hit max iterations — warn the user
                yield {
                    "type": "status",
                    "content": "Reached maximum search iterations without finding a complete answer.",
                }

            # Phase B: Final streaming call (if we went through tools and answer not yet emitted)
            if tool_call_count > 0 and not answer_already_emitted:
                yield {"type": "status", "content": "Generating answer..."}
                async with self.client.messages.stream(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                ) as stream:
                    async for text in stream.text_stream:
                        yield {"type": "token", "content": text}
                    final_message = await stream.get_final_message()
                    total_input_tokens += final_message.usage.input_tokens
                    total_output_tokens += final_message.usage.output_tokens

            # Phase C: Citations and done
            for c in all_citations:
                yield {
                    "type": "citation",
                    "data": {
                        "title": c.document_title,
                        "source_url": c.source_url,
                        "document_id": c.document_title,
                        "segment_id": c.segment_id,
                    },
                }

            total_latency = (time.perf_counter() - start) * 1000
            self.cost_tracker.log_llm_call(self.model, total_input_tokens, total_output_tokens, total_latency)
            yield {
                "type": "done",
                "metadata": {
                    "token_usage": {
                        "input_tokens": total_input_tokens,
                        "output_tokens": total_output_tokens,
                        "total_tokens": total_input_tokens + total_output_tokens,
                    },
                    "latency_ms": round(total_latency, 1),
                    "tool_calls": tool_call_count,
                    "retrieval_mode": self._last_classification.mode.value if self._last_classification else None,
                    "mode_confidence": self._last_classification.confidence if self._last_classification else None,
                },
            }

        except Exception as e:
            logger.exception("streaming_error", error=str(e))
            yield {
                "type": "error",
                "data": {"type": type(e).__name__, "message": str(e)},
                "message": f"An error occurred: {e!s}",
            }

    @staticmethod
    def _chunk_text(text: str, size: int = 4) -> list[str]:
        """Split text into word-based chunks for simulated streaming.

        Trailing spaces separate chunks so that non-first chunks never
        start with a leading space character.
        """
        words = text.split(" ")
        chunks = []
        for i in range(0, len(words), size):
            chunk = " ".join(words[i : i + size])
            if i + size < len(words):
                chunk += " "  # trailing space as word separator
            chunks.append(chunk)
        return chunks

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> tuple[str, list[Citation]]:
        """Execute a tool call and return (result_text, citations)."""
        if tool_name == "smart_search":
            return await self._smart_search(tool_input)
        if tool_name == "search_knowledge":
            return await self._search_knowledge(tool_input)
        if tool_name == "get_document_context":
            return await self._get_document_context(tool_input)
        if tool_name == "get_change_history":
            return await self._get_change_history(tool_input)
        if tool_name == "query_database":
            return await self._query_database(tool_input)
        if tool_name == "search_entities":
            return await self._search_entities(tool_input)
        if tool_name == "search_knowledge_graph":
            return await self._search_knowledge_graph(tool_input)
        if tool_name == "get_entity_history":
            return await self._get_entity_history(tool_input)
        return f"Unknown tool: {tool_name}", []

    async def _smart_search(self, input_: dict) -> tuple[str, list[Citation]]:
        """Execute the smart_search tool: keyword extraction + 4-way concurrent search.

        Extracts dual-level keywords from the query, then runs ES hybrid search
        (low-level keywords), graph relationship search (high-level keywords),
        entity VDB search (low-level keywords), and relationship VDB search
        (high-level keywords) concurrently via asyncio.gather.  Returns results
        in separate sections with extracted keywords for transparency.
        """
        query = input_["query"]

        # Step A: Extract keywords
        try:
            keywords = await extract_query_keywords(self.client, query)
        except Exception as exc:
            logger.warning("smart_search_keyword_extraction_failed", error=str(exc))
            return (
                f"Keyword extraction failed: {exc}. "
                "Try search_knowledge or search_knowledge_graph instead."
            ), []

        # Step A2: Classify query mode
        forced_mode_str = input_.get("mode")
        if forced_mode_str:
            try:
                mode = RetrievalMode(forced_mode_str)
                classification = ClassificationResult(mode=mode, confidence=1.0, method="forced")
            except ValueError:
                # Invalid mode string from tool input; fall back to auto-classification
                classification = await classify_query_mode(
                    query, client=self.client, vdb_store=self.vdb_store,
                )
                mode = classification.mode
        else:
            classification = await classify_query_mode(
                query, client=self.client, vdb_store=self.vdb_store,
            )
            mode = classification.mode

        logger.info(
            "smart_search_mode_selected",
            mode=mode.value,
            confidence=classification.confidence,
            method=classification.method,
            query=query[:100],
        )

        # Step B: Prepare search queries
        es_query = " ".join(keywords.low_level_keywords) if keywords.low_level_keywords else query
        graph_query = " ".join(keywords.high_level_keywords) if keywords.high_level_keywords else query

        settings = get_settings()
        es_limit = settings.smart_search_es_limit
        _graph_limit = settings.smart_search_graph_limit  # reserved for future re-query backfill

        # Step B2: Embed both queries upfront (reuse for VDB searches)
        # es_query_embedding -> ES segment search + entity VDB search (low-level)
        # graph_query_embedding -> relationship VDB search (high-level)
        query_embeddings = await self.embedder.embed_texts([es_query, graph_query])
        es_query_embedding = query_embeddings[0]
        graph_query_embedding = query_embeddings[1]

        # Step C: Define async search coroutines
        async def _es_search_coro() -> list:
            return await self.search.search(
                query=es_query,
                query_embedding=es_query_embedding,
                top_k=es_limit,
                source_type=self._default_source_type,
            )

        async def _graph_search_coro() -> str:
            if self.graph_service is None:
                return ""
            from pam.graph.query import search_graph_relationships

            return await search_graph_relationships(
                graph_service=self.graph_service,
                query=graph_query,
            )

        async def _entity_vdb_search_coro() -> list[dict]:
            if self.vdb_store is None:
                return []
            return await self.vdb_store.search_entities(
                query_embedding=es_query_embedding,
                top_k=settings.smart_search_entity_limit,
            )

        async def _rel_vdb_search_coro() -> list[dict]:
            if self.vdb_store is None:
                return []
            return await self.vdb_store.search_relationships(
                query_embedding=graph_query_embedding,
                top_k=settings.smart_search_relationship_limit,
            )

        # Step D: Run searches concurrently (mode-conditioned)
        async def _noop_list() -> list:
            return []

        async def _noop_str() -> str:
            return ""

        if mode == RetrievalMode.FACTUAL:
            es_coro = _es_search_coro()
            graph_coro = _noop_str()
            entity_vdb_coro = _noop_list()
            rel_vdb_coro = _noop_list()
        elif mode == RetrievalMode.ENTITY:
            es_coro = _es_search_coro()
            graph_coro = _noop_str()
            entity_vdb_coro = _entity_vdb_search_coro()
            rel_vdb_coro = _noop_list()
        elif mode == RetrievalMode.CONCEPTUAL:
            es_coro = _es_search_coro()
            graph_coro = _graph_search_coro()
            entity_vdb_coro = _noop_list()
            rel_vdb_coro = _rel_vdb_search_coro()
        else:  # TEMPORAL or HYBRID — all paths
            es_coro = _es_search_coro()
            graph_coro = _graph_search_coro()
            entity_vdb_coro = _entity_vdb_search_coro()
            rel_vdb_coro = _rel_vdb_search_coro()

        es_result, graph_result, entity_vdb_result, rel_vdb_result = await asyncio.gather(
            es_coro, graph_coro, entity_vdb_coro, rel_vdb_coro,
            return_exceptions=True,
        )

        warnings: list[str] = []

        if isinstance(es_result, Exception):
            logger.warning("smart_search_es_failed", error=str(es_result))
            es_results: list = []
            warnings.append("es_backend_failed")
        else:
            es_results = es_result

        if isinstance(graph_result, Exception):
            logger.warning("smart_search_graph_failed", error=str(graph_result))
            graph_text: str = ""
            warnings.append("graph_backend_failed")
        else:
            graph_text = graph_result

        if isinstance(entity_vdb_result, Exception):
            logger.warning("smart_search_entity_vdb_failed", error=str(entity_vdb_result))
            entity_vdb_results: list[dict] = []
            warnings.append("entity_vdb_failed")
        else:
            entity_vdb_results = entity_vdb_result

        if isinstance(rel_vdb_result, Exception):
            logger.warning("smart_search_rel_vdb_failed", error=str(rel_vdb_result))
            rel_vdb_results: list[dict] = []
            warnings.append("relationship_vdb_failed")
        else:
            rel_vdb_results = rel_vdb_result

        # Step E: Extract citations from ES results (for agent response attribution)
        citations: list[Citation] = []
        for r in es_results:
            citation = Citation(
                document_title=r.document_title,
                section_path=r.section_path,
                source_url=r.source_url,
                segment_id=str(r.segment_id),
            )
            citations.append(citation)

        # Step F: Assemble structured context with token budgets
        budget = ContextBudget(
            entity_tokens=settings.context_entity_budget,
            relationship_tokens=settings.context_relationship_budget,
            max_total_tokens=settings.context_max_tokens,
        )
        assembled = assemble_context(
            es_results=es_results,
            graph_text=graph_text,
            entity_vdb_results=entity_vdb_results,
            rel_vdb_results=rel_vdb_results,
            budget=budget,
        )

        # Step G: Build final output with keywords header + assembled context
        parts: list[str] = []
        parts.append("Keywords extracted:")
        parts.append(f"- High-level: {', '.join(keywords.high_level_keywords)}")
        parts.append(f"- Low-level: {', '.join(keywords.low_level_keywords)}")
        parts.append("")
        parts.append(assembled.text)

        if warnings:
            parts.append("")
            parts.extend(
                f"Warning: {w} search was unavailable, showing partial results."
                for w in warnings
            )

        # Store classification for response metadata propagation
        self._last_classification = classification

        return "\n".join(parts), citations

    async def _search_knowledge(self, input_: dict) -> tuple[str, list[Citation]]:
        """Execute the search_knowledge tool."""
        query = input_["query"]
        source_type = input_.get("source_type") or self._default_source_type

        # Embed the query
        query_embeddings = await self.embedder.embed_texts([query])
        query_embedding = query_embeddings[0]

        # Search
        try:
            results = await self.search.search(
                query=query,
                query_embedding=query_embedding,
                top_k=10,
                source_type=source_type,
            )
        except SearchBackendError as exc:
            logger.warning("search_backend_error", query=query[:100], error=str(exc))
            return "Search is temporarily unavailable. Please try again.", []

        if not results:
            return "No relevant results found for this query.", []

        # Format results for the LLM
        citations = []
        formatted_parts = []

        for i, r in enumerate(results, 1):
            citation = Citation(
                document_title=r.document_title,
                section_path=r.section_path,
                source_url=r.source_url,
                segment_id=str(r.segment_id),
            )
            citations.append(citation)

            source_label = r.document_title or r.source_id or "Unknown"
            if r.section_path:
                source_label += f" > {r.section_path}"

            url_part = f" ({r.source_url})" if r.source_url else ""
            formatted_parts.append(f"[Result {i}] Source: {source_label}{url_part}\n{r.content}")

        return "\n\n---\n\n".join(formatted_parts), citations

    async def _get_document_context(self, input_: dict) -> tuple[str, list[Citation]]:
        """Fetch full document content by title or source_id."""
        if self.db_session is None:
            return "Database session not available.", []

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from pam.common.models import Document

        title = input_.get("document_title")
        source_id = input_.get("source_id")

        if not title and not source_id:
            return "Please provide either document_title or source_id.", []

        query = select(Document).options(selectinload(Document.segments))
        if title:
            query = query.where(Document.title.ilike(f"%{escape_like(title)}%"))
        elif source_id:
            query = query.where(Document.source_id == source_id)

        result = await self.db_session.execute(query)
        doc = result.scalar_one_or_none()

        if doc is None:
            return f"Document not found: {title or source_id}", []

        # Sort segments by position and concatenate
        segments = sorted(doc.segments, key=lambda s: s.position)
        full_content = "\n\n".join(s.content for s in segments)

        # Truncate if too large to prevent context window overflow
        truncated = False
        if len(full_content) > MAX_DOC_CHARS:
            full_content = full_content[:MAX_DOC_CHARS]
            truncated = True

        citation = Citation(
            document_title=doc.title,
            section_path=None,
            source_url=doc.source_url,
            segment_id=None,
        )

        header = f"Document: {doc.title}\nSource: {doc.source_id}\nSegments: {len(segments)}\n\n"
        result = header + full_content
        if truncated:
            result += "\n\n[truncated] Document content was too large. Use search_knowledge for specific sections."
        return result, [citation]

    async def _get_change_history(self, input_: dict) -> tuple[str, list[Citation]]:
        """Query sync_log for recent changes."""
        if self.db_session is None:
            return "Database session not available.", []

        from sqlalchemy import select

        from pam.common.models import Document, SyncLog

        limit = input_.get("limit", 20)
        title = input_.get("document_title")

        query = select(SyncLog).order_by(SyncLog.created_at.desc()).limit(limit)

        if title:
            # Join with documents to filter by title
            subq = select(Document.id).where(Document.title.ilike(f"%{escape_like(title)}%"))
            query = query.where(SyncLog.document_id.in_(subq))

        result = await self.db_session.execute(query)
        logs = result.scalars().all()

        if not logs:
            return "No change history found.", []

        parts = [
            f"- [{log.created_at}] {log.action}"
            f" | segments_affected: {log.segments_affected}"
            f" | details: {json.dumps(log.details) if log.details else 'N/A'}"
            for log in logs
        ]

        return f"Recent changes ({len(logs)} records):\n" + "\n".join(parts), []

    async def _query_database(self, input_: dict) -> tuple[str, list[Citation]]:
        """Execute a DuckDB SQL query over registered data files."""
        if self.duckdb_service is None:
            return "DuckDB service not configured. Set DUCKDB_DATA_DIR.", []

        if input_.get("list_tables"):
            tables = self.duckdb_service.list_tables()
            if not tables:
                return "No data tables registered.", []
            parts = []
            for t in tables:
                if "error" in t:
                    parts.append(f"- {t['table']} ({t['file']}): ERROR - {t['error']}")
                else:
                    cols = ", ".join(f"{c['name']} ({c['type']})" for c in t["columns"])
                    parts.append(f"- {t['table']} ({t['file']}, {t['row_count']} rows): {cols}")
            return "Available tables:\n" + "\n".join(parts), []

        sql = input_.get("sql")
        if not sql:
            return "Please provide either 'sql' query or set 'list_tables' to true.", []

        result = self.duckdb_service.execute_query(sql)
        if "error" in result:
            return f"Query error: {result['error']}", []

        # Format as table
        columns = result["columns"]
        rows = result["rows"]
        header = " | ".join(columns)
        separator = " | ".join("---" for _ in columns)
        body = "\n".join(" | ".join(str(v) for v in row) for row in rows)
        truncated_note = "\n(Results truncated)" if result.get("truncated") else ""

        return f"{header}\n{separator}\n{body}{truncated_note}\n\n({result['row_count']} rows)", []

    async def _search_entities(self, input_: dict) -> tuple[str, list[Citation]]:
        """Search for extracted business entities."""
        if self.db_session is None:
            return "Database session not available.", []

        from sqlalchemy import String, cast, select

        from pam.common.models import ExtractedEntity

        entity_type = input_.get("entity_type")
        search_term = input_.get("search_term")
        limit = input_.get("limit", 10)

        query = select(ExtractedEntity).order_by(ExtractedEntity.confidence.desc()).limit(limit)

        if entity_type:
            query = query.where(ExtractedEntity.entity_type == entity_type)
        if search_term:
            # Search in the JSONB entity_data — cast to text for ILIKE
            query = query.where(cast(ExtractedEntity.entity_data, String).ilike(f"%{escape_like(search_term)}%"))

        result = await self.db_session.execute(query)
        entities = result.scalars().all()

        if not entities:
            return "No matching entities found.", []

        parts = []
        for e in entities:
            data_str = json.dumps(e.entity_data, indent=2)
            parts.append(f"[{e.entity_type}] (confidence: {e.confidence:.1%})\n{data_str}")

        return f"Found {len(entities)} entities:\n\n" + "\n\n---\n\n".join(parts), []

    async def _search_knowledge_graph(self, input_: dict) -> tuple[str, list[Citation]]:
        """Execute the search_knowledge_graph tool."""
        if self.graph_service is None:
            return "Knowledge graph is not available. Try search_knowledge instead.", []

        from pam.graph.query import search_graph_relationships

        result_text = await search_graph_relationships(
            graph_service=self.graph_service,
            query=input_["query"],
            entity_name=input_.get("entity_name"),
            relationship_type=input_.get("relationship_type"),
        )
        return result_text, []

    async def _get_entity_history(self, input_: dict) -> tuple[str, list[Citation]]:
        """Execute the get_entity_history tool for temporal queries."""
        if self.graph_service is None:
            return "Knowledge graph is not available.", []

        from pam.graph.query import get_entity_history

        result_text = await get_entity_history(
            graph_service=self.graph_service,
            entity_name=input_["entity_name"],
            since=input_.get("since"),
            reference_time=input_.get("reference_time"),
        )
        return result_text, []

    @staticmethod
    def _extract_text(content: list) -> str:
        """Extract text from Claude response content blocks."""
        parts = [block.text for block in content if hasattr(block, "text")]
        return "\n".join(parts)
