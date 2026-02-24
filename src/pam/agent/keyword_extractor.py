"""Dual-level keyword extraction for smart search (LightRAG-inspired).

Extracts high-level (theme/concept) and low-level (entity/term) keywords
from a user query via a lightweight Claude call, enabling targeted routing
to document search (ES) and knowledge graph search (Graphiti).
"""

import json
from dataclasses import dataclass

import structlog
from anthropic import AsyncAnthropic

logger = structlog.get_logger()

KEYWORD_EXTRACTION_PROMPT = """\
You are a keyword extractor for a RAG system. Given a user query, extract:
- high_level_keywords: overarching themes, concepts, or relationship types
- low_level_keywords: specific entities, proper nouns, technical terms

Output a JSON object with exactly two keys: "high_level_keywords" and \
"low_level_keywords", each an array of strings. Output JSON only.

Examples:
Query: "What services depend on the authentication module?"
{{"high_level_keywords": ["service dependencies", "system architecture"], \
"low_level_keywords": ["authentication module"]}}

Query: "How has the deployment process changed since January?"
{{"high_level_keywords": ["process evolution", "deployment changes"], \
"low_level_keywords": ["deployment process", "January"]}}

Query: "What is the conversion rate formula?"
{{"high_level_keywords": ["metric definition", "business analytics"], \
"low_level_keywords": ["conversion rate", "formula"]}}

Query: "{query}"
"""


@dataclass
class QueryKeywords:
    """Dual-level keywords extracted from a user query."""

    high_level_keywords: list[str]
    low_level_keywords: list[str]


async def extract_query_keywords(
    client: AsyncAnthropic,
    query: str,
    model: str = "claude-3-5-haiku-20241022",
    timeout: float = 15.0,
) -> QueryKeywords:
    """Extract dual-level keywords from a user query via Claude.

    Uses a lightweight Claude call (~50 output tokens) to classify the query
    into high-level (theme) and low-level (entity) keywords for routing to
    appropriate search backends.

    Args:
        client: Anthropic async client.
        query: The user's natural language query.
        model: Model to use for extraction (default: Haiku for speed/cost).
        timeout: Request timeout in seconds.

    Returns:
        QueryKeywords with high_level_keywords and low_level_keywords lists.

    Raises:
        json.JSONDecodeError: If the model response is not valid JSON.
        KeyError: If the parsed JSON is missing expected structure.
        IndexError: If the response content is empty.
    """
    prompt = KEYWORD_EXTRACTION_PROMPT.format(query=query)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=100,
            messages=[{"role": "user", "content": prompt}],
            timeout=timeout,
        )
        raw_text = response.content[0].text.strip()
        data = json.loads(raw_text)
        return QueryKeywords(
            high_level_keywords=data.get("high_level_keywords", []),
            low_level_keywords=data.get("low_level_keywords", []),
        )
    except (json.JSONDecodeError, KeyError, IndexError):
        logger.warning("keyword_extraction_parse_failed", query=query[:100])
        raise
    except Exception:
        logger.warning("keyword_extraction_failed", query=query[:100], exc_info=True)
        raise
