"""Redis cache layer for search results, segments, and conversation sessions."""

import hashlib
import json
from datetime import datetime
from typing import Any

import redis.asyncio as redis
import structlog

logger = structlog.get_logger()


async def ping_redis(client: redis.Redis | None) -> bool:
    """Check if Redis is reachable."""
    if client is None:
        return False
    try:
        return bool(await client.ping())  # type: ignore[misc]
    except Exception:
        return False


def _make_search_key(
    query: str,
    top_k: int,
    source_type: str | None,
    project: str | None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> str:
    """Build a deterministic cache key for a search query."""
    raw = json.dumps(
        {
            "q": query,
            "k": top_k,
            "st": source_type,
            "p": project,
            "df": date_from.isoformat() if date_from else None,
            "dt": date_to.isoformat() if date_to else None,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return f"search:{digest}"


class CacheService:
    """Thin wrapper around Redis for PAM-specific caching."""

    def __init__(
        self,
        client: redis.Redis,
        search_ttl: int,
        session_ttl: int,
    ) -> None:
        self.client = client
        self._search_ttl = search_ttl
        self._session_ttl = session_ttl

    @property
    def search_ttl(self) -> int:
        return self._search_ttl

    @property
    def session_ttl(self) -> int:
        return self._session_ttl

    # ------------------------------------------------------------------
    # Search result caching
    # ------------------------------------------------------------------
    async def get_search_results(
        self,
        query: str,
        top_k: int,
        source_type: str | None = None,
        project: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> list[dict[str, Any]] | None:
        key = _make_search_key(query, top_k, source_type, project, date_from, date_to)
        raw = await self.client.get(key)
        if raw is None:
            return None
        logger.debug("cache_hit", key=key)
        result: list[dict[str, Any]] = json.loads(raw)
        return result

    async def set_search_results(
        self,
        query: str,
        top_k: int,
        results: list[dict[str, Any]],
        source_type: str | None = None,
        project: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> None:
        key = _make_search_key(query, top_k, source_type, project, date_from, date_to)
        await self.client.set(key, json.dumps(results, default=str), ex=self.search_ttl)
        logger.debug("cache_set", key=key, ttl=self.search_ttl)

    async def invalidate_search(self) -> int:
        """Invalidate all cached search results (e.g. after ingestion)."""
        keys = [k async for k in self.client.scan_iter(match="search:*")]
        if keys:
            deleted: int = await self.client.delete(*keys)
            return deleted
        return 0

    # ------------------------------------------------------------------
    # Conversation session state
    # ------------------------------------------------------------------
    async def get_session(self, session_id: str) -> list[dict[str, Any]] | None:
        raw = await self.client.get(f"session:{session_id}")
        if raw is None:
            return None
        messages: list[dict[str, Any]] = json.loads(raw)
        return messages

    async def save_session(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        await self.client.set(
            f"session:{session_id}",
            json.dumps(messages, default=str),
            ex=self.session_ttl,
        )

    async def delete_session(self, session_id: str) -> None:
        await self.client.delete(f"session:{session_id}")
