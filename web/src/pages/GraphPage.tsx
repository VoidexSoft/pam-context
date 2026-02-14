import { useCallback, useEffect, useState } from "react";
import {
  getGraphEntities,
  getGraphEntity,
  getSubgraph,
  getTimeline,
  type GraphEntity,
  type GraphEntityDetail,
  type SubgraphResponse,
  type TimelineResponse,
} from "../api/client";
import GraphExplorer from "../components/GraphExplorer";
import Timeline from "../components/Timeline";

export default function GraphPage() {
  const [search, setSearch] = useState("");
  const [entities, setEntities] = useState<GraphEntity[]>([]);
  const [entitiesLoading, setEntitiesLoading] = useState(true);
  const [entitiesError, setEntitiesError] = useState<string | null>(null);

  const [selectedEntity, setSelectedEntity] = useState<string | null>(null);
  const [entityDetail, setEntityDetail] = useState<GraphEntityDetail | null>(null);
  const [subgraph, setSubgraph] = useState<SubgraphResponse | null>(null);
  const [graphLoading, setGraphLoading] = useState(false);
  const [timeline, setTimeline] = useState<TimelineResponse | null>(null);
  const [timelineLoading, setTimelineLoading] = useState(false);

  const [depth, setDepth] = useState(2);
  const [tab, setTab] = useState<"graph" | "timeline">("graph");

  // Load entity list on mount
  useEffect(() => {
    getGraphEntities()
      .then(setEntities)
      .catch((err) =>
        setEntitiesError(err instanceof Error ? err.message : "Failed to load entities")
      )
      .finally(() => setEntitiesLoading(false));
  }, []);

  const selectEntity = useCallback(
    async (name: string) => {
      setSelectedEntity(name);
      setGraphLoading(true);
      setTimelineLoading(true);

      try {
        const [sg, detail, tl] = await Promise.all([
          getSubgraph(name, depth),
          getGraphEntity(name),
          getTimeline(name),
        ]);
        setSubgraph(sg);
        setEntityDetail(detail);
        setTimeline(tl);
      } catch {
        // Individual errors handled by components
      } finally {
        setGraphLoading(false);
        setTimelineLoading(false);
      }
    },
    [depth]
  );

  const handleNodeClick = useCallback(
    (name: string) => {
      selectEntity(name);
      setSearch(name);
    },
    [selectEntity]
  );

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (search.trim()) {
      selectEntity(search.trim());
    }
  };

  const filteredEntities = search
    ? entities.filter((e) => e.name.toLowerCase().includes(search.toLowerCase()))
    : entities;

  if (entitiesError?.includes("503")) {
    return (
      <div className="flex flex-col h-full">
        <header className="px-6 py-3 border-b border-gray-200 bg-white">
          <h2 className="text-base font-semibold text-gray-800">Knowledge Graph</h2>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-sm text-gray-500">
              Knowledge graph is not available. Is Neo4j running?
            </p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-3 border-b border-gray-200 bg-white flex items-center gap-4">
        <h2 className="text-base font-semibold text-gray-800">Knowledge Graph</h2>

        {/* Search */}
        <form onSubmit={handleSearch} className="flex-1 max-w-md">
          <div className="relative">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search entities..."
              className="w-full rounded-lg border border-gray-200 bg-gray-50 px-3 py-1.5 text-sm focus:border-indigo-300 focus:bg-white focus:outline-none focus:ring-1 focus:ring-indigo-300"
            />
            <button
              type="submit"
              className="absolute right-1 top-1 rounded-md bg-indigo-500 px-2 py-0.5 text-xs text-white hover:bg-indigo-600"
            >
              Explore
            </button>
          </div>
        </form>

        {/* Depth control */}
        <div className="flex items-center gap-1.5 text-xs text-gray-500">
          <span>Depth:</span>
          {[1, 2, 3, 4].map((d) => (
            <button
              key={d}
              onClick={() => {
                setDepth(d);
                if (selectedEntity) selectEntity(selectedEntity);
              }}
              className={`w-6 h-6 rounded ${
                depth === d
                  ? "bg-indigo-500 text-white"
                  : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden">
        {/* Left sidebar: entity list */}
        <aside className="w-56 border-r border-gray-200 bg-white overflow-y-auto flex-shrink-0">
          <div className="p-3">
            <p className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-2">
              Entities{" "}
              {!entitiesLoading && (
                <span className="text-gray-300">({entities.length})</span>
              )}
            </p>
            {entitiesLoading ? (
              <div className="text-xs text-gray-400 py-2">Loading...</div>
            ) : filteredEntities.length === 0 ? (
              <div className="text-xs text-gray-400 py-2">No entities found</div>
            ) : (
              <ul className="space-y-0.5">
                {filteredEntities.slice(0, 100).map((entity) => (
                  <li key={entity.name}>
                    <button
                      onClick={() => {
                        setSearch(entity.name);
                        selectEntity(entity.name);
                      }}
                      className={`w-full text-left px-2 py-1.5 rounded-md text-sm transition-colors ${
                        selectedEntity === entity.name
                          ? "bg-indigo-50 text-indigo-700"
                          : "text-gray-600 hover:bg-gray-50"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="truncate">{entity.name}</span>
                        <span className="text-[10px] text-gray-400 ml-1">
                          {entity.rel_count}
                        </span>
                      </div>
                      <span className="text-[10px] text-gray-400">{entity.label}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* Main content */}
        <div className="flex-1 flex flex-col overflow-hidden">
          {/* Tab bar */}
          <div className="flex border-b border-gray-200 bg-white px-4">
            {(["graph", "timeline"] as const).map((t) => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                  tab === t
                    ? "border-indigo-500 text-indigo-600"
                    : "border-transparent text-gray-500 hover:text-gray-700"
                }`}
              >
                {t === "graph" ? "Graph" : "Timeline"}
              </button>
            ))}
          </div>

          {/* Content */}
          <div className="flex-1 flex overflow-hidden">
            <div className="flex-1 overflow-hidden">
              {tab === "graph" ? (
                <GraphExplorer
                  data={subgraph}
                  loading={graphLoading}
                  onNodeClick={handleNodeClick}
                  selectedNode={selectedEntity}
                />
              ) : (
                <div className="p-4 overflow-y-auto h-full">
                  <Timeline
                    data={timeline}
                    loading={timelineLoading}
                    onEntityClick={handleNodeClick}
                  />
                </div>
              )}
            </div>

            {/* Right panel: entity detail */}
            {entityDetail && (
              <aside className="w-72 border-l border-gray-200 bg-white overflow-y-auto flex-shrink-0">
                <div className="p-4 space-y-4">
                  {/* Entity header */}
                  <div>
                    <h3 className="text-sm font-semibold text-gray-800">
                      {entityDetail.name}
                    </h3>
                    <span className="text-xs bg-gray-100 text-gray-500 rounded-full px-2 py-0.5">
                      {entityDetail.label}
                    </span>
                  </div>

                  {/* Properties */}
                  {Object.keys(entityDetail.properties).length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">
                        Properties
                      </h4>
                      <dl className="space-y-1">
                        {Object.entries(entityDetail.properties)
                          .filter(([k]) => k !== "name")
                          .map(([key, value]) => (
                            <div key={key}>
                              <dt className="text-[10px] text-gray-400">{key}</dt>
                              <dd className="text-xs text-gray-700 break-words">
                                {String(value ?? "—")}
                              </dd>
                            </div>
                          ))}
                      </dl>
                    </div>
                  )}

                  {/* Relationships */}
                  {entityDetail.relationships.length > 0 && (
                    <div>
                      <h4 className="text-xs font-medium text-gray-400 uppercase tracking-wide mb-1">
                        Relationships ({entityDetail.relationships.length})
                      </h4>
                      <ul className="space-y-1.5">
                        {entityDetail.relationships.map((rel, i) => (
                          <li key={i} className="text-xs">
                            <div className="flex items-center gap-1 flex-wrap">
                              <span className="text-gray-400">
                                {rel.direction === "outgoing" ? "\u2192" : "\u2190"}
                              </span>
                              <span className="font-mono text-[10px] bg-gray-100 rounded px-1 py-0.5 text-gray-500">
                                {rel.rel_type}
                              </span>
                              <button
                                onClick={() => handleNodeClick(rel.target_name)}
                                className="text-indigo-600 hover:underline"
                              >
                                {rel.target_name}
                              </button>
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              </aside>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
