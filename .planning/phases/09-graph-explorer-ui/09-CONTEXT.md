# Phase 9: Graph Explorer UI - Context

**Gathered:** 2026-02-21
**Status:** Ready for planning

<domain>
## Phase Boundary

Visual knowledge graph explorer as a dedicated full page. Users can browse entity neighborhoods via NVL, inspect entity details and temporal history in a fixed sidebar, see post-ingestion graph diffs, and navigate to entities from chat responses. The feature is gated behind `VITE_GRAPH_ENABLED`. This phase does NOT add new graph data capabilities — it visualizes what Phases 6-8 already provide.

</domain>

<decisions>
## Implementation Decisions

### Graph panel layout
- Dedicated full page at `/graph/explore` — separate from the existing `/graph` status page
- Layout: NVL canvas takes ~2/3 of page width, fixed right sidebar always visible
- Sidebar sections: search bar at top, entity details in middle, temporal history at bottom
- Zoom/pan controls on the canvas (bottom-left)
- Entry points: navigation bar tab + clickable entity names in chat responses that deep-link to the explorer

### Node interaction
- Click a node: shows details in sidebar (properties card, relationship list, temporal history, source documents)
- Progressive disclosure for neighbors: click shows details only, double-click (or explicit expand button) loads 1-hop neighbors onto canvas
- Node styling: color by entity type, size by connection count (heavily-connected entities appear larger)
- Edge labels (relationship types like 'Leads', 'Uses') always visible on the canvas

### Ingestion preview
- Shown on the graph explorer page, not the admin page
- Scoped per-ingestion run — tracks which entities/edges were created, changed, or invalidated in a specific run
- Detail level: entity-level list with field-level changes (e.g., "Data Platform Team: relationship to Alex Chen changed from Leads to Led")
- Color coding on canvas: green for added, yellow for changed, red for invalidated
- Toggle between filtered subgraph (only affected nodes) and full graph with highlights — default to filtered

### Empty & loading states
- Feature flag off (`VITE_GRAPH_ENABLED=false`): nav tab shows "Graph (Coming Soon)" in muted style, route exists but shows "Graph features not enabled" message
- Graph enabled but zero entities: friendly illustration + message "No graph data yet. Ingest some documents to build the knowledge graph." with link to ingestion page
- Sparse graph (few nodes): no special handling — same layout as full graph
- Loading state: full page centered spinner until initial graph data loads

### Claude's Discretion
- NVL force-directed layout configuration and physics tuning
- Exact color palette for entity types
- Sidebar responsive breakpoints
- Search input debounce and result ranking
- Canvas animation transitions

</decisions>

<specifics>
## Specific Ideas

- Entity names in chat responses should be clickable links that navigate to `/graph/explore?entity={uuid}` and auto-focus that node
- The ingestion diff sidebar should list changes grouped by type: "Added", "Changed", "Invalidated" sections
- The mockup layout chosen: canvas (2/3) + fixed sidebar (1/3) with search, details, and history sections stacked vertically

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 09-graph-explorer-ui*
*Context gathered: 2026-02-21*
