"""Token-budgeted context assembly for the LLM agent.

Implements a 4-stage pipeline inspired by LightRAG's _build_query_context pattern:
  Stage 1 (Collect):   Normalize raw search results into uniform dicts
  Stage 2 (Truncate):  Per-category token truncation sorted by relevance score
  Stage 3 (Dedup):     Chunk deduplication by segment_id
  Stage 4 (Build):     Structured Markdown prompt construction
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
import tiktoken

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Token counting (lazy singleton)
# ---------------------------------------------------------------------------

_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    """Lazy-load and cache the tiktoken cl100k_base encoder (singleton)."""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in *text* using cl100k_base encoding."""
    return len(_get_encoder().encode(text))


def _truncate_text_to_tokens(text: str, max_tokens: int) -> str:
    """Truncate *text* to at most *max_tokens* tokens.

    If truncated, ``"..."`` is appended to signal the cut.
    """
    encoder = _get_encoder()
    tokens = encoder.encode(text)
    if len(tokens) <= max_tokens:
        return text
    truncated = encoder.decode(tokens[:max_tokens])
    return truncated + "..."


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ContextBudget:
    """Token budget configuration for context assembly."""

    entity_tokens: int = 4000
    relationship_tokens: int = 6000
    max_total_tokens: int = 16000
    max_item_tokens: int = 500  # per-item description truncation cap
    memory_tokens: int = 2000
    conversation_tokens: int = 2000


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


# ---------------------------------------------------------------------------
# Stage helpers
# ---------------------------------------------------------------------------


def truncate_list_by_token_budget(
    items: list[dict],
    text_key: str,
    max_tokens: int,
    max_item_tokens: int = 500,
) -> tuple[list[dict], int, int]:
    """Truncate a list of items to fit within *max_tokens*.

    Items whose text exceeds *max_item_tokens* have their text truncated
    (not dropped).

    Returns ``(truncated_items, tokens_used, total_items_before_truncation)``.
    """
    total_before = len(items)
    result: list[dict] = []
    tokens_used = 0

    for item in items:
        text = item.get(text_key, "")
        item_tokens = count_tokens(text)

        # Truncate individual item text if it exceeds the per-item cap
        if item_tokens > max_item_tokens:
            text = _truncate_text_to_tokens(text, max_item_tokens)
            item_tokens = count_tokens(text)
            item = {**item, text_key: text}

        if tokens_used + item_tokens > max_tokens:
            break

        result.append(item)
        tokens_used += item_tokens

    return result, tokens_used, total_before


def deduplicate_chunks(chunks: list[dict], key: str = "segment_id") -> list[dict]:
    """Remove duplicate chunks by *key*, preserving insertion order.

    First occurrence wins.  Items missing the key (or with an empty-string
    value) are always included.
    """
    seen: set[str] = set()
    result: list[dict] = []
    for chunk in chunks:
        chunk_key = str(chunk.get(key, ""))
        if chunk_key and chunk_key in seen:
            continue
        if chunk_key:
            seen.add(chunk_key)
        result.append(chunk)
    return result


def _calculate_chunk_budget(
    max_total: int,
    entity_budget: int,
    relationship_budget: int,
    entity_tokens_used: int,
    relationship_tokens_used: int,
) -> int:
    """Calculate the dynamic chunk budget with unused redistribution.

    *max_total* is the remaining token budget after memory and conversation
    tokens have been subtracted by the caller.
    Base chunk budget = max_total - entity_budget - relationship_budget.
    Any unused tokens from entities / relationships are added back.
    Result is floored at 0.
    """
    base = max_total - entity_budget - relationship_budget
    unused_entities = max(entity_budget - entity_tokens_used, 0)
    unused_relationships = max(relationship_budget - relationship_tokens_used, 0)
    return max(base + unused_entities + unused_relationships, 0)


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


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


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
        Dicts with ``content``, ``type``, and ``score`` from user memory search.
    conversation_context:
        Pre-formatted recent conversation text.

    Returns
    -------
    AssembledContext
        The assembled Markdown text and per-category token usage.
    """
    budget = budget or ContextBudget()

    # ---- Memory & Conversation truncation ----
    memory_results = memory_results or []
    memories_sorted = sorted(memory_results, key=lambda x: x.get("score", 0), reverse=True)
    memories_truncated, memory_tokens_used, _ = truncate_list_by_token_budget(
        memories_sorted, "content", budget.memory_tokens, budget.max_item_tokens,
    )

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
        entity_tokens_used + relationship_tokens_used + chunk_tokens_used
        + memory_tokens_used + conversation_tokens_used
    )

    logger.debug(
        "context_assembly_budget",
        entities=f"{entity_tokens_used}/{budget.entity_tokens}",
        relationships=f"{relationship_tokens_used}/{budget.relationship_tokens}",
        chunks=f"{chunk_tokens_used}/{chunk_budget}",
        memory=f"{memory_tokens_used}/{budget.memory_tokens}",
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
