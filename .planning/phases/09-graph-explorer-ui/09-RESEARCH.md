# Phase 9: Graph Explorer UI - Research

**Researched:** 2026-02-21
**Domain:** Graph visualization, React component architecture, NVL (Neo4j Visualization Library), temporal UI patterns
**Confidence:** HIGH

## Summary

This phase builds a dedicated graph explorer page at `/graph/explore` using the already-installed @neo4j-nvl packages (v1.1.0). The existing backend provides all necessary graph data through `GET /api/graph/neighborhood/{entity_name}` (1-hop subgraph with nodes + edges) and `GET /api/graph/entities` (paginated entity listing). The missing backend piece is a `GET /api/graph/sync-logs` endpoint to expose SyncLog diff data (added/changed/invalidated entities per ingestion run) for the VIZ-04 ingestion preview requirement.

The NVL library provides `InteractiveNvlWrapper` as the primary React component, which bundles click, drag, zoom, pan, and hover interaction handlers. It accepts `nodes`, `rels`, `mouseEventCallbacks`, `layout` (force-directed or hierarchical), and `nvlOptions` (zoom limits, renderer). The NVL instance supports dynamic graph manipulation via `addAndUpdateElementsInGraph()` and viewport control via `fit()`, `setZoom()`, `setPan()`. Node styling uses `color`, `size`, and `caption` properties; relationship styling uses `color`, `width`, and `caption`.

The frontend architecture follows the existing project pattern: a new page component at `pages/GraphExplorerPage.tsx`, API client functions in `api/client.ts`, and small focused components for the sidebar sections (entity details, temporal history, ingestion diff). The feature flag `VITE_GRAPH_ENABLED` already gates the nav item in `App.tsx`; this phase extends it to gate the new `/graph/explore` route and the chat entity link behavior.

**Primary recommendation:** Use `InteractiveNvlWrapper` with force-directed layout, split the explorer into a canvas component (2/3 width) and a sidebar component (1/3 width) using CSS grid, fetch neighborhood data on-demand via the existing REST endpoint, and add one new backend endpoint for SyncLog retrieval.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Graph panel layout
- Dedicated full page at `/graph/explore` -- separate from the existing `/graph` status page
- Layout: NVL canvas takes ~2/3 of page width, fixed right sidebar always visible
- Sidebar sections: search bar at top, entity details in middle, temporal history at bottom
- Zoom/pan controls on the canvas (bottom-left)
- Entry points: navigation bar tab + clickable entity names in chat responses that deep-link to the explorer

#### Node interaction
- Click a node: shows details in sidebar (properties card, relationship list, temporal history, source documents)
- Progressive disclosure for neighbors: click shows details only, double-click (or explicit expand button) loads 1-hop neighbors onto canvas
- Node styling: color by entity type, size by connection count (heavily-connected entities appear larger)
- Edge labels (relationship types like 'Leads', 'Uses') always visible on the canvas

#### Ingestion preview
- Shown on the graph explorer page, not the admin page
- Scoped per-ingestion run -- tracks which entities/edges were created, changed, or invalidated in a specific run
- Detail level: entity-level list with field-level changes (e.g., "Data Platform Team: relationship to Alex Chen changed from Leads to Led")
- Color coding on canvas: green for added, yellow for changed, red for invalidated
- Toggle between filtered subgraph (only affected nodes) and full graph with highlights -- default to filtered

#### Empty & loading states
- Feature flag off (`VITE_GRAPH_ENABLED=false`): nav tab shows "Graph (Coming Soon)" in muted style, route exists but shows "Graph features not enabled" message
- Graph enabled but zero entities: friendly illustration + message "No graph data yet. Ingest some documents to build the knowledge graph." with link to ingestion page
- Sparse graph (few nodes): no special handling -- same layout as full graph
- Loading state: full page centered spinner until initial graph data loads

### Claude's Discretion
- NVL force-directed layout configuration and physics tuning
- Exact color palette for entity types
- Sidebar responsive breakpoints
- Search input debounce and result ranking
- Canvas animation transitions

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| VIZ-01 | Graph explorer using InteractiveNvlWrapper as collapsible side panel with neighborhood view | InteractiveNvlWrapper API documented: nodes, rels, mouseEventCallbacks, layout='forceDirected', nvlOptions for zoom control. Existing `/api/graph/neighborhood/{entity_name}` endpoint provides node+edge data. Note: CONTEXT.md changed this to full page, not side panel. |
| VIZ-02 | Entity click expands detail panel showing properties, relationships, and temporal history | mouseEventCallbacks.onNodeClick provides clicked Node; sidebar component receives selected entity UUID; backend neighborhood endpoint returns center node with summary + connected edges with valid_at/invalid_at |
| VIZ-03 | Temporal timeline component showing t_valid/t_invalid edge history for selected entity | GraphEdge response model already includes valid_at and invalid_at fields; need to query ALL edges (including invalidated ones) for timeline -- requires new Cypher query variant or backend modification |
| VIZ-04 | Ingestion graph preview showing entities added/changed/invalidated per ingestion run | SyncLog.details stores structured diff JSON with added/removed_from_document/modified arrays. Need new GET /api/graph/sync-logs endpoint to expose this data. Color coding via NVL Node.color property. |
| VIZ-05 | VITE_GRAPH_ENABLED env flag gates the graph explorer UI | Already implemented for /graph nav item in App.tsx; extend to /graph/explore route and chat entity links |
| VIZ-06 | "Graph indexing in progress" state when graph_synced count is 0 | GraphStatus response includes total_entities count; when total_entities=0 but graph is connected, show indexing state |

</phase_requirements>

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| @neo4j-nvl/react | 1.1.0 | React wrapper for graph canvas | Already installed; provides InteractiveNvlWrapper with built-in interaction handlers |
| @neo4j-nvl/base | 1.1.0 | Graph visualization core | Already installed; Node/Relationship interfaces, NVL class for programmatic control |
| @neo4j-nvl/interaction-handlers | 1.1.0 | Click, drag, zoom, pan handlers | Already installed; bundled into InteractiveNvlWrapper |
| react-router-dom | ^6.28.0 | Routing for /graph/explore | Already installed; useNavigate for entity deep-links, useSearchParams for ?entity= |
| lucide-react | ^0.563.0 | Icons for sidebar UI | Already installed; used throughout existing pages |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| React.memo | (React 18) | Prevent NVL re-renders during streaming | Wrap graph canvas component to isolate from chat state changes |
| useRef | (React 18) | Preserve NVL instance for imperative control | Access NVL methods like fit(), setZoom() without re-renders |
| useMemo | (React 18) | Stable node/rel arrays for NVL | Prevent unnecessary NVL re-renders from reference changes |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| InteractiveNvlWrapper | BasicNvlWrapper + manual handlers | More control but requires hand-wiring all interaction handlers; unnecessary since InteractiveNvlWrapper covers all needs |
| Force-directed layout | Hierarchical layout | Hierarchical suits tree structures; force-directed better for general knowledge graphs with cycles |
| CSS Grid for canvas/sidebar split | Flexbox | Grid gives more precise control over 2/3 + 1/3 layout with gap; flexbox works but grid is cleaner |

**Installation:** No new packages needed. All @neo4j-nvl packages already installed in Phase 6.

## Architecture Patterns

### Recommended Project Structure

```
web/src/
├── pages/
│   ├── GraphPage.tsx              # EXISTING: Graph status page at /graph
│   └── GraphExplorerPage.tsx      # NEW: Graph explorer at /graph/explore
├── components/
│   └── graph/                     # NEW: Graph-specific components
│       ├── GraphCanvas.tsx        # NVL canvas wrapper (React.memo)
│       ├── EntitySidebar.tsx      # Right sidebar container
│       ├── EntitySearch.tsx       # Search bar with debounce
│       ├── EntityDetails.tsx      # Properties + relationships card
│       ├── TemporalTimeline.tsx   # Edge history timeline
│       └── IngestionDiff.tsx      # Per-run diff preview
├── hooks/
│   └── useGraphExplorer.ts       # NEW: Graph data fetching + state
├── api/
│   └── client.ts                 # MODIFIED: Add graph explorer API functions
└── App.tsx                       # MODIFIED: Add /graph/explore route
```

### Pattern 1: Isolated NVL Canvas with React.memo

**What:** Wrap the NVL canvas in React.memo with custom comparison to prevent re-renders during chat streaming.
**When to use:** Always -- the NVL component is expensive to re-render and must not respond to unrelated state changes.

```tsx
// Source: NVL React docs + React performance patterns
import React, { useRef, useMemo, useCallback } from "react";
import { InteractiveNvlWrapper } from "@neo4j-nvl/react";
import type { Node, Relationship } from "@neo4j-nvl/base";

interface GraphCanvasProps {
  nodes: Node[];
  rels: Relationship[];
  onNodeClick: (node: Node) => void;
  onNodeDoubleClick: (node: Node) => void;
}

function GraphCanvasInner({ nodes, rels, onNodeClick, onNodeDoubleClick }: GraphCanvasProps) {
  const nvlRef = useRef(null);

  const mouseCallbacks = useMemo(() => ({
    onNodeClick: (node: Node) => onNodeClick(node),
    onNodeDoubleClick: (node: Node) => onNodeDoubleClick(node),
    onCanvasClick: () => {/* deselect */},
    onZoom: true,
    onPan: true,
  }), [onNodeClick, onNodeDoubleClick]);

  return (
    <div className="w-full h-full" style={{ minHeight: 400 }}>
      <InteractiveNvlWrapper
        ref={nvlRef}
        nodes={nodes}
        rels={rels}
        layout="forceDirected"
        mouseEventCallbacks={mouseCallbacks}
        nvlOptions={{
          initialZoom: 1,
          minZoom: 0.1,
          maxZoom: 5,
          disableTelemetry: true,
          renderer: "canvas",
        }}
      />
    </div>
  );
}

const GraphCanvas = React.memo(GraphCanvasInner);
export default GraphCanvas;
```

### Pattern 2: Entity Type Color Map

**What:** Map entity types to consistent colors for node styling.
**When to use:** When converting backend GraphNode data to NVL Node objects.

```tsx
// Source: Application pattern -- aligned with 7 entity types from entity_types.py
const ENTITY_TYPE_COLORS: Record<string, string> = {
  Person: "#6366f1",     // Indigo
  Team: "#8b5cf6",       // Violet
  Project: "#3b82f6",    // Blue
  Technology: "#10b981",  // Emerald
  Process: "#f59e0b",    // Amber
  Concept: "#ec4899",    // Pink
  Asset: "#6b7280",      // Gray
};

function toNvlNode(graphNode: GraphNode, connectionCount: number): Node {
  return {
    id: graphNode.uuid,
    caption: graphNode.name,
    color: ENTITY_TYPE_COLORS[graphNode.entity_type] ?? "#9ca3af",
    size: Math.max(20, Math.min(50, 20 + connectionCount * 5)),
  };
}

function toNvlRel(graphEdge: GraphEdge, nodeMap: Map<string, string>): Relationship {
  // Map source_name/target_name to UUIDs
  return {
    id: graphEdge.uuid,
    from: nodeMap.get(graphEdge.source_name) ?? graphEdge.source_name,
    to: nodeMap.get(graphEdge.target_name) ?? graphEdge.target_name,
    caption: graphEdge.relationship_type,
    color: "#d1d5db",
    width: 2,
  };
}
```

### Pattern 3: On-Demand Neighborhood Loading

**What:** Fetch 1-hop neighbors via the existing REST endpoint when user double-clicks a node.
**When to use:** Progressive disclosure -- user explores graph by expanding neighborhoods.

```tsx
// Source: Existing /api/graph/neighborhood/{entity_name} endpoint
async function expandNeighborhood(entityName: string) {
  const response = await getGraphNeighborhood(entityName);
  // Merge new nodes/edges into existing canvas state
  // Avoid duplicates by checking node IDs
  setNodes(prev => {
    const existing = new Set(prev.map(n => n.id));
    const newNodes = response.nodes
      .filter(n => !existing.has(n.uuid))
      .map(n => toNvlNode(n, response.edges.filter(
        e => e.source_name === n.name || e.target_name === n.name
      ).length));
    return [...prev, ...newNodes];
  });
  // Similar merge for edges
}
```

### Pattern 4: Deep-Link from Chat to Graph Explorer

**What:** Make entity names in chat responses clickable, navigating to `/graph/explore?entity={uuid}`.
**When to use:** When `VITE_GRAPH_ENABLED=true` and the agent returns entity references.

The existing `useMarkdownComponents` hook already handles custom anchor rendering. Entity links from the agent would appear as markdown links like `[Entity Name](/graph/explore?entity=uuid)` in the response text. The `renderAnchor` function in `useMarkdownComponents.tsx` can detect internal `/graph/explore` links and use `react-router-dom`'s `useNavigate` instead of a full page reload.

### Pattern 5: SyncLog Diff Visualization

**What:** Fetch SyncLog entries for a specific ingestion task and color-code affected entities on the canvas.
**When to use:** VIZ-04 ingestion preview feature.

```tsx
// Diff color coding for NVL nodes
const DIFF_COLORS = {
  added: "#22c55e",       // Green-500
  changed: "#eab308",     // Yellow-500
  invalidated: "#ef4444",  // Red-500
};

function applyDiffColoring(nodes: Node[], diffSummary: DiffSummary): Node[] {
  const addedNames = new Set(diffSummary.added.map(e => e.name));
  const changedNames = new Set(diffSummary.modified.map(e => e.name));
  const removedNames = new Set(diffSummary.removed_from_document.map(e => e.name));

  return nodes.map(node => {
    if (addedNames.has(node.caption ?? "")) return { ...node, color: DIFF_COLORS.added };
    if (changedNames.has(node.caption ?? "")) return { ...node, color: DIFF_COLORS.changed };
    if (removedNames.has(node.caption ?? "")) return { ...node, color: DIFF_COLORS.invalidated };
    return node;
  });
}
```

### Anti-Patterns to Avoid

- **Don't render NVL without a fixed-height container.** NVL requires a container with explicit height; `h-full` with proper parent sizing or a `min-height` on the container. Without it, the canvas collapses to 0 height.
- **Don't pass new node/rel array references on every render.** NVL re-lays-out on every `nodes`/`rels` change. Use `useMemo` to stabilize references, and only create new arrays when data actually changes.
- **Don't fetch the full entity list on page load for the canvas.** The entities endpoint returns up to 50 items per page. Instead, load a single entity's neighborhood (or the most-connected entity) as the starting view, and expand from there.
- **Don't mutate NVL node positions manually.** Let the force-directed layout handle positioning. Only use `pinned: true` on nodes the user has explicitly dragged.
- **Don't re-create the InteractiveNvlWrapper on every state change.** Keep the wrapper mounted and use `addAndUpdateElementsInGraph()` for dynamic updates via the NVL ref.
- **Don't put chat streaming state and graph state in the same component.** Chat state changes every token (~20ms); graph state changes on user interaction. These must be in separate React subtrees to prevent NVL re-renders during streaming.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Graph layout algorithm | Custom force simulation | NVL's built-in `layout="forceDirected"` | Complex physics simulation with edge crossings, overlap avoidance |
| Node drag with position pinning | Manual mouse event tracking | InteractiveNvlWrapper's built-in drag handler | Handles coordinate transforms, zoom-aware positioning |
| Graph zoom/pan with scroll events | Custom wheel/mouse handlers | InteractiveNvlWrapper's built-in zoom/pan | Handles scroll event conflicts, touch gestures, zoom limits |
| Hit testing (which node was clicked) | Manual bounding-box collision | NVL's `getHits()` / mouseEventCallbacks | Handles overlapping nodes, edge proximity, zoom-adjusted coordinates |
| Entity search with ranking | Custom search algorithm | Backend entity listing with name filter + frontend debounce | Server-side search handles case-insensitive matching via Cypher regex |
| Temporal timeline visualization | Custom SVG timeline | Simple CSS/HTML list with date markers | Entity edge counts are small (typically <20); a styled list with date labels is simpler and more maintainable than a custom timeline component |

**Key insight:** NVL handles all the hard graph rendering problems (layout, hit testing, zoom, pan, drag, rendering). The frontend work is mapping backend data models to NVL's Node/Relationship interfaces and building the sidebar detail panels.

## Common Pitfalls

### Pitfall 1: NVL Container Height Collapse
**What goes wrong:** The NVL canvas renders as a 0-height invisible element.
**Why it happens:** NVL's canvas element needs a container with explicit height. If the parent uses `height: auto` or `min-height: 0`, the canvas has no height to fill.
**How to avoid:** Set the NVL container to `h-full` with all ancestors also having explicit height (`h-screen` or `h-full` chain), or use `min-height: 400px` as a fallback.
**Warning signs:** Page renders but no graph is visible; canvas element exists in DOM with 0 height.

### Pitfall 2: NVL Re-Renders During Chat Streaming
**What goes wrong:** The graph canvas re-lays-out and resets zoom/pan position every time a chat token arrives.
**Why it happens:** If the NVL component is a descendant of a component whose state changes during streaming, React re-renders it. NVL interprets new `nodes`/`rels` prop references as data changes.
**How to avoid:** (1) Keep graph state completely separate from chat state -- they should live in different component subtrees. (2) Use `React.memo` on the graph canvas component. (3) Use `useMemo` on the nodes/rels arrays so references only change when data changes. (4) The graph explorer is a separate page (`/graph/explore`), not embedded in the chat page, which naturally isolates it.
**Warning signs:** Graph "jumps" or resets position during streaming responses.

### Pitfall 3: Node/Edge ID Collisions Between Neighborhood Expansions
**What goes wrong:** Duplicate nodes appear on the canvas, or edges connect to wrong nodes.
**Why it happens:** When expanding multiple neighborhoods, the same node can appear in multiple neighborhood responses. If not deduplicated, NVL may render duplicates or throw errors.
**How to avoid:** Maintain a `Set<string>` of node UUIDs currently on canvas. When merging new neighborhood data, skip nodes/edges whose UUIDs already exist. Use UUIDs (not names) as NVL node IDs to guarantee uniqueness.
**Warning signs:** Same entity appearing twice on canvas, edges not connecting to expected nodes.

### Pitfall 4: Missing Temporal Edges in History
**What goes wrong:** The temporal timeline only shows current (valid) edges, missing invalidated historical edges.
**Why it happens:** The existing neighborhood endpoint filters `WHERE e.invalid_at IS NULL`, excluding superseded edges. The temporal history needs ALL edges for the selected entity.
**How to avoid:** Create a dedicated backend endpoint or query parameter that returns both valid and invalidated edges for a specific entity. The existing `get_entity_history` agent tool already queries historical edges -- expose a similar REST endpoint.
**Warning signs:** Temporal timeline shows current state only, no historical changes visible.

### Pitfall 5: Entity Name vs UUID Mismatch in Edge References
**What goes wrong:** NVL edges fail to render because `from`/`to` don't match any node ID.
**Why it happens:** The backend `GraphEdge` model uses `source_name` and `target_name` (entity names), but NVL requires `from`/`to` to reference node IDs (which should be UUIDs). A name-to-UUID mapping is needed.
**How to avoid:** Build a `Map<string, string>` (name -> UUID) from the neighborhood response nodes, then use it when converting GraphEdge to NVL Relationship. The center node and all neighbor nodes are included in the response.
**Warning signs:** Edges render as disconnected or throw console errors about missing node references.

### Pitfall 6: WebGL Renderer Lacks Captions
**What goes wrong:** Edge labels and node captions don't render.
**Why it happens:** NVL's WebGL renderer doesn't support text rendering (captions, arrowheads). Only the `canvas` renderer supports captions.
**How to avoid:** Use `renderer: "canvas"` in nvlOptions. The user decision requires "edge labels always visible on the canvas," so WebGL is not an option.
**Warning signs:** Nodes render as colored circles with no text; edges have no labels.

## Code Examples

### InteractiveNvlWrapper Complete Setup

```tsx
// Source: NVL docs (https://neo4j.com/docs/nvl/current/react-wrappers/)
import { InteractiveNvlWrapper } from "@neo4j-nvl/react";
import type { Node, Relationship, MouseEventCallbacks } from "@neo4j-nvl/base";

const mouseCallbacks: MouseEventCallbacks = {
  onNodeClick: (node: Node, hitTargets, evt) => {
    // Show entity details in sidebar
    setSelectedEntity(node.id);
  },
  onNodeDoubleClick: (node: Node, hitTargets, evt) => {
    // Expand 1-hop neighborhood
    expandNeighborhood(node.id);
  },
  onCanvasClick: () => {
    // Deselect entity
    setSelectedEntity(null);
  },
  onZoom: true,   // Enable built-in zoom
  onPan: true,    // Enable built-in pan
  onDrag: true,   // Enable built-in drag
  onHover: true,  // Enable built-in hover
};

<InteractiveNvlWrapper
  nodes={nodes}
  rels={rels}
  layout="forceDirected"
  mouseEventCallbacks={mouseCallbacks}
  nvlOptions={{
    initialZoom: 1,
    minZoom: 0.1,
    maxZoom: 5,
    renderer: "canvas",
    disableTelemetry: true,
    allowDynamicMinZoom: true,
  }}
  nvlCallbacks={{
    onLayoutDone: () => {
      // Optional: fit all nodes after layout settles
    },
  }}
/>
```

### NVL Node Data Shape (Complete)

```tsx
// Source: NVL API docs (https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.Node.html)
interface NvlNode {
  id: string;              // Required: unique across all nodes AND rels
  caption?: string;        // Text displayed inside node (canvas renderer only)
  captions?: StyledCaption[]; // Multiple captions with custom styling
  captionAlign?: "center" | "top" | "bottom";
  captionSize?: number;
  color?: string;          // Node fill color
  size?: number;           // Node diameter
  icon?: string;           // URL to icon image
  pinned?: boolean;        // Lock position (set after user drag)
  selected?: boolean;      // Visual selection state
  activated?: boolean;     // Activation highlight
  hovered?: boolean;       // Hover state
  disabled?: boolean;      // Dimmed state
  html?: HTMLElement;      // Experimental: DOM overlay
}
```

### NVL Relationship Data Shape (Complete)

```tsx
// Source: NVL API docs (https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.Relationship.html)
interface NvlRelationship {
  id: string;              // Required: unique across all nodes AND rels
  from: string;            // Source node ID
  to: string;              // Target node ID
  caption?: string;        // Edge label text
  captions?: StyledCaption[];
  captionAlign?: "center" | "top" | "bottom";
  color?: string;          // Edge color
  width?: number;          // Edge thickness
  type?: string;           // Relationship type label
  selected?: boolean;
  hovered?: boolean;
  disabled?: boolean;
}
```

### Backend Data to NVL Conversion

```tsx
// Source: Application pattern -- maps existing API response models to NVL shapes
import { GraphNode, GraphEdge, NeighborhoodResponse } from "../api/client";

function convertNeighborhoodToNvl(response: NeighborhoodResponse) {
  // Build name-to-UUID map for edge references
  const nameToUuid = new Map<string, string>();
  nameToUuid.set(response.center.name, response.center.uuid);
  response.nodes.forEach(n => nameToUuid.set(n.name, n.uuid));

  // Count connections per node for sizing
  const connectionCount = new Map<string, number>();
  response.edges.forEach(e => {
    connectionCount.set(e.source_name, (connectionCount.get(e.source_name) ?? 0) + 1);
    connectionCount.set(e.target_name, (connectionCount.get(e.target_name) ?? 0) + 1);
  });

  // Convert center node
  const centerNode: Node = {
    id: response.center.uuid,
    caption: response.center.name,
    color: ENTITY_TYPE_COLORS[response.center.entity_type] ?? "#9ca3af",
    size: Math.max(30, Math.min(60, 30 + (connectionCount.get(response.center.name) ?? 0) * 5)),
    selected: true,
  };

  // Convert neighbor nodes
  const neighborNodes: Node[] = response.nodes.map(n => ({
    id: n.uuid,
    caption: n.name,
    color: ENTITY_TYPE_COLORS[n.entity_type] ?? "#9ca3af",
    size: Math.max(20, Math.min(50, 20 + (connectionCount.get(n.name) ?? 0) * 5)),
  }));

  // Convert edges (using UUID mapping)
  const rels: Relationship[] = response.edges.map(e => ({
    id: e.uuid,
    from: nameToUuid.get(e.source_name) ?? e.source_name,
    to: nameToUuid.get(e.target_name) ?? e.target_name,
    caption: e.relationship_type,
    color: "#94a3b8",
    width: 2,
  }));

  return {
    nodes: [centerNode, ...neighborNodes],
    rels,
  };
}
```

### New Backend Endpoint: SyncLog Retrieval

```python
# Source: Application pattern -- follows existing graph.py endpoint style
# New endpoint needed for VIZ-04

@router.get("/graph/sync-logs")
async def graph_sync_logs(
    document_id: str | None = None,
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
) -> list[SyncLogResponse]:
    """Return recent sync log entries with diff details.

    Query params:
      - document_id: Optional UUID to filter by document.
      - limit: Max entries to return (default 10, max 50).
    """
    effective_limit = min(limit, 50)
    query = (
        select(SyncLog)
        .order_by(SyncLog.created_at.desc())
        .limit(effective_limit)
    )
    if document_id:
        query = query.where(SyncLog.document_id == document_id)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        SyncLogResponse(
            id=str(log.id),
            document_id=str(log.document_id) if log.document_id else None,
            action=log.action,
            segments_affected=log.segments_affected,
            details=log.details,
            created_at=log.created_at.isoformat(),
        )
        for log in logs
    ]
```

### New Backend Endpoint: Entity History (All Edges Including Invalidated)

```python
# Source: Application pattern -- variant of existing neighborhood query
# Needed for VIZ-03 temporal timeline

@router.get("/graph/entity/{entity_name}/history")
async def entity_history(
    entity_name: str,
    graph_service: GraphitiService = Depends(get_graph_service),
) -> EntityHistoryResponse:
    """Return all edges (including invalidated) for temporal timeline.

    Unlike neighborhood which filters invalid_at IS NULL, this returns
    ALL edges ordered by valid_at for temporal visualization.
    """
    async with graph_service.client.driver.session() as session:
        result = await session.run(
            """
            MATCH (n:Entity)-[e:RELATES_TO]-(m:Entity)
            WHERE n.name =~ $name_pattern
            RETURN e.uuid AS uuid, e.fact AS fact, e.name AS rel_type,
                   e.valid_at AS valid_at, e.invalid_at AS invalid_at,
                   startNode(e).name AS source, endNode(e).name AS target
            ORDER BY e.valid_at ASC
            LIMIT 50
            """,
            name_pattern=f"(?i){entity_name}",
        )
        records = await result.data()
    # ... return structured response
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| vis.js / d3-force for Neo4j graph rendering | @neo4j-nvl official library | NVL 1.0 (2025) | Purpose-built for Neo4j data shapes, official support |
| Manual interaction handlers with BasicNvlWrapper | InteractiveNvlWrapper bundles all handlers | NVL 1.0 | Simpler setup, consistent behavior |
| Global graph state in Redux/Zustand | Component-local state with React hooks | React 18 patterns | Less boilerplate, NVL is self-contained |
| Separate zoom/pan buttons | Built-in mouse/touch gestures in InteractiveNvlWrapper | NVL 1.0 | No custom UI needed for basic viewport control |

**Deprecated/outdated:**
- `BasicNvlWrapper` without interaction handlers: Still works but requires manual handler wiring; InteractiveNvlWrapper is preferred.
- WebGL renderer for labeled graphs: Lacks caption/arrowhead support; canvas renderer required for this use case.
- vis.js for Neo4j graph visualization: No longer recommended by Neo4j; NVL is the official replacement.

## Open Questions

1. **NVL force-directed layout tuning parameters**
   - What we know: NVL supports `layout="forceDirected"` and `layoutOptions` for configuration. The module exports `ForceDirectedOptions` type.
   - What's unclear: The specific configurable parameters (gravity, charge, link distance) are not documented in the public API docs. The `ForceDirectedOptions` interface is referenced but not detailed.
   - Recommendation: Start with default force-directed layout (which works well for small graphs). If nodes overlap or spacing is poor, inspect the ForceDirectedOptions type definition in `node_modules/@neo4j-nvl/base` at implementation time to discover tuning parameters.

2. **NVL ref access in InteractiveNvlWrapper**
   - What we know: BasicNvlWrapper supports a ref to access the NVL class instance. InteractiveNvlWrapper extends BasicNvlWrapper.
   - What's unclear: Whether the ref forwarding works identically in InteractiveNvlWrapper and provides the full NVL class API (fit, setZoom, addAndUpdateElementsInGraph).
   - Recommendation: Test ref access during implementation. If InteractiveNvlWrapper doesn't forward ref, use BasicNvlWrapper with manual interaction handler setup as fallback.

3. **Edge label rendering performance with many edges**
   - What we know: Canvas renderer supports captions. User requirement is "edge labels always visible."
   - What's unclear: Performance impact of rendering 20+ edge labels simultaneously with force-directed layout animation.
   - Recommendation: The 20-edge cap per neighborhood (GRAPH-06) limits the maximum label count. This should be fine for canvas rendering. If performance issues arise, consider showing labels only on hover (which contradicts the user decision and should be discussed).

4. **SyncLog data completeness for ingestion diff**
   - What we know: SyncLog.details stores `{added: [], removed_from_document: [], modified: [], episodes_added: N, episodes_removed: N}`. This is written during graph sync in the ingestion pipeline.
   - What's unclear: Whether entity names in the diff summary correspond to current graph entity names (they should, since they're populated from Graphiti's extraction result). Also unclear how to correlate a SyncLog entry with a specific ingestion task_id for the "per-ingestion run" scoping.
   - Recommendation: Add a `task_id` or equivalent reference to SyncLog entries during implementation (if not already present), or use `created_at` timestamp proximity to correlate with ingestion tasks. The existing SyncLog model has `document_id` which links to a specific document, so grouping sync logs by timestamp window gives a reasonable "per-run" approximation.

## Sources

### Primary (HIGH confidence)
- [NVL React Wrappers](https://neo4j.com/docs/nvl/current/react-wrappers/) -- InteractiveNvlWrapper component API, mouseEventCallbacks
- [NVL Base Library](https://neo4j.com/docs/nvl/current/base-library/) -- Node/Relationship data shapes, NVL class methods
- [InteractiveNvlWrapperProps API](https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_react.InteractiveNvlWrapperProps.html) -- Complete props interface
- [NVL Node Interface](https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.Node.html) -- Node properties (color, size, caption, pinned, selected)
- [NVL Relationship Interface](https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.Relationship.html) -- Relationship properties (from, to, caption, color, width)
- [NVL NvlOptions](https://neo4j.com/docs/api/nvl/current/interfaces/_neo4j_nvl_base.NvlOptions.html) -- Layout, zoom, pan, renderer options
- [NVL Class API](https://neo4j.com/docs/api/nvl/current/classes/_neo4j_nvl_base.NVL.html) -- Methods: addAndUpdateElementsInGraph, fit, setZoom, setPan, removeNodesWithIds
- Existing codebase: `web/src/pages/GraphPage.tsx`, `web/src/App.tsx`, `src/pam/api/routes/graph.py` -- Current graph implementation patterns

### Secondary (MEDIUM confidence)
- [NVL Interaction Handlers](https://neo4j.com/docs/nvl/current/interaction-handlers/) -- Handler classes, callback structure
- [NVL Installation](https://neo4j.com/docs/nvl/current/installation/) -- Container height requirement
- Installed packages: @neo4j-nvl v1.1.0 confirmed from `node_modules/@neo4j-nvl/react/package.json`

### Tertiary (LOW confidence)
- Force-directed layout parameters: Not documented in public API; need to inspect TypeScript definitions at implementation time

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All packages already installed (Phase 6); NVL API well-documented with official docs
- Architecture: HIGH -- Clear separation between canvas and sidebar; existing project patterns for pages, hooks, and API client are unambiguous
- Pitfalls: HIGH -- Container height, re-render isolation, and data mapping issues identified from NVL docs and React patterns
- Backend gaps: HIGH -- SyncLog endpoint and entity history endpoint patterns follow existing codebase conventions exactly
- Force-directed tuning: LOW -- NVL layout options not publicly documented; defaults should work but tuning may need empirical testing

**Research date:** 2026-02-21
**Valid until:** 2026-03-21 (30 days -- stable domain, NVL at v1.1.0)
