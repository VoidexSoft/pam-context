import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import type { Node, Relationship } from "@neo4j-nvl/base";
import { useGraphExplorer } from "../hooks/useGraphExplorer";
import GraphCanvas from "../components/graph/GraphCanvas";
import EntitySidebar from "../components/graph/EntitySidebar";
import IngestionDiff from "../components/graph/IngestionDiff";
import type { FilterMode } from "../components/graph/IngestionDiff";

export default function GraphExplorerPage() {
  const [searchParams] = useSearchParams();
  const {
    nodes,
    rels,
    selectedEntity,
    selectedEntityHistory,
    selectedEntityEdges,
    loading,
    error,
    entityCount,
    documentCount,
    graphSyncedCount,
    selectEntity,
    expandNeighborhood,
    focusEntity,
    deselectEntity,
  } = useGraphExplorer();

  // Diff overlay state
  const [diffColors, setDiffColors] = useState<Map<string, string> | null>(
    null
  );
  const [diffFilterMode, setDiffFilterMode] = useState<FilterMode>("filtered");

  const handleApplyDiff = useCallback(
    (colors: Map<string, string> | null, mode: FilterMode) => {
      setDiffColors(colors);
      setDiffFilterMode(mode);
    },
    []
  );

  // Compute modified nodes/rels based on diff overlay
  const displayNodes: Node[] = useMemo(() => {
    if (!diffColors) return nodes;

    if (diffFilterMode === "filtered") {
      // Only show nodes whose captions (entity names) are in the diff map
      return nodes
        .filter((n) => diffColors.has(n.caption ?? ""))
        .map((n) => ({
          ...n,
          color: diffColors.get(n.caption ?? "") ?? n.color,
        }));
    }

    // Highlighted: show all nodes but override colors for affected ones
    return nodes.map((n) => {
      const diffColor = diffColors.get(n.caption ?? "");
      return diffColor ? { ...n, color: diffColor } : n;
    });
  }, [nodes, diffColors, diffFilterMode]);

  const displayRels: Relationship[] = useMemo(() => {
    if (!diffColors || diffFilterMode !== "filtered") return rels;

    // In filtered mode, only show edges between visible (diff-affected) nodes
    const visibleNodeIds = new Set(displayNodes.map((n) => n.id));
    return rels.filter(
      (r) => visibleNodeIds.has(r.from) && visibleNodeIds.has(r.to)
    );
  }, [rels, diffColors, diffFilterMode, displayNodes]);

  // Deep-link handling: ?entity=name loads that entity's neighborhood
  useEffect(() => {
    const entityParam = searchParams.get("entity");
    if (entityParam && !loading && entityCount > 0) {
      focusEntity(entityParam);
    }
    // Only run on initial mount with entity param
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Loading state
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <span className="inline-block w-2 h-2 bg-indigo-400 rounded-full animate-pulse" />
          Loading graph data...
        </div>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div className="flex flex-col h-full">
        <header className="px-6 py-3 border-b border-gray-200 bg-white">
          <h2 className="text-base font-semibold text-gray-800">
            Graph Explorer
          </h2>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3">
            <p className="text-sm text-gray-500">
              {error.includes("500") || error.includes("fetch")
                ? "Could not reach the graph API. Is the backend running?"
                : error}
            </p>
            <button
              onClick={() => window.location.reload()}
              className="text-sm text-indigo-600 hover:text-indigo-700 font-medium"
            >
              Retry
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Empty state: Branch A — No documents ingested
  if (entityCount === 0 && documentCount === 0) {
    return (
      <div className="flex flex-col h-full">
        <header className="px-6 py-3 border-b border-gray-200 bg-white">
          <h2 className="text-base font-semibold text-gray-800">
            Graph Explorer
          </h2>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3 max-w-sm">
            <div className="mx-auto w-16 h-16 rounded-full bg-indigo-50 flex items-center justify-center">
              <svg
                className="w-8 h-8 text-indigo-400"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={1.5}
                  d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"
                />
              </svg>
            </div>
            <p className="text-sm text-gray-800 font-medium">
              No documents ingested
            </p>
            <p className="text-sm text-gray-500">
              Ingest documents to build the knowledge graph
            </p>
            <Link
              to="/admin"
              className="inline-block px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-md hover:bg-indigo-700 transition-colors"
            >
              Go to Ingest
            </Link>
          </div>
        </div>
      </div>
    );
  }

  // Empty state: Branch B — Documents exist but graph not synced
  if (entityCount === 0 && documentCount > 0) {
    const pendingCount = documentCount - graphSyncedCount;
    return (
      <div className="flex flex-col h-full">
        <header className="px-6 py-3 border-b border-gray-200 bg-white">
          <h2 className="text-base font-semibold text-gray-800">
            Graph Explorer
          </h2>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3 max-w-sm">
            <div className="mx-auto w-16 h-16 rounded-full bg-indigo-50 flex items-center justify-center">
              <svg
                className="w-8 h-8 text-indigo-400 animate-pulse"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <circle cx="6" cy="6" r="2.5" strokeWidth={1.5} />
                <circle cx="18" cy="12" r="2.5" strokeWidth={1.5} />
                <circle cx="8" cy="18" r="2.5" strokeWidth={1.5} />
                <path
                  strokeLinecap="round"
                  strokeWidth={1.5}
                  d="M8.5 6.5L15.5 11M10.5 17L15.5 13"
                />
              </svg>
            </div>
            <p className="text-sm text-gray-800 font-medium">
              Graph indexing in progress
            </p>
            <p className="text-sm text-gray-500">
              {pendingCount} {pendingCount === 1 ? "document" : "documents"} awaiting graph indexing
            </p>
          </div>
        </div>
      </div>
    );
  }

  // Main explorer layout
  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-3 border-b border-gray-200 bg-white shrink-0">
        <h2 className="text-base font-semibold text-gray-800">
          Graph Explorer
        </h2>
        <p className="text-xs text-gray-400 mt-0.5">
          Click a node to view details. Double-click to expand its neighborhood.
        </p>
      </header>

      <div className="flex-1 grid grid-cols-[2fr_1fr] min-h-0">
        {/* Canvas section */}
        <div className="h-full min-h-0 bg-gray-50">
          <GraphCanvas
            nodes={displayNodes}
            rels={displayRels}
            onNodeClick={selectEntity}
            onNodeDoubleClick={expandNeighborhood}
            onCanvasClick={deselectEntity}
          />
        </div>

        {/* Sidebar section */}
        <EntitySidebar
          selectedEntity={selectedEntity}
          selectedEntityHistory={selectedEntityHistory}
          edges={selectedEntityEdges}
          onSearch={focusEntity}
          onEntitySelect={focusEntity}
          footer={<IngestionDiff onApplyDiff={handleApplyDiff} />}
        />
      </div>
    </div>
  );
}
