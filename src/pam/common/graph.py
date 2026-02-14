"""Async Neo4j driver wrapper with connection pool management."""

from __future__ import annotations

from typing import Any

import structlog
from neo4j import AsyncGraphDatabase, AsyncDriver

logger = structlog.get_logger(__name__)


class GraphClient:
    """Async wrapper around the Neo4j driver for graph operations."""

    def __init__(self, uri: str, user: str, password: str, database: str = "neo4j") -> None:
        self._uri = uri
        self._user = user
        self._password = password
        self._database = database
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        """Initialize the Neo4j driver and verify connectivity."""
        self._driver = AsyncGraphDatabase.driver(self._uri, auth=(self._user, self._password))
        await self._driver.verify_connectivity()
        logger.info("neo4j_connected", uri=self._uri, database=self._database)

    async def close(self) -> None:
        """Close the driver and release all connections."""
        if self._driver:
            await self._driver.close()
            self._driver = None
            logger.info("neo4j_disconnected")

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            raise RuntimeError("GraphClient is not connected. Call connect() first.")
        return self._driver

    async def execute_read(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read transaction and return results as list of dicts."""
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def execute_write(self, query: str, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a write transaction and return results as list of dicts."""
        async with self.driver.session(database=self._database) as session:
            result = await session.run(query, parameters or {})
            records = await result.data()
            return records

    async def health_check(self) -> bool:
        """Return True if Neo4j is reachable and the database is available."""
        try:
            await self.execute_read("RETURN 1 AS ok")
            return True
        except Exception:
            logger.warning("neo4j_health_check_failed", exc_info=True)
            return False
