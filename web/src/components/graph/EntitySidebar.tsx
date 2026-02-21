import type { ReactNode } from "react";
import type { GraphEdge, GraphNode, EntityHistoryResponse } from "../../api/client";
import EntitySearch from "./EntitySearch";
import EntityDetails from "./EntityDetails";
import TemporalTimeline from "./TemporalTimeline";

interface EntitySidebarProps {
  selectedEntity: GraphNode | null;
  selectedEntityHistory: EntityHistoryResponse | null;
  edges: GraphEdge[];
  onSearch: (name: string) => void;
  onEntitySelect: (name: string) => void;
  footer?: ReactNode;
}

export default function EntitySidebar({
  selectedEntity,
  selectedEntityHistory,
  edges,
  onSearch: _onSearch,
  onEntitySelect,
  footer,
}: EntitySidebarProps) {
  return (
    <div className="flex flex-col h-full bg-white border-l border-gray-200">
      {/* Search */}
      <div className="p-4 border-b border-gray-200">
        <EntitySearch onEntitySelect={onEntitySelect} />
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {selectedEntity ? (
          <>
            {/* Entity Details */}
            <section>
              <EntityDetails entity={selectedEntity} edges={edges} />
            </section>

            {/* Temporal History */}
            <section>
              <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
                Temporal History
              </h4>
              <TemporalTimeline history={selectedEntityHistory} />
            </section>
          </>
        ) : (
          <div className="flex items-center justify-center h-48">
            <p className="text-sm text-gray-400">
              Click a node to view details
            </p>
          </div>
        )}
      </div>

      {/* Footer slot (e.g., Ingestion Diff) */}
      {footer && (
        <div className="p-4 border-t border-gray-200 shrink-0">{footer}</div>
      )}
    </div>
  );
}
