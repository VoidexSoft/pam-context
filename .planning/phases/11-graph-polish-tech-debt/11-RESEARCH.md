# Phase 11: Graph Polish + Tech Debt Cleanup - Research

**Researched:** 2026-02-23
**Domain:** Frontend UX polish, backend API hardening, lint fixes, documentation standardization
**Confidence:** HIGH

## Summary

This phase is a cleanup phase with four discrete, low-risk items identified by the v2.0 milestone audit. No new capabilities are introduced. The work divides into: (1) a frontend empty state enhancement requiring a backend API extension to distinguish "no documents" from "graph indexing pending," (2) explicit null guards on graph REST endpoints, (3) a one-line ruff B904 lint fix, and (4) SUMMARY.md frontmatter standardization across 11 files.

The most complex item is VIZ-06 (empty state), which requires the `/graph/status` backend endpoint to return PG document counts alongside Neo4j entity counts so the frontend can differentiate empty states. The remaining items are surgical edits.

**Primary recommendation:** Extend `/graph/status` to return `document_count` and `graph_synced_count` from PostgreSQL, then update the frontend `useGraphExplorer` hook and `GraphExplorerPage` to render two distinct empty states based on these values.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- Empty state design: Icon + message treatment with relevant icon above centered status text
- "Indexing in progress" state: Show document count pending graph sync (e.g., "5 documents awaiting graph indexing") using existing `graph_synced` data
- "No documents" state: Include a clickable link/button that navigates to the ingest page to reduce friction for new users
- Use the same color palette as the rest of the graph explorer -- consistent with active content styling, not muted
- Graph nav item always visible even when Neo4j is unavailable -- user clicks and sees unavailable message
- API endpoints return 503 with JSON body: `{"detail": "Graph service unavailable"}` -- structured error the frontend can parse
- Manual refresh only -- no auto-retry or polling. User refreshes page to check if service is back
- `requirements_completed` field uses ID + short description pairs format in YAML
- Plans with no requirement mapping use empty list: `requirements_completed: []`
- Description is a short 5-10 word summary, not full requirement text

### Claude's Discretion
- Exact icon choices for empty states
- Frontend error display pattern when graph service is unavailable (banner vs inline message)
- Placement of `requirements_completed` field within existing SUMMARY.md frontmatter structure
- Loading skeleton or transition animations
- Frontend display approach for unavailable state: Claude's discretion based on existing error patterns

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VIZ-06 | "Graph indexing in progress" state when graph_synced count is 0 | Backend: extend `/graph/status` with `document_count` + `graph_synced_count` from PG. Frontend: two-branch empty state in GraphExplorerPage based on these values. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| React 18 | 18.x | Frontend UI (existing) | Already installed |
| FastAPI | existing | Backend API (existing) | Already installed |
| SQLAlchemy | existing | PG queries for doc counts (existing) | Already installed |
| Tailwind CSS | existing | Styling (existing) | Already installed |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| react-router-dom | existing | `<Link>` for navigate-to-ingest button | Already used in empty state |
| structlog | existing | Logging in graph routes | Already imported |

No new dependencies needed. All work uses the existing stack.

## Architecture Patterns

### Pattern 1: Extend /graph/status with PG Document Counts

**What:** Add `document_count` and `graph_synced_count` fields to the `/graph/status` response by querying PostgreSQL alongside Neo4j.

**When to use:** The `useGraphExplorer` hook already calls `getGraphStatus()` on mount. Adding document counts to this single endpoint avoids an extra API round-trip.

**Current response shape:**
```python
# src/pam/api/routes/graph.py — graph_status endpoint
return {
    "status": "connected",
    "entity_counts": entity_counts,
    "total_entities": total_entities,
    "last_sync_time": last_sync_time,
}
```

**Target response shape (extend, don't break):**
```python
return {
    "status": "connected",
    "entity_counts": entity_counts,
    "total_entities": total_entities,
    "last_sync_time": last_sync_time,
    "document_count": total_doc_count,          # NEW: from PG
    "graph_synced_count": graph_synced_count,    # NEW: from PG
}
```

**Implementation approach:** The `graph_status` endpoint needs a `db: AsyncSession = Depends(get_db)` parameter added. Two simple PG queries:
```python
# Total documents
total_doc_result = await db.execute(select(func.count()).select_from(Document))
total_doc_count = total_doc_result.scalar() or 0

# Graph synced documents
synced_result = await db.execute(
    select(func.count()).select_from(Document).where(Document.graph_synced == True)  # noqa: E712
)
graph_synced_count = synced_result.scalar() or 0
```

**Confidence:** HIGH -- this follows the exact same pattern already used in the `/stats` endpoint (`documents.py:142`).

### Pattern 2: Two-Branch Empty State in GraphExplorerPage

**What:** Replace the single empty state in `GraphExplorerPage.tsx` with conditional rendering based on document counts.

**Current behavior (lines 123-166 of GraphExplorerPage.tsx):**
```tsx
if (entityCount === 0) {
    // Shows: "No graph data yet" + "Ingest some documents" + Link to /admin
}
```

**Target behavior:**
```tsx
// When no documents exist at all:
// Icon + "No documents ingested" + "Ingest documents to build the knowledge graph" + Link to /ingest or /admin

// When documents exist but graph_synced_count is 0:
// Icon + "Graph indexing in progress" + "N documents awaiting graph indexing" + no action link (just wait)
```

**Data flow:**
1. `useGraphExplorer` hook calls `getGraphStatus()` (already does this)
2. Extract `document_count` and `graph_synced_count` from response (new fields)
3. Store in hook state alongside existing `entityCount`
4. `GraphExplorerPage` renders the appropriate empty state branch

**Confidence:** HIGH -- the hook already stores `entityCount` from this same API call.

### Pattern 3: Explicit Null Guard on Graph REST Endpoints

**What:** Add `if graph_service is None` check at the top of each graph endpoint handler before attempting Neo4j operations.

**Current pattern (sync-graph in ingest.py already has this):**
```python
if graph_service is None:
    raise HTTPException(status_code=503, detail="Graph service not available")
```

**Current graph.py behavior:** All four endpoints (`graph_status`, `graph_neighborhood`, `graph_entities`, `entity_history`) receive `graph_service` via `Depends(get_graph_service)`, which returns `cast(GraphitiService, None)` when Neo4j is unavailable. They handle failure via outer `try/except Exception` which catches the resulting `AttributeError` when calling methods on `None`. This works but is fragile -- the error message is an opaque Python exception rather than a clean 503.

**Target:** Each endpoint gets an explicit guard:
```python
if graph_service is None:
    raise HTTPException(status_code=503, detail="Graph service unavailable")
```

The user decision specifies the JSON body format: `{"detail": "Graph service unavailable"}`.

Note: `graph_status` is special -- it currently returns `{"status": "disconnected", "error": "..."}` with 200 status. Per the user decision (API endpoints return 503), this should be made consistent, BUT the `graph_status` endpoint also serves as a health probe. The null guard should be added before the Neo4j query, but the endpoint can still catch Neo4j connection failures gracefully with 200. The null guard only fires when `get_graph_service()` returns None (no graph_service at startup).

**IMPORTANT NUANCE for graph_status:** When `graph_service is None`, the endpoint should still return document counts (from PG) alongside the 503 or return a degraded 200 response with `"status": "disconnected"`. The frontend needs document counts regardless. Two options:
- Option A: Return 503 like other endpoints when graph_service is None (consistent with user decision)
- Option B: Return 200 with `"status": "unavailable"` and include document_count + graph_synced_count=0

Recommendation: Use Option B for `graph_status` specifically because the frontend needs document counts even when Neo4j is down (to show the right empty state). The other three endpoints should use Option A (503).

**Confidence:** HIGH -- follows existing pattern in sync-graph endpoint.

### Pattern 4: Ruff B904 Fix

**What:** Fix `raise HTTPException(...)` without `from err` in `ingest.py:121`.

**Current code (line 120-121):**
```python
except (ValueError, KeyError):
    raise HTTPException(status_code=400, detail="Invalid cursor")
```

**Fix:**
```python
except (ValueError, KeyError) as err:
    raise HTTPException(status_code=400, detail="Invalid cursor") from err
```

**Confidence:** HIGH -- mechanical one-line fix.

### Pattern 5: SUMMARY.md Frontmatter Update

**What:** Replace `requirements-completed: [REQ-01, REQ-02]` with structured `requirements_completed` field across all 11 SUMMARY.md files.

**Current format (all 11 files):**
```yaml
requirements-completed: [INFRA-01, INFRA-02, INFRA-05]
```

**Target format (per user decision):**
```yaml
requirements_completed:
  - id: INFRA-01
    desc: Neo4j running in Docker
  - id: INFRA-02
    desc: graphiti-core installed with Anthropic LLM
  - id: INFRA-05
    desc: Entity type taxonomy as Pydantic models
```

**Files to update (11 total):**
1. `.planning/phases/06-neo4j-graphiti-infrastructure/06-01-SUMMARY.md` -- [INFRA-01, INFRA-02, INFRA-05]
2. `.planning/phases/06-neo4j-graphiti-infrastructure/06-02-SUMMARY.md` -- [INFRA-03, INFRA-04]
3. `.planning/phases/06-neo4j-graphiti-infrastructure/06-03-SUMMARY.md` -- [INFRA-06]
4. `.planning/phases/07-ingestion-pipeline-extension-diff-engine/07-01-SUMMARY.md` -- [EXTRACT-01, EXTRACT-02, EXTRACT-03, EXTRACT-06, DIFF-01, DIFF-02]
5. `.planning/phases/07-ingestion-pipeline-extension-diff-engine/07-02-SUMMARY.md` -- [EXTRACT-04, EXTRACT-05, DIFF-03]
6. `.planning/phases/08-agent-graph-tool-rest-graph-endpoints/08-01-SUMMARY.md` -- [GRAPH-01, GRAPH-02, GRAPH-03, GRAPH-06]
7. `.planning/phases/08-agent-graph-tool-rest-graph-endpoints/08-02-SUMMARY.md` -- [GRAPH-04, GRAPH-05, GRAPH-06]
8. `.planning/phases/09-graph-explorer-ui/09-01-SUMMARY.md` -- [VIZ-03, VIZ-04]
9. `.planning/phases/09-graph-explorer-ui/09-02-SUMMARY.md` -- [VIZ-01, VIZ-02, VIZ-03, VIZ-05, VIZ-06]
10. `.planning/phases/09-graph-explorer-ui/09-03-SUMMARY.md` -- [VIZ-04]
11. `.planning/phases/10-bitemporal-timestamp-fix/10-01-SUMMARY.md` -- [EXTRACT-02]

**Requirement descriptions (sourced from REQUIREMENTS.md):**

| ID | Short Description (5-10 words) |
|----|-------------------------------|
| INFRA-01 | Neo4j running in Docker with health check |
| INFRA-02 | graphiti-core installed with Anthropic LLM |
| INFRA-03 | GraphitiService singleton on app.state |
| INFRA-04 | get_graph_service dependency in deps.py |
| INFRA-05 | Entity type taxonomy as Pydantic models |
| INFRA-06 | NVL React packages installed in web/ |
| EXTRACT-01 | Pipeline calls add_episode per segment |
| EXTRACT-02 | Bi-temporal timestamps from document modified_at |
| EXTRACT-03 | graph_synced column via Alembic migration |
| EXTRACT-04 | Graph extraction as non-blocking background step |
| EXTRACT-05 | sync-graph endpoint retries failed extractions |
| EXTRACT-06 | Orphan prevention via episode tombstoning |
| DIFF-01 | Entity-level change detection on re-ingestion |
| DIFF-02 | Superseded edges get t_invalid set |
| DIFF-03 | Diff summaries in SyncLog.details JSON |
| GRAPH-01 | search_knowledge_graph agent tool |
| GRAPH-02 | get_entity_history agent tool |
| GRAPH-03 | Point-in-time graph query via reference_time |
| GRAPH-04 | GET /graph/neighborhood endpoint |
| GRAPH-05 | GET /graph/entities endpoint |
| GRAPH-06 | Tool result capped at 3000 chars / 20 nodes |
| VIZ-01 | Graph explorer with NVL as collapsible panel |
| VIZ-02 | Entity click expands detail panel |
| VIZ-03 | Temporal timeline for edge history |
| VIZ-04 | Ingestion graph preview with diff overlay |
| VIZ-05 | VITE_GRAPH_ENABLED feature flag |
| VIZ-06 | Graph indexing in progress empty state |

**Confidence:** HIGH -- mechanical text replacement with clear source data.

### Anti-Patterns to Avoid
- **Fetching document counts from a second API call in the frontend:** The `useGraphExplorer` hook already calls `getGraphStatus()`. Extend that single endpoint rather than adding another round-trip.
- **Using `getattr(app.state, "graph_service", None)` in graph endpoints:** The existing DI pattern uses `Depends(get_graph_service)`. Keep using DI but add the null guard inside the handler.
- **Auto-retry/polling for graph availability:** User explicitly decided against this. Manual refresh only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Document count queries | Custom SQL strings | SQLAlchemy `func.count()` + `select_from()` | Already established pattern in `/stats` endpoint |
| Frontend conditional rendering | Complex state machine | Simple `if/else` branches on `documentCount` / `graphSyncedCount` | Two states, simple conditions |

**Key insight:** This is a cleanup phase. Every change maps to an existing pattern already in the codebase. No novel solutions needed.

## Common Pitfalls

### Pitfall 1: Breaking graph_status for Frontend Consumers
**What goes wrong:** Changing the response shape of `/graph/status` breaks the frontend `GraphStatus` TypeScript interface and both consumers (`GraphPage.tsx`, `useGraphExplorer.ts`).
**Why it happens:** The frontend interface is manually maintained alongside the backend response dict.
**How to avoid:** Add new fields to the response (backward compatible). Update the `GraphStatus` TypeScript interface in `web/src/api/client.ts`. Both consumers need updating.
**Warning signs:** TypeScript compilation errors after backend changes.

### Pitfall 2: Null Guard Breaking graph_status Health Probe
**What goes wrong:** Adding a 503 null guard to `graph_status` prevents the frontend from getting document counts when Neo4j is down, making it impossible to render the correct empty state.
**Why it happens:** `graph_status` serves dual purpose: health probe AND data provider.
**How to avoid:** Handle `graph_service is None` in `graph_status` as a degraded 200 response with `"status": "unavailable"` and document counts from PG, NOT as a 503. Only the three data endpoints (neighborhood, entities, history) should return 503.
**Warning signs:** Frontend shows generic error instead of empty state when Neo4j is down.

### Pitfall 3: graph_status Endpoint Signature Change Requires DI Update
**What goes wrong:** Adding `db: AsyncSession = Depends(get_db)` to `graph_status` changes its function signature. If the endpoint already works via outer try/except with no db parameter, the new dependency injection must be added correctly.
**Why it happens:** Extending an existing endpoint signature.
**How to avoid:** Simply add the `db` parameter with `Depends(get_db)`. FastAPI handles DI automatically. Test that the endpoint still works when Neo4j is down (the PG query should succeed independently).
**Warning signs:** 500 error on `/graph/status` after the change.

### Pitfall 4: YAML Frontmatter Indentation in SUMMARY.md
**What goes wrong:** Multi-line YAML sequences with nested maps require correct indentation. Bad indentation breaks YAML parsing.
**Why it happens:** YAML is whitespace-sensitive.
**How to avoid:** Use consistent 2-space indentation. Validate that the frontmatter parses correctly. The `---` delimiters must remain on their own lines.
**Warning signs:** YAML parse errors when reading SUMMARY files.

### Pitfall 5: Missing `from err` Pattern Elsewhere
**What goes wrong:** Fixing only the known B904 at `ingest.py:121` but missing other instances.
**Why it happens:** The audit identified this specific line, but there could be others.
**How to avoid:** Run `ruff check --select B904` across the codebase to find all instances.
**Warning signs:** Ruff still reports B904 after the fix.

## Code Examples

### Empty State Branch Logic (Frontend)
```tsx
// In GraphExplorerPage.tsx -- replacing the current single empty state
if (entityCount === 0) {
    if (documentCount === 0) {
        // "No documents ingested" state
        // Icon + "No documents ingested"
        // "Ingest documents to build the knowledge graph"
        // <Link to="/admin">Go to Ingest</Link>
    } else {
        // "Graph indexing in progress" state
        // Icon + "Graph indexing in progress"
        // "N documents awaiting graph indexing"
        // No action button (user waits for sync)
    }
}
```

### Null Guard Pattern (Backend)
```python
# At the top of each graph endpoint handler (neighborhood, entities, history)
@router.get("/graph/neighborhood/{entity_name:path}", response_model=NeighborhoodResponse)
async def graph_neighborhood(
    entity_name: str,
    graph_service: GraphitiService = Depends(get_graph_service),
) -> NeighborhoodResponse:
    if graph_service is None:
        raise HTTPException(status_code=503, detail="Graph service unavailable")
    # ... existing logic
```

### graph_status with PG Counts (Backend)
```python
@router.get("/graph/status")
async def graph_status(
    db: AsyncSession = Depends(get_db),  # NEW
    graph_service: GraphitiService = Depends(get_graph_service),
):
    # Always query PG for document counts (works even without Neo4j)
    total_doc_result = await db.execute(select(func.count()).select_from(Document))
    document_count = total_doc_result.scalar() or 0
    synced_result = await db.execute(
        select(func.count()).select_from(Document).where(Document.graph_synced == True)
    )
    graph_synced_count = synced_result.scalar() or 0

    if graph_service is None:
        return {
            "status": "unavailable",
            "entity_counts": {},
            "total_entities": 0,
            "last_sync_time": None,
            "document_count": document_count,
            "graph_synced_count": graph_synced_count,
        }

    # ... existing Neo4j query logic, adding document_count and graph_synced_count to return
```

### Ruff B904 Fix
```python
# Before (ingest.py:120-121)
except (ValueError, KeyError):
    raise HTTPException(status_code=400, detail="Invalid cursor")

# After
except (ValueError, KeyError) as err:
    raise HTTPException(status_code=400, detail="Invalid cursor") from err
```

### SUMMARY.md Frontmatter Update
```yaml
# Before
requirements-completed: [INFRA-01, INFRA-02, INFRA-05]

# After
requirements_completed:
  - id: INFRA-01
    desc: Neo4j running in Docker with health check
  - id: INFRA-02
    desc: graphiti-core installed with Anthropic LLM
  - id: INFRA-05
    desc: Entity type taxonomy as Pydantic models
```

## Open Questions

1. **graph_status return code when graph_service is None**
   - What we know: User says "API endpoints return 503" for unavailable state. But graph_status currently returns 200 with `"status": "disconnected"` for Neo4j connection failures, and the frontend needs document counts regardless.
   - What's unclear: Should graph_status specifically return 200 (degraded) or 503 when graph_service is None?
   - Recommendation: Return 200 with `"status": "unavailable"` for graph_status (it's a status endpoint, degraded responses are idiomatic). Return 503 for the three data endpoints. This preserves the frontend's ability to read document counts.

2. **VIZ-06 wording for "indexing in progress" when docs exist but graph entities also exist (partial sync)**
   - What we know: The condition `entityCount === 0` means Neo4j has zero entities. But documents might have `graph_synced = True` in PG (entities were created then Neo4j was rebuilt).
   - What's unclear: This edge case is unlikely in practice but technically possible.
   - Recommendation: Use the simple condition: `entityCount === 0 && documentCount > 0` means show "indexing in progress." If Neo4j has entities, the normal explorer view shows regardless of graph_synced counts.

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `src/pam/api/routes/graph.py` -- current graph endpoint implementation
- Codebase inspection: `src/pam/api/routes/ingest.py` -- sync-graph null guard pattern, B904 line
- Codebase inspection: `src/pam/api/routes/documents.py` -- `/stats` endpoint PG count pattern
- Codebase inspection: `web/src/pages/GraphExplorerPage.tsx` -- current empty state rendering
- Codebase inspection: `web/src/hooks/useGraphExplorer.ts` -- hook state management
- Codebase inspection: `web/src/api/client.ts` -- GraphStatus TypeScript interface
- Codebase inspection: `src/pam/api/deps.py` -- get_graph_service DI function
- Codebase inspection: `src/pam/api/main.py` -- lifespan graph_service initialization
- Codebase inspection: All 11 SUMMARY.md files -- current frontmatter structure

### Secondary (MEDIUM confidence)
- `.planning/v2.0-MILESTONE-AUDIT.md` -- tech debt item descriptions and rationale
- `.planning/REQUIREMENTS.md` -- requirement descriptions for frontmatter updates

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- no new libraries, all existing
- Architecture: HIGH -- all patterns already established in codebase
- Pitfalls: HIGH -- identified from direct code inspection
- VIZ-06 implementation: HIGH -- clear data flow from backend to frontend

**Research date:** 2026-02-23
**Valid until:** 2026-03-23 (stable, no external dependency changes)
