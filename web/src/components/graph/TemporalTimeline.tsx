import type { EntityHistoryResponse } from "../../api/client";

interface TemporalTimelineProps {
  history: EntityHistoryResponse | null;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return dateStr;
  }
}

export default function TemporalTimeline({ history }: TemporalTimelineProps) {
  if (!history || history.edges.length === 0) {
    return (
      <p className="text-sm text-gray-400">No temporal data</p>
    );
  }

  // Sort edges by valid_at ascending
  const sortedEdges = [...history.edges].sort((a, b) => {
    const aTime = a.valid_at ? new Date(a.valid_at).getTime() : 0;
    const bTime = b.valid_at ? new Date(b.valid_at).getTime() : 0;
    return aTime - bTime;
  });

  return (
    <div className="space-y-3">
      {sortedEdges.map((edge) => {
        const isActive = !edge.invalid_at;
        return (
          <div
            key={edge.uuid}
            className={`flex gap-3 text-sm ${isActive ? "" : "opacity-70"}`}
          >
            {/* Status dot */}
            <div className="flex flex-col items-center pt-1.5">
              <span
                className={`inline-block w-2.5 h-2.5 rounded-full shrink-0 ${
                  isActive ? "bg-green-400" : "bg-red-400"
                }`}
              />
              <div className="w-px flex-1 bg-gray-200 mt-1" />
            </div>

            {/* Content */}
            <div className="pb-3 min-w-0">
              <p className="font-medium text-gray-700">
                {edge.relationship_type}
              </p>
              <p className="text-gray-500 text-xs mt-0.5">
                {edge.source_name}
                <span className="mx-1 text-gray-300">&rarr;</span>
                {edge.target_name}
              </p>
              {edge.fact && (
                <p className="text-gray-500 text-xs mt-0.5 leading-relaxed">
                  {edge.fact}
                </p>
              )}
              <div className="mt-1 flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
                {edge.valid_at && (
                  <span className="text-gray-400">
                    Valid from: {formatDate(edge.valid_at)}
                  </span>
                )}
                {edge.invalid_at && (
                  <span className="text-red-500">
                    Invalidated: {formatDate(edge.invalid_at)}
                  </span>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
