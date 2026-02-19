import { useCallback, useEffect, useState } from "react";
import { getGraphStatus, GraphStatus } from "../api/client";

function StatCard({
  label,
  value,
  sub,
  indicator,
}: {
  label: string;
  value: number | string;
  sub?: string;
  indicator?: "green" | "red";
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">
        {label}
      </p>
      <div className="flex items-center gap-2 mt-1">
        {indicator && (
          <span
            className={`inline-block w-2.5 h-2.5 rounded-full ${
              indicator === "green" ? "bg-green-400" : "bg-red-400"
            }`}
          />
        )}
        <p className="text-2xl font-bold text-gray-800">{value}</p>
      </div>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

function formatSyncTime(time: string | null): string {
  if (!time) return "Never";
  try {
    return new Date(time).toLocaleString();
  } catch {
    return time;
  }
}

export default function GraphPage() {
  const [status, setStatus] = useState<GraphStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getGraphStatus()
      .then(setStatus)
      .catch((err) =>
        setError(err instanceof Error ? err.message : "Failed to load graph status")
      )
      .finally(() => setLoading(false));
  }, [refreshKey]);

  const handleRefresh = useCallback(() => {
    setRefreshKey((k) => k + 1);
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <span className="inline-block w-2 h-2 bg-indigo-400 rounded-full animate-pulse" />
          Loading graph status...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col h-full">
        <header className="px-6 py-3 border-b border-gray-200 bg-white">
          <h2 className="text-base font-semibold text-gray-800">
            Knowledge Graph
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Neo4j graph database status and entity overview
          </p>
        </header>
        <div className="flex-1 flex items-center justify-center">
          <div className="text-center">
            <p className="text-sm text-gray-500">
              {error.includes("500") || error.includes("fetch")
                ? "Could not reach the graph API. Is the backend running?"
                : error}
            </p>
          </div>
        </div>
      </div>
    );
  }

  if (!status) return null;

  const isConnected = status.status === "connected";
  const entityEntries = Object.entries(status.entity_counts);

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-3 border-b border-gray-200 bg-white flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-800">
            Knowledge Graph
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Neo4j graph database status and entity overview
          </p>
        </div>
        <button
          onClick={handleRefresh}
          disabled={loading}
          aria-label="Refresh graph status"
          className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Stat cards */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <StatCard
            label="Neo4j Status"
            value={isConnected ? "Connected" : "Disconnected"}
            indicator={isConnected ? "green" : "red"}
          />
          <StatCard
            label="Total Entities"
            value={status.total_entities}
          />
          <StatCard
            label="Last Sync"
            value={formatSyncTime(status.last_sync_time)}
          />
        </div>

        {/* Entity counts by type */}
        {entityEntries.length > 0 ? (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">
              Entities by Type
            </h3>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {entityEntries.map(([type, count]) => (
                <div
                  key={type}
                  className="flex items-center justify-between rounded-lg border border-gray-100 bg-gray-50 px-4 py-3"
                >
                  <span className="text-sm font-medium text-gray-700">
                    {type}
                  </span>
                  <span className="text-sm font-bold text-indigo-600">
                    {count}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <p className="text-sm text-gray-400">
              No entities yet. Run an ingestion to populate the knowledge graph.
            </p>
          </div>
        )}

        {/* Error message if present */}
        {status.error && (
          <div className="bg-red-50 rounded-xl border border-red-200 p-5">
            <h3 className="text-sm font-semibold text-red-700 mb-1">
              Connection Error
            </h3>
            <p className="text-sm text-red-600">{status.error}</p>
          </div>
        )}
      </div>
    </div>
  );
}
