"""Alias resolution and query expansion using glossary terms."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from uuid import UUID

    from pam.glossary.store import GlossaryStore

logger = structlog.get_logger()


@dataclass
class ResolvedQuery:
    """Result of alias resolution."""

    original_query: str
    expanded_query: str
    resolved_terms: list[dict] = field(default_factory=list)


class AliasResolver:
    """Resolves aliases in user queries to canonical glossary terms.

    Strategy:
    1. Tokenize query into candidate words/phrases
    2. For each candidate, search glossary aliases (keyword match)
    3. If a match is found with score above threshold, note the expansion
    4. Return the expanded query with resolved terms appended
    """

    def __init__(
        self,
        store: GlossaryStore,
        min_score: float = 3.0,
        project_id: UUID | None = None,
    ) -> None:
        self._store = store
        self._min_score = min_score
        self._project_id = project_id

    async def resolve(
        self,
        query: str,
        project_id: UUID | None = None,
    ) -> ResolvedQuery:
        """Resolve aliases in a query string to canonical terms.

        Extracts candidate tokens from the query, searches each against
        the glossary, and appends canonical expansions.
        """
        pid = project_id or self._project_id
        candidates = self._extract_candidates(query)

        if not candidates:
            return ResolvedQuery(original_query=query, expanded_query=query)

        resolved_terms: list[dict] = []
        seen_canonicals: set[str] = set()

        for candidate in candidates:
            hits = await self._store.search_by_alias(
                alias=candidate,
                project_id=pid,
                top_k=1,
            )
            if not hits:
                continue

            hit = hits[0]
            if hit["score"] < self._min_score:
                continue

            canonical = hit["canonical"]
            if canonical.lower() in seen_canonicals:
                continue

            # Verify the candidate actually matches an alias or canonical
            all_names = [canonical.lower()] + [a.lower() for a in hit.get("aliases", [])]
            if candidate.lower() not in all_names:
                continue

            seen_canonicals.add(canonical.lower())
            resolved_terms.append({
                "matched": candidate,
                "canonical": canonical,
                "definition": hit.get("definition", ""),
                "category": hit.get("category", ""),
            })

        if not resolved_terms:
            return ResolvedQuery(original_query=query, expanded_query=query)

        # Build expanded query: original + glossary context
        expansions = []
        for rt in resolved_terms:
            if rt["matched"].lower() != rt["canonical"].lower():
                expansions.append(f'{rt["matched"]} (= {rt["canonical"]})')

        expanded = query
        if expansions:
            expanded = f"{query} [Glossary: {'; '.join(expansions)}]"

        logger.info(
            "alias_resolved",
            original=query[:100],
            resolved_count=len(resolved_terms),
        )

        return ResolvedQuery(
            original_query=query,
            expanded_query=expanded,
            resolved_terms=resolved_terms,
        )

    def _extract_candidates(self, query: str) -> list[str]:
        """Extract candidate tokens that might be aliases.

        Focuses on:
        - Quoted terms
        - Uppercase abbreviations (GBs, EMEA)
        - Individual words (filtered by length and stop words)
        """
        candidates: list[str] = []
        seen: set[str] = set()

        def _add(token: str) -> None:
            t = token.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                candidates.append(t)

        # Quoted terms: "Gross Bookings"
        for match in re.finditer(r'"([^"]+)"', query):
            _add(match.group(1))

        # Uppercase abbreviations: GBs, EMEA, US&C
        for match in re.finditer(r'\b[A-Z][A-Z&]+[a-z]?\b', query):
            _add(match.group())

        # Individual words (3+ chars, not stop words)
        stop_words = {
            "the", "what", "how", "why", "who", "when", "where",
            "is", "are", "was", "were", "and", "for", "our",
            "last", "this", "that", "with", "from", "have", "has",
        }
        for word in re.findall(r'\b\w+\b', query):
            if len(word) >= 3 and word.lower() not in stop_words:
                _add(word)

        return candidates
