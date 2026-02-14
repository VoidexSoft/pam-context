"""Graph schema definition and initialization for Neo4j.

Defines node types, relationship types, uniqueness constraints, and indexes.
Schema initialization is idempotent — safe to run on every startup.
"""

from __future__ import annotations

import structlog

from pam.common.graph import GraphClient

logger = structlog.get_logger(__name__)

# --- Uniqueness Constraints ---
# Each constraint uses CREATE ... IF NOT EXISTS for idempotency.

CONSTRAINTS: list[str] = [
    "CREATE CONSTRAINT metric_name IF NOT EXISTS FOR (m:Metric) REQUIRE m.name IS UNIQUE",
    "CREATE CONSTRAINT event_name IF NOT EXISTS FOR (e:Event) REQUIRE e.name IS UNIQUE",
    "CREATE CONSTRAINT document_id IF NOT EXISTS FOR (d:Document) REQUIRE d.id IS UNIQUE",
    "CREATE CONSTRAINT team_name IF NOT EXISTS FOR (t:Team) REQUIRE t.name IS UNIQUE",
    "CREATE CONSTRAINT datasource_name IF NOT EXISTS FOR (ds:DataSource) REQUIRE ds.name IS UNIQUE",
    "CREATE CONSTRAINT kpi_key IF NOT EXISTS FOR (k:KPI) REQUIRE (k.metric, k.period) IS UNIQUE",
]

# --- Indexes for query performance ---
INDEXES: list[str] = [
    "CREATE INDEX metric_owner IF NOT EXISTS FOR (m:Metric) ON (m.owner)",
    "CREATE INDEX kpi_owner IF NOT EXISTS FOR (k:KPI) ON (k.owner)",
    "CREATE INDEX metric_confidence IF NOT EXISTS FOR (m:Metric) ON (m.confidence)",
    "CREATE INDEX event_confidence IF NOT EXISTS FOR (e:Event) ON (e.confidence)",
]


async def initialize_schema(client: GraphClient) -> None:
    """Create all constraints and indexes. Idempotent — safe to call on every startup."""
    for stmt in CONSTRAINTS:
        await client.execute_write(stmt)
    for stmt in INDEXES:
        await client.execute_write(stmt)
    logger.info("graph_schema_initialized", constraints=len(CONSTRAINTS), indexes=len(INDEXES))


async def drop_schema(client: GraphClient) -> None:
    """Drop all constraints and indexes. Useful for testing teardown."""
    # Fetch and drop all constraints
    constraints = await client.execute_read("SHOW CONSTRAINTS YIELD name RETURN name")
    for c in constraints:
        await client.execute_write(f"DROP CONSTRAINT {c['name']} IF EXISTS")

    # Fetch and drop all indexes (skip lookup indexes which can't be dropped)
    indexes = await client.execute_read(
        "SHOW INDEXES YIELD name, type WHERE type <> 'LOOKUP' RETURN name"
    )
    for idx in indexes:
        await client.execute_write(f"DROP INDEX {idx['name']} IF EXISTS")

    logger.info("graph_schema_dropped")


async def clear_graph(client: GraphClient) -> None:
    """Delete all nodes and relationships. Useful for testing."""
    await client.execute_write("MATCH (n) DETACH DELETE n")
    logger.info("graph_cleared")
