import type { GraphEdge, GraphNode } from "../../api/client";

const ENTITY_TYPE_COLORS: Record<string, string> = {
  Person: "#6366f1",
  Team: "#8b5cf6",
  Project: "#3b82f6",
  Technology: "#10b981",
  Process: "#f59e0b",
  Concept: "#ec4899",
  Asset: "#6b7280",
};

interface EntityDetailsProps {
  entity: GraphNode;
  edges: GraphEdge[];
}

export default function EntityDetails({ entity, edges }: EntityDetailsProps) {
  // Group edges by relationship type
  const edgesByType = edges.reduce<Record<string, GraphEdge[]>>((acc, edge) => {
    const type = edge.relationship_type;
    if (!acc[type]) acc[type] = [];
    acc[type].push(edge);
    return acc;
  }, {});

  const typeColor =
    ENTITY_TYPE_COLORS[entity.entity_type] ?? "#6b7280";

  return (
    <div className="space-y-4">
      {/* Entity header */}
      <div>
        <h3 className="text-lg font-semibold text-gray-800">{entity.name}</h3>
        <span
          className="inline-block mt-1 text-xs font-medium px-2.5 py-0.5 rounded-full text-white"
          style={{ backgroundColor: typeColor }}
        >
          {entity.entity_type}
        </span>
        {entity.summary && (
          <p className="mt-2 text-sm text-gray-600 leading-relaxed">
            {entity.summary}
          </p>
        )}
      </div>

      {/* Relationships */}
      <div>
        <h4 className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">
          Relationships
        </h4>
        {Object.keys(edgesByType).length === 0 ? (
          <p className="text-sm text-gray-400">No relationships found</p>
        ) : (
          <div className="space-y-3">
            {Object.entries(edgesByType).map(([relType, relEdges]) => (
              <div key={relType}>
                <p className="text-xs font-medium text-indigo-600 mb-1">
                  {relType}
                </p>
                <div className="space-y-1.5">
                  {relEdges.map((edge) => (
                    <div
                      key={edge.uuid}
                      className="text-sm text-gray-600 pl-3 border-l-2 border-gray-200"
                    >
                      <span className="font-medium text-gray-700">
                        {edge.source_name}
                      </span>
                      <span className="text-gray-400 mx-1">&rarr;</span>
                      <span className="font-medium text-gray-700">
                        {edge.target_name}
                      </span>
                      {edge.fact && (
                        <p className="text-xs text-gray-500 mt-0.5">
                          {edge.fact}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
