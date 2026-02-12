"""Retrieval agent using a simple tool-use loop with the Anthropic SDK."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import structlog
from anthropic import AsyncAnthropic

from pam.agent.tools import ALL_TOOLS
from pam.common.config import settings
from pam.common.logging import CostTracker
from pam.ingestion.embedders.base import BaseEmbedder
from pam.retrieval.hybrid_search import HybridSearchService
from pam.retrieval.types import SearchResult

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from pam.agent.duckdb_service import DuckDBService

logger = structlog.get_logger()

SYSTEM_PROMPT = """You are a business knowledge assistant. You answer questions using information \
retrieved from the business knowledge base via the available tools.

Available tools:
- search_knowledge: Search documents for relevant text segments.
- get_document_context: Fetch full document content for deep reading.
- get_change_history: See recent document changes and sync history.
- query_database: Run SQL queries on analytics data files (CSV/Parquet/JSON).

Rules:
1. ALWAYS use tools to find information before answering.
2. Every factual claim MUST cite its source using this format: [Source: document_title > section](source_url)
3. If the source_url is not available, use: [Source: document_title > section]
4. If you cannot find relevant information, say so clearly — never make up facts.
5. For complex questions, you may search multiple times with different queries.
6. Synthesize information from multiple sources when relevant.
7. Be concise and direct in your answers."""

MAX_TOOL_ITERATIONS = 5


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


class RetrievalAgent:
    def __init__(
        self,
        search_service: HybridSearchService,
        embedder: BaseEmbedder,
        api_key: str | None = None,
        model: str | None = None,
        cost_tracker: CostTracker | None = None,
        db_session: AsyncSession | None = None,
        duckdb_service: DuckDBService | None = None,
    ) -> None:
        self.client = AsyncAnthropic(api_key=api_key or settings.anthropic_api_key)
        self.model = model or settings.agent_model
        self.search = search_service
        self.embedder = embedder
        self.cost_tracker = cost_tracker or CostTracker()
        self.db_session = db_session
        self.duckdb_service = duckdb_service

    async def answer(self, question: str, conversation_history: list | None = None) -> AgentResponse:
        """Answer a question using the knowledge base.

        Runs a tool-use loop: sends the question to Claude, executes any tool calls,
        appends results, and repeats until Claude provides a final answer.
        """
        start = time.perf_counter()
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": question})

        all_citations: list[Citation] = []
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0

        for _ in range(MAX_TOOL_ITERATIONS):
            call_start = time.perf_counter()
            response = await self.client.messages.create(
                model=self.model,
                max_tokens=4096,
                system=SYSTEM_PROMPT,
                messages=messages,
                tools=ALL_TOOLS,
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
        )

    async def answer_streaming(
        self, question: str, conversation_history: list | None = None
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream an answer as SSE events.

        Yields dicts with keys: type, content/data/message/metadata.
        Phase A: tool-use loop (non-streaming), yields status events.
        Phase B: final answer with token streaming.
        Phase C: citations and done event.
        """
        start = time.perf_counter()
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": question})

        all_citations: list[Citation] = []
        total_input_tokens = 0
        total_output_tokens = 0
        tool_call_count = 0

        try:
            # Phase A: Tool-use loop (non-streaming)
            for _ in range(MAX_TOOL_ITERATIONS):
                yield {"type": "status", "content": "Thinking..."}

                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=SYSTEM_PROMPT,
                    messages=messages,
                    tools=ALL_TOOLS,
                )
                total_input_tokens += response.usage.input_tokens
                total_output_tokens += response.usage.output_tokens

                if response.stop_reason == "end_turn":
                    # No tool calls needed — stream the text we already have
                    answer_text = self._extract_text(response.content)
                    for token in self._chunk_text(answer_text, 4):
                        yield {"type": "token", "content": token}
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
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result,
                            })
                    messages.append({"role": "user", "content": tool_results})
                    continue

            else:
                # Hit max iterations — do a final streaming call
                pass

            # Phase B: Final streaming call (if we went through tools)
            if tool_call_count > 0:
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
            self.cost_tracker.log_llm_call(
                self.model, total_input_tokens, total_output_tokens, total_latency
            )
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
                },
            }

        except Exception as e:
            logger.error("streaming_error", error=str(e))
            yield {"type": "error", "message": str(e)}

    @staticmethod
    def _chunk_text(text: str, size: int = 4) -> list[str]:
        """Split text into word-based chunks for simulated streaming."""
        words = text.split(" ")
        chunks = []
        for i in range(0, len(words), size):
            chunk = " ".join(words[i : i + size])
            if i > 0:
                chunk = " " + chunk
            chunks.append(chunk)
        return chunks

    async def _execute_tool(self, tool_name: str, tool_input: dict) -> tuple[str, list[Citation]]:
        """Execute a tool call and return (result_text, citations)."""
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
        return f"Unknown tool: {tool_name}", []

    async def _search_knowledge(self, input_: dict) -> tuple[str, list[Citation]]:
        """Execute the search_knowledge tool."""
        query = input_["query"]
        source_type = input_.get("source_type")

        # Embed the query
        query_embeddings = await self.embedder.embed_texts([query])
        query_embedding = query_embeddings[0]

        # Search
        results = await self.search.search(
            query=query,
            query_embedding=query_embedding,
            top_k=10,
            source_type=source_type,
        )

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
        from pam.common.models import Document, Segment

        title = input_.get("document_title")
        source_id = input_.get("source_id")

        if not title and not source_id:
            return "Please provide either document_title or source_id.", []

        query = select(Document).options(selectinload(Document.segments))
        if title:
            query = query.where(Document.title.ilike(f"%{title}%"))
        elif source_id:
            query = query.where(Document.source_id == source_id)

        result = await self.db_session.execute(query)
        doc = result.scalar_one_or_none()

        if doc is None:
            return f"Document not found: {title or source_id}", []

        # Sort segments by position and concatenate
        segments = sorted(doc.segments, key=lambda s: s.position)
        full_content = "\n\n".join(s.content for s in segments)

        citation = Citation(
            document_title=doc.title,
            section_path=None,
            source_url=doc.source_url,
            segment_id=None,
        )

        header = f"Document: {doc.title}\nSource: {doc.source_id}\nSegments: {len(segments)}\n\n"
        return header + full_content, [citation]

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
            subq = select(Document.id).where(Document.title.ilike(f"%{title}%"))
            query = query.where(SyncLog.document_id.in_(subq))

        result = await self.db_session.execute(query)
        logs = result.scalars().all()

        if not logs:
            return "No change history found.", []

        parts = []
        for log in logs:
            parts.append(
                f"- [{log.created_at}] {log.action}"
                f" | segments_affected: {log.segments_affected}"
                f" | details: {json.dumps(log.details) if log.details else 'N/A'}"
            )

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

        from sqlalchemy import select, cast, String
        from pam.common.models import ExtractedEntity

        entity_type = input_.get("entity_type")
        search_term = input_.get("search_term")
        limit = input_.get("limit", 10)

        query = select(ExtractedEntity).order_by(ExtractedEntity.confidence.desc()).limit(limit)

        if entity_type:
            query = query.where(ExtractedEntity.entity_type == entity_type)
        if search_term:
            # Search in the JSONB entity_data — cast to text for ILIKE
            query = query.where(cast(ExtractedEntity.entity_data, String).ilike(f"%{search_term}%"))

        result = await self.db_session.execute(query)
        entities = result.scalars().all()

        if not entities:
            return "No matching entities found.", []

        parts = []
        for e in entities:
            data_str = json.dumps(e.entity_data, indent=2)
            parts.append(
                f"[{e.entity_type}] (confidence: {e.confidence:.1%})\n{data_str}"
            )

        return f"Found {len(entities)} entities:\n\n" + "\n\n---\n\n".join(parts), []

    @staticmethod
    def _extract_text(content: list) -> str:
        """Extract text from Claude response content blocks."""
        parts = []
        for block in content:
            if hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)
