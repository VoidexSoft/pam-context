"""Graph routes -- Neo4j / Graphiti status and diagnostics."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends

from pam.api.deps import get_graph_service
from pam.graph.service import GraphitiService

logger = structlog.get_logger()

router = APIRouter()


@router.get("/graph/status")
async def graph_status(
    graph_service: GraphitiService = Depends(get_graph_service),
):
    """Return Neo4j connection status, entity counts, and last sync time.

    Always returns HTTP 200 -- the ``status`` field indicates whether the
    graph database is reachable (``connected`` vs ``disconnected``).
    """
    try:
        async with graph_service.client.driver.session() as session:
            # Entity counts by label
            result = await session.run(
                "MATCH (n:Entity) RETURN labels(n) AS labels, count(n) AS count"
            )
            records = await result.data()
            entity_counts: dict[str, int] = {}
            total_entities = 0
            for record in records:
                count = record["count"]
                total_entities += count
                for label in record["labels"]:
                    if label != "Entity":
                        entity_counts[label] = entity_counts.get(label, 0) + count

            # Last sync time
            result = await session.run(
                "MATCH (e:Episodic) RETURN max(e.created_at) AS last_sync"
            )
            sync_record = await result.single()
            last_sync_time = None
            if sync_record and sync_record["last_sync"]:
                last_sync_time = str(sync_record["last_sync"])

        return {
            "status": "connected",
            "entity_counts": entity_counts,
            "total_entities": total_entities,
            "last_sync_time": last_sync_time,
        }
    except Exception as exc:
        logger.warning("graph_status_failed", error=str(exc))
        return {"status": "disconnected", "error": str(exc)}
