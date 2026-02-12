import { useEffect, useState } from "react";
import { getStats, SystemStats } from "../api/client";

function StatCard({ label, value, sub }: { label: string; value: number | string; sub?: string }) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 p-5">
      <p className="text-xs font-medium text-gray-400 uppercase tracking-wide">{label}</p>
      <p className="text-2xl font-bold text-gray-800 mt-1">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-1">{sub}</p>}
    </div>
  );
}

export default function AdminDashboard() {
  const [stats, setStats] = useState<SystemStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load stats"))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex items-center gap-2 text-sm text-gray-400">
          <span className="inline-block w-2 h-2 bg-indigo-400 rounded-full animate-pulse" />
          Loading dashboard...
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm text-red-500 bg-red-50 rounded-lg p-4">{error}</div>
      </div>
    );
  }

  if (!stats) return null;

  const statusBreakdown = Object.entries(stats.documents.by_status)
    .map(([status, count]) => `${count} ${status}`)
    .join(", ");

  const entityBreakdown = Object.entries(stats.entities.by_type)
    .map(([type, count]) => `${count} ${type}`)
    .join(", ");

  return (
    <div className="flex flex-col h-full">
      <header className="px-6 py-3 border-b border-gray-200 bg-white">
        <h2 className="text-base font-semibold text-gray-800">Admin Dashboard</h2>
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Stats cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <StatCard
            label="Documents"
            value={stats.documents.total}
            sub={statusBreakdown || undefined}
          />
          <StatCard label="Segments" value={stats.segments} />
          <StatCard
            label="Entities"
            value={stats.entities.total}
            sub={entityBreakdown || undefined}
          />
          <StatCard
            label="Ingestion Tasks"
            value={stats.recent_tasks.length}
            sub="shown (last 10)"
          />
        </div>

        {/* Document status breakdown */}
        {Object.keys(stats.documents.by_status).length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Documents by Status</h3>
            <div className="flex gap-4">
              {Object.entries(stats.documents.by_status).map(([status, count]) => (
                <div key={status} className="flex items-center gap-2">
                  <span
                    className={`w-2 h-2 rounded-full ${
                      status === "active"
                        ? "bg-green-400"
                        : status === "error"
                        ? "bg-red-400"
                        : "bg-gray-400"
                    }`}
                  />
                  <span className="text-sm text-gray-600">
                    {status}: <span className="font-medium">{count}</span>
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Entity breakdown */}
        {stats.entities.total > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 p-5">
            <h3 className="text-sm font-semibold text-gray-700 mb-3">Entities by Type</h3>
            <div className="flex gap-4 flex-wrap">
              {Object.entries(stats.entities.by_type).map(([type, count]) => (
                <span
                  key={type}
                  className="inline-flex items-center gap-1.5 rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700"
                >
                  {type}
                  <span className="rounded-full bg-indigo-200 px-1.5 py-0.5 text-[10px]">{count}</span>
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Recent ingestion tasks */}
        {stats.recent_tasks.length > 0 && (
          <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-gray-100">
              <h3 className="text-sm font-semibold text-gray-700">Recent Ingestion Tasks</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-100 text-left text-xs font-medium text-gray-400 uppercase tracking-wide">
                    <th className="px-5 py-2">Status</th>
                    <th className="px-5 py-2">Path</th>
                    <th className="px-5 py-2">Docs</th>
                    <th className="px-5 py-2">OK</th>
                    <th className="px-5 py-2">Failed</th>
                    <th className="px-5 py-2">Created</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.recent_tasks.map((task) => (
                    <tr key={task.id} className="border-b border-gray-50 hover:bg-gray-50/50">
                      <td className="px-5 py-2.5">
                        <span
                          className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                            task.status === "completed"
                              ? "bg-green-50 text-green-700"
                              : task.status === "running"
                              ? "bg-blue-50 text-blue-700"
                              : task.status === "failed"
                              ? "bg-red-50 text-red-700"
                              : "bg-gray-100 text-gray-600"
                          }`}
                        >
                          {task.status}
                        </span>
                      </td>
                      <td className="px-5 py-2.5 text-gray-600 font-mono text-xs max-w-[200px] truncate">
                        {task.folder_path}
                      </td>
                      <td className="px-5 py-2.5 text-gray-600">{task.total_documents}</td>
                      <td className="px-5 py-2.5 text-green-600">{task.succeeded}</td>
                      <td className="px-5 py-2.5 text-red-600">{task.failed}</td>
                      <td className="px-5 py-2.5 text-gray-400 text-xs">
                        {task.created_at
                          ? new Date(task.created_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
