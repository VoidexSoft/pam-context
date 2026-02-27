"""Two-tier query classifier for retrieval mode routing.

Categorizes user queries into 5 retrieval modes (entity, conceptual,
temporal, factual, hybrid) using rule-based heuristics as the primary
layer and an LLM fallback via Claude Haiku for ambiguous queries.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

import structlog
from anthropic import AsyncAnthropic

from pam.common.config import Settings, get_settings

if TYPE_CHECKING:
    from pam.ingestion.stores.entity_relationship_store import (
        EntityRelationshipVDBStore,
    )

logger = structlog.get_logger()


class RetrievalMode(str, Enum):
    """Retrieval strategy modes for query routing."""

    ENTITY = "entity"  # Shallow graph: ES + entity VDB
    CONCEPTUAL = "conceptual"  # Deep graph: Graphiti + relationship VDB
    TEMPORAL = "temporal"  # All paths with temporal focus
    FACTUAL = "factual"  # ES-only, skip graph entirely
    HYBRID = "hybrid"  # All 4 retrieval paths (default)


@dataclass
class ClassificationResult:
    """Result of query mode classification."""

    mode: RetrievalMode
    confidence: float  # 0.0 - 1.0
    method: str  # "rules", "llm", or "default"


# Stop words excluded from single-word entity candidate detection
_STOP_WORDS = frozenset(
    {
        "The",
        "This",
        "That",
        "What",
        "When",
        "Where",
        "How",
        "Who",
        "Which",
        "Does",
        "Did",
        "Can",
        "Could",
        "Would",
        "Should",
        "Has",
        "Have",
        "Had",
    }
)

# Regex for multi-word capitalized names (e.g., "Auth Service", "Sales Team")
_MULTI_WORD_CAP_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")

# Regex for PascalCase compound words (e.g., "AuthService", "PaymentGateway")
_PASCAL_CASE_RE = re.compile(r"\b([A-Z][a-z]+[A-Z][a-zA-Z]*)\b")

# Regex for single capitalized words (3+ chars, not at sentence start)
_SINGLE_CAP_RE = re.compile(r"(?<!^)(?<!\. )(?<!\? )(?<! !\s)\b([A-Z][a-z]{2,})\b")


LLM_CLASSIFICATION_PROMPT = """\
Classify this query into exactly one retrieval mode.
Modes:
- entity: about a specific named entity, its properties or neighbors
- conceptual: about relationships, dependencies, patterns between entities
- temporal: about changes over time, history, before/after comparisons
- factual: simple definition or fact lookup, answerable from documents alone
- hybrid: unclear or spans multiple modes

Output JSON only: {{"mode": "<mode>", "confidence": <0.0-1.0>}}

Query: "{query}"
"""


async def classify_query_mode(
    query: str,
    client: AsyncAnthropic | None = None,
    vdb_store: EntityRelationshipVDBStore | None = None,
) -> ClassificationResult:
    """Classify a query into a retrieval mode using a two-tier approach.

    Steps:
    1. Rule-based classification (regex patterns, keyword detection)
    2. Entity name lookup against ES (if vdb_store provided)
    3. LLM fallback via Haiku (if client provided and enabled)
    4. Default to hybrid mode

    Args:
        query: The user's natural language query.
        client: Optional Anthropic async client for LLM fallback.
        vdb_store: Optional VDB store for entity name ES lookup.

    Returns:
        ClassificationResult with mode, confidence, and method.
    """
    settings = get_settings()
    threshold = settings.mode_confidence_threshold

    # Step 1: Rule-based classification
    result = _rule_based_classify(query, settings)
    if result.confidence >= threshold:
        logger.info(
            "query_mode_classified",
            mode=result.mode.value,
            confidence=result.confidence,
            method=result.method,
            query=query[:100],
        )
        return result

    # Step 2: Entity name lookup (async)
    if vdb_store is not None:
        entity_result = await _check_entity_mentions(query, vdb_store)
        if entity_result is not None and entity_result.confidence >= threshold:
            logger.info(
                "query_mode_classified",
                mode=entity_result.mode.value,
                confidence=entity_result.confidence,
                method=entity_result.method,
                query=query[:100],
            )
            return entity_result

    # Step 3: LLM fallback
    if client is not None and settings.mode_llm_fallback_enabled:
        llm_result = await _llm_classify(query, client)
        if llm_result.confidence >= threshold:
            logger.info(
                "query_mode_classified",
                mode=llm_result.mode.value,
                confidence=llm_result.confidence,
                method=llm_result.method,
                query=query[:100],
            )
            return llm_result

    # Step 4: Default to hybrid
    result = ClassificationResult(
        mode=RetrievalMode.HYBRID,
        confidence=0.5,
        method="default",
    )
    logger.info(
        "query_mode_classified",
        mode=result.mode.value,
        confidence=result.confidence,
        method=result.method,
        query=query[:100],
    )
    return result


def _rule_based_classify(query: str, settings: Settings) -> ClassificationResult:
    """Classify a query using rule-based heuristics.

    Priority order (highest specificity first):
    1. Temporal (time-related keywords)
    2. Factual (question patterns, with negative signal for entity/conceptual overlap)
    3. Conceptual (relationship keywords)
    4. Hybrid fallback (no confident match)
    """
    query_lower = query.lower().strip()

    # Parse keyword lists from settings
    temporal_keywords = [
        kw.strip() for kw in settings.mode_temporal_keywords.split(",")
    ]
    factual_patterns = [
        pat.strip() for pat in settings.mode_factual_patterns.split(",")
    ]
    conceptual_keywords = [
        kw.strip() for kw in settings.mode_conceptual_keywords.split(",")
    ]

    # Build regex patterns with word boundaries
    temporal_regexes = [re.compile(rf"\b{re.escape(kw)}\b") for kw in temporal_keywords]
    factual_regexes = [re.compile(rf"^{re.escape(pat)}\b") for pat in factual_patterns]
    conceptual_regexes = [
        re.compile(rf"\b{re.escape(kw)}\b") for kw in conceptual_keywords
    ]

    # 1. Temporal (highest specificity)
    temporal_matches = sum(
        1 for rx in temporal_regexes if rx.search(query_lower)
    )
    if temporal_matches >= 2:
        return ClassificationResult(RetrievalMode.TEMPORAL, 0.9, "rules")
    if temporal_matches == 1:
        return ClassificationResult(RetrievalMode.TEMPORAL, 0.75, "rules")

    # 2. Factual (question patterns, anchored to start)
    factual_match = any(rx.search(query_lower) for rx in factual_regexes)
    if factual_match:
        # Negative signal: check for conceptual keywords or entity mentions
        conceptual_overlap = any(rx.search(query_lower) for rx in conceptual_regexes)
        has_entity_mention = bool(_MULTI_WORD_CAP_RE.search(query)) or bool(
            _PASCAL_CASE_RE.search(query)
        )
        if conceptual_overlap or has_entity_mention:
            # Reduce confidence below threshold to avoid misclassifying
            return ClassificationResult(RetrievalMode.FACTUAL, 0.5, "rules")
        return ClassificationResult(RetrievalMode.FACTUAL, 0.8, "rules")

    # 3. Conceptual (relationship keywords)
    conceptual_matches = sum(
        1 for rx in conceptual_regexes if rx.search(query_lower)
    )
    if conceptual_matches >= 2:
        return ClassificationResult(RetrievalMode.CONCEPTUAL, 0.85, "rules")
    if conceptual_matches == 1:
        return ClassificationResult(RetrievalMode.CONCEPTUAL, 0.7, "rules")

    # 4. No confident match
    return ClassificationResult(RetrievalMode.HYBRID, 0.4, "rules")


def _extract_candidate_names(query: str) -> list[str]:
    """Extract potential entity name candidates from a query.

    Finds:
    - Sequences of 2+ consecutive capitalized words (e.g., "Auth Service")
    - PascalCase compound words (e.g., "AuthService", "PaymentGateway")
    - Single capitalized words (3+ chars) not at sentence start, excluding stop words

    Returns:
        Deduplicated list of candidate entity names.
    """
    candidates: list[str] = []

    # Multi-word capitalized names
    for match in _MULTI_WORD_CAP_RE.finditer(query):
        candidates.append(match.group(1))

    # PascalCase compound words
    for match in _PASCAL_CASE_RE.finditer(query):
        candidates.append(match.group(1))

    # Single capitalized words (not at sentence start, not stop words)
    for match in _SINGLE_CAP_RE.finditer(query):
        word = match.group(1)
        if word not in _STOP_WORDS:
            candidates.append(word)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            unique.append(c)
    return unique


async def _check_entity_mentions(
    query: str,
    vdb_store: EntityRelationshipVDBStore,
) -> ClassificationResult | None:
    """Check if the query mentions known entities in the pam_entities ES index.

    Uses a terms query on the name keyword field with candidate names
    extracted from the query. Returns ENTITY mode if any match is found.

    Args:
        query: The user's query.
        vdb_store: VDB store with client and entity_index attributes.

    Returns:
        ClassificationResult with ENTITY mode if match found, None otherwise.
    """
    candidates = _extract_candidate_names(query)
    if not candidates:
        return None

    # Query ES for matching entity names (use original casing for keyword field)
    body = {
        "query": {"terms": {"name": candidates}},
        "size": 1,
        "_source": ["name"],
    }
    try:
        response = await vdb_store.client.search(
            index=vdb_store.entity_index,
            body=body,
        )
        if response["hits"]["total"]["value"] > 0:
            return ClassificationResult(RetrievalMode.ENTITY, 0.85, "rules")
    except Exception:
        logger.debug("entity_mention_check_failed", query=query[:100], exc_info=True)
    return None


async def _llm_classify(
    query: str,
    client: AsyncAnthropic,
) -> ClassificationResult:
    """Classify a query using Claude Haiku as a fallback.

    Uses the same LLM call pattern as extract_query_keywords() in
    keyword_extractor.py. Returns hybrid mode on any error (graceful
    degradation).

    Args:
        query: The user's query.
        client: Anthropic async client.

    Returns:
        ClassificationResult with mode from LLM or hybrid fallback.
    """
    prompt = LLM_CLASSIFICATION_PROMPT.format(query=query)

    try:
        response = await client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=50,
            messages=[{"role": "user", "content": prompt}],
            timeout=10.0,
        )
        raw_text = response.content[0].text.strip()
        data = json.loads(raw_text)

        mode_str = data.get("mode", "hybrid")
        confidence = float(data.get("confidence", 0.5))

        # Validate mode string maps to a known enum value
        mode = RetrievalMode(mode_str)

        return ClassificationResult(
            mode=mode,
            confidence=confidence,
            method="llm",
        )
    except (json.JSONDecodeError, ValueError, KeyError, IndexError):
        logger.warning("llm_classification_parse_failed", query=query[:100])
        return ClassificationResult(
            mode=RetrievalMode.HYBRID,
            confidence=0.5,
            method="llm",
        )
    except Exception:
        logger.warning(
            "llm_classification_failed", query=query[:100], exc_info=True
        )
        return ClassificationResult(
            mode=RetrievalMode.HYBRID,
            confidence=0.5,
            method="llm",
        )
