import { useEffect } from "react";
import { useSearchParams, Link } from "react-router-dom";
import { useGraphExplorer } from "../hooks/useGraphExplorer";
import GraphCanvas from "../components/graph/GraphCanvas";
import EntitySidebar from "../components/graph/EntitySidebar";

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
    selectEntity,
    expandNeighborhood,
    focusEntity,
    deselectEntity,
  } = useGraphExplorer();

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

  // Empty state
  if (entityCount === 0) {
    return (
      <div className="flex flex-col h-full">
        <header className="px-6 py-3 border-b border-gray-200 bg-white">
          <h2 className="text-base font-semibold text-gray-800">
            Graph Explorer
          </h2>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center space-y-3 max-w-sm">
            <div className="mx-auto w-16 h-16 rounded-full bg-gray-100 flex items-center justify-center">
              <svg
                className="w-8 h-8 text-gray-400"
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
            <p className="text-sm text-gray-600 font-medium">
              No graph data yet
            </p>
            <p className="text-sm text-gray-400">
              Ingest some documents to build the knowledge graph.
            </p>
            <Link
              to="/admin"
              className="inline-block text-sm text-indigo-600 hover:text-indigo-700 font-medium"
            >
              Go to Admin
            </Link>
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
            nodes={nodes}
            rels={rels}
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
        />
      </div>
    </div>
  );
}
