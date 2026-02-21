import { useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { getGraphSyncLogs, type SyncLogEntry } from "../../api/client";

const DIFF_COLORS = {
  added: "#22c55e",
  changed: "#eab308",
  invalidated: "#ef4444",
};

type FilterMode = "filtered" | "highlighted";

interface IngestionDiffProps {
  onApplyDiff: (
    diffColors: Map<string, string> | null,
    mode: FilterMode
  ) => void;
  className?: string;
}

export default function IngestionDiff({
  onApplyDiff,
  className = "",
}: IngestionDiffProps) {
  const [syncLogs, setSyncLogs] = useState<SyncLogEntry[]>([]);
  const [selectedLogId, setSelectedLogId] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<FilterMode>("filtered");
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState(false);

  // Fetch sync logs on mount
  useEffect(() => {
    let cancelled = false;
    async function fetchLogs() {
      try {
        const logs = await getGraphSyncLogs({ limit: 10 });
        if (!cancelled) {
          setSyncLogs(logs);
          setLoading(false);
        }
      } catch {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }
    fetchLogs();
    return () => {
      cancelled = true;
    };
  }, []);

  // Build and apply diff color map when selection or filter mode changes
  const applyDiffForLog = useCallback(
    (logId: string | null, mode: FilterMode) => {
      if (!logId) {
        onApplyDiff(null, mode);
        return;
      }

      const log = syncLogs.find((l) => l.id === logId);
      if (!log) {
        onApplyDiff(null, mode);
        return;
      }

      const colorMap = new Map<string, string>();

      if (log.details.added) {
        for (const entity of log.details.added) {
          colorMap.set(entity.name, DIFF_COLORS.added);
        }
      }
      if (log.details.modified) {
        for (const entity of log.details.modified) {
          colorMap.set(entity.name, DIFF_COLORS.changed);
        }
      }
      if (log.details.removed_from_document) {
        for (const entity of log.details.removed_from_document) {
          colorMap.set(entity.name, DIFF_COLORS.invalidated);
        }
      }

      onApplyDiff(colorMap.size > 0 ? colorMap : null, mode);
    },
    [syncLogs, onApplyDiff]
  );

  const handleSelectLog = useCallback(
    (logId: string) => {
      if (logId === "") {
        setSelectedLogId(null);
        onApplyDiff(null, filterMode);
        return;
      }
      setSelectedLogId(logId);
      applyDiffForLog(logId, filterMode);
    },
    [applyDiffForLog, onApplyDiff, filterMode]
  );

  // Re-apply when filter mode changes
  useEffect(() => {
    applyDiffForLog(selectedLogId, filterMode);
  }, [filterMode, selectedLogId, applyDiffForLog]);

  const selectedLog = syncLogs.find((l) => l.id === selectedLogId) ?? null;

  const addedEntities = selectedLog?.details.added ?? [];
  const changedEntities = selectedLog?.details.modified ?? [];
  const invalidatedEntities =
    selectedLog?.details.removed_from_document ?? [];

  return (
    <section className={className}>
      {/* Collapsible header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 w-full text-left"
      >
        {expanded ? (
          <ChevronDown className="w-3.5 h-3.5 text-gray-400" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5 text-gray-400" />
        )}
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
          Ingestion Changes
        </h4>
      </button>

      {expanded && (
        <div className="mt-3 space-y-3">
          {loading ? (
            <p className="text-xs text-gray-400">Loading sync logs...</p>
          ) : syncLogs.length === 0 ? (
            <p className="text-xs text-gray-400">
              No ingestion history available.
            </p>
          ) : (
            <>
              {/* Sync log selector */}
              <select
                value={selectedLogId ?? ""}
                onChange={(e) => handleSelectLog(e.target.value)}
                className="w-full text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-indigo-300"
              >
                <option value="">Select an ingestion run...</option>
                {syncLogs.map((log) => (
                  <option key={log.id} value={log.id}>
                    {log.action}
                    {log.document_id
                      ? ` — doc ${log.document_id.slice(0, 8)}`
                      : ""}
                    {" — "}
                    {new Date(log.created_at).toLocaleDateString(undefined, {
                      month: "short",
                      day: "numeric",
                      hour: "2-digit",
                      minute: "2-digit",
                    })}
                  </option>
                ))}
              </select>

              {/* Filter mode toggle */}
              {selectedLogId && (
                <div className="flex rounded-md overflow-hidden border border-gray-200">
                  <button
                    onClick={() => setFilterMode("filtered")}
                    className={`flex-1 text-xs py-1 px-2 font-medium transition-colors ${
                      filterMode === "filtered"
                        ? "bg-indigo-50 text-indigo-700 border-r border-gray-200"
                        : "bg-white text-gray-500 border-r border-gray-200 hover:bg-gray-50"
                    }`}
                  >
                    Filtered
                  </button>
                  <button
                    onClick={() => setFilterMode("highlighted")}
                    className={`flex-1 text-xs py-1 px-2 font-medium transition-colors ${
                      filterMode === "highlighted"
                        ? "bg-indigo-50 text-indigo-700"
                        : "bg-white text-gray-500 hover:bg-gray-50"
                    }`}
                  >
                    Highlighted
                  </button>
                </div>
              )}

              {/* Entity changes grouped by type */}
              {selectedLog && (
                <div className="space-y-2">
                  {addedEntities.length > 0 && (
                    <div>
                      <h5
                        className="text-xs font-semibold mb-1"
                        style={{ color: DIFF_COLORS.added }}
                      >
                        Added ({addedEntities.length})
                      </h5>
                      <ul className="space-y-0.5">
                        {addedEntities.map((e) => (
                          <li
                            key={e.name}
                            className="text-xs text-gray-600 pl-2 border-l-2"
                            style={{ borderColor: DIFF_COLORS.added }}
                          >
                            {e.name}
                            {e.entity_type && (
                              <span className="ml-1 text-gray-400">
                                ({e.entity_type})
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {changedEntities.length > 0 && (
                    <div>
                      <h5
                        className="text-xs font-semibold mb-1"
                        style={{ color: DIFF_COLORS.changed }}
                      >
                        Changed ({changedEntities.length})
                      </h5>
                      <ul className="space-y-0.5">
                        {changedEntities.map((e) => (
                          <li
                            key={e.name}
                            className="text-xs text-gray-600 pl-2 border-l-2"
                            style={{ borderColor: DIFF_COLORS.changed }}
                          >
                            {e.name}
                            {e.changes && (
                              <span className="ml-1 text-gray-400">
                                ({Object.keys(e.changes).join(", ")})
                              </span>
                            )}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {invalidatedEntities.length > 0 && (
                    <div>
                      <h5
                        className="text-xs font-semibold mb-1"
                        style={{ color: DIFF_COLORS.invalidated }}
                      >
                        Invalidated ({invalidatedEntities.length})
                      </h5>
                      <ul className="space-y-0.5">
                        {invalidatedEntities.map((e) => (
                          <li
                            key={e.name}
                            className="text-xs text-gray-600 pl-2 border-l-2"
                            style={{ borderColor: DIFF_COLORS.invalidated }}
                          >
                            {e.name}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {addedEntities.length === 0 &&
                    changedEntities.length === 0 &&
                    invalidatedEntities.length === 0 && (
                      <p className="text-xs text-gray-400">
                        No entity changes in this run.
                      </p>
                    )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </section>
  );
}

export { DIFF_COLORS };
export type { FilterMode };
