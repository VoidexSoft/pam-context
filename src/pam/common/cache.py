"""Redis cache layer for search results, segments, and conversation sessions."""

import hashlib
import json
from typing import Any

import redis.asyncio as redis
import structlog

from pam.common.config import settings

logger = structlog.get_logger()

_redis_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    """Get or create a shared async Redis client."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def close_redis() -> None:
    """Close the shared Redis client."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def ping_redis() -> bool:
    """Check if Redis is reachable."""
    try:
        client = await get_redis()
        return bool(await client.ping())  # type: ignore[misc]
    except Exception:
        return False


def _make_search_key(query: str, top_k: int, source_type: str | None, project: str | None) -> str:
    """Build a deterministic cache key for a search query."""
    raw = json.dumps(
        {"q": query, "k": top_k, "st": source_type, "p": project},
        sort_keys=True,
    )
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return f"search:{digest}"


class CacheService:
    """Thin wrapper around Redis for PAM-specific caching."""

    def __init__(self, client: redis.Redis) -> None:
        self.client = client

    # ------------------------------------------------------------------
    # Search result caching
    # ------------------------------------------------------------------
    async def get_search_results(
        self, query: str, top_k: int, source_type: str | None = None, project: str | None = None
    ) -> list[dict[str, Any]] | None:
        key = _make_search_key(query, top_k, source_type, project)
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
    ) -> None:
        key = _make_search_key(query, top_k, source_type, project)
        await self.client.set(key, json.dumps(results, default=str), ex=settings.redis_search_ttl)
        logger.debug("cache_set", key=key, ttl=settings.redis_search_ttl)

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
            ex=settings.redis_session_ttl,
        )

    async def delete_session(self, session_id: str) -> None:
        await self.client.delete(f"session:{session_id}")
