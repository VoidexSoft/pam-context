import type { TimelineEntry, TimelineResponse } from "../api/client";

const REL_COLORS: Record<string, string> = {
  DEFINED_IN: "#64748b",
  DEPENDS_ON: "#6366f1",
  TRACKED_BY: "#f59e0b",
  TARGETS: "#10b981",
  OWNED_BY: "#ec4899",
  SOURCED_FROM: "#06b6d4",
  DISPLAYED_ON: "#8b5cf6",
};

function formatDate(d: string | null): string {
  if (!d) return "present";
  try {
    return new Date(d).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return d;
  }
}

interface Props {
  data: TimelineResponse | null;
  loading: boolean;
  onEntityClick?: (name: string) => void;
}

export default function Timeline({ data, loading, onEntityClick }: Props) {
  if (loading) {
    return (
      <div className="flex items-center justify-center py-8 text-sm text-gray-400">
        <span className="inline-block w-2 h-2 bg-indigo-400 rounded-full animate-pulse mr-2" />
        Loading timeline...
      </div>
    );
  }

  if (!data) {
    return (
      <div className="text-sm text-gray-400 text-center py-8">
        Select an entity to view its history.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="flex items-center gap-2">
        <h3 className="text-sm font-semibold text-gray-700">
          {data.entity_name}
        </h3>
        <span className="text-xs bg-gray-100 text-gray-500 rounded-full px-2 py-0.5">
          {data.label}
        </span>
        {data.version != null && (
          <span className="text-xs text-gray-400">v{data.version}</span>
        )}
      </div>

      {data.history.length === 0 ? (
        <p className="text-sm text-gray-400">No temporal history recorded.</p>
      ) : (
        <div className="relative pl-5 border-l-2 border-gray-200 space-y-4">
          {data.history.map((entry: TimelineEntry, i: number) => {
            const color = REL_COLORS[entry.rel_type] ?? "#9ca3af";
            const isClosed = entry.valid_to != null;

            return (
              <div key={i} className="relative">
                {/* Dot on the timeline */}
                <div
                  className="absolute -left-[25px] top-1 w-3 h-3 rounded-full border-2 border-white"
                  style={{ backgroundColor: color }}
                />

                <div className={`text-sm ${isClosed ? "opacity-60" : ""}`}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="inline-block rounded px-1.5 py-0.5 text-xs font-mono font-medium text-white"
                      style={{ backgroundColor: color }}
                    >
                      {entry.rel_type}
                    </span>
                    <button
                      onClick={() => onEntityClick?.(entry.target_name)}
                      className="text-indigo-600 hover:text-indigo-800 hover:underline font-medium"
                    >
                      {entry.target_name}
                    </button>
                    <span className="text-xs text-gray-400">
                      ({entry.target_label})
                    </span>
                  </div>

                  <div className="mt-0.5 text-xs text-gray-400">
                    {formatDate(entry.valid_from)}
                    {isClosed && (
                      <>
                        {" "}
                        <span className="text-gray-300">&rarr;</span>{" "}
                        {formatDate(entry.valid_to)}
                      </>
                    )}
                    {entry.confidence != null && (
                      <span className="ml-2 text-gray-300">
                        conf: {(entry.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
